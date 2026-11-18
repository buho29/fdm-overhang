# Comando "Voladizos FDM": pinta encima del modelo, como la vista de soportes de un laminador, lo que mira hacia
# abajo con menos del ángulo límite desde la horizontal (rojo -> naranja), los puentes (azul) y lo que apoya en la
# cama (verde). Con "Soportes en los voladizos" marca esas caras para Enviar al laminador.
import math
import time
import traceback

import adsk.core
import adsk.fusion

from .. import analysis as A
from ..i18n import tr
from .common import (API_MIN_OVERHANG, BEDS, BODIES, GROUP_ID, KEEP_EVENT, KEEP_ID, QUALITIES, TOL_CM, _add_run_button,
                     _app, _choice, _clear, _handlers, _load_settings, _mesh, _meshes, _mm, _native_token, _paint,
                     _prompt, _save_settings, _ui, _visible_bodies)
from .slicer_cmd import (SL_ROLES, _api_body, _api_cfg, _api_store, _count, _sl_edge, _sl_face, _sl_isolate, _sl_paint,
                         _sl_zoom)


_state = {}     # comando abierto y último resultado (útil para depurar)


_keep = {}      # capa que queda al cerrar: 'design', 'settings', 'bodies', 'face'. Solo en memoria


def _read(inputs):
    return {'bodies': _choice(inputs, 'bodies', BODIES), 'bed': _choice(inputs, 'bed', BEDS),
            'own_bed': inputs.itemById('own_bed').value, 'angle': inputs.itemById('angle').valueOne,
            'gradient': inputs.itemById('gradient').value, 'quality': _choice(inputs, 'quality', QUALITIES),
            'bridge': inputs.itemById('bridge').value,
            'bridge_max': round(inputs.itemById('bridge_max').value * 10, 4),   # mm
            'keep': inputs.itemById('keep').value, 'ov_solo': inputs.itemById('ov_solo').value}


def _update_visibility(inputs):
    pick = _choice(inputs, 'bodies', BODIES) == 'pick'
    face = _choice(inputs, 'bed', BEDS) == 'face'
    # después de analizar, el campo vacío se sustituye por un botón con los cuerpos (ver _ChangedHandler)
    shown = pick and bool(_state.get('picked')) and not _state.get('editing')
    inputs.itemById('body_sel').isVisible = pick and not shown
    btn = inputs.itemById('body_btn')
    btn.isVisible = shown
    if shown:
        names = [b.name for b in _state['picked'] if b.isValid]
        btn.text = ', '.join(names) if len(names) <= 2 else tr('%d cuerpos') % len(names)
    inputs.itemById('ov_solo').isVisible = pick
    inputs.itemById('face_sel').isVisible = face
    inputs.itemById('bridge_max').isVisible = inputs.itemById('bridge').value


def _legend(s):
    sq = '<font color="#%02x%02x%02x">■</font> %s'
    items = [sq % (A.RED[:3] + (tr('voladizo (menos de %d° desde la horizontal)') % s['angle'],))]
    if s['bridge']:
        items.append(sq % (A.BRIDGE_COLOR[:3] + (tr('puente (hasta %s mm)') % _mm(s['bridge_max']),)))
    items.append(sq % (A.BED_COLOR[:3] + (tr('apoyo en la cama'),)))
    return ' &nbsp; '.join(items)


def _draw(inputs):
    """Escribe el resultado y pinta la capa. Se llama desde executePreview: Fusion deshace la capa de la
    vista previa anterior al cambiar cualquier campo, y la de la última al cerrar el diálogo.
    El texto va antes que la capa porque cambiar un campo también deshace lo pintado; solo se cambia si es
    distinto, para no lanzar otra vista previa. Esa otra vista previa llega sin el botón pulsado: por eso lo que
    decide si se puede pintar es que las mallas ya estén calculadas, no el botón."""
    _clear()
    layers = []
    design = adsk.fusion.Design.cast(_app.activeProduct)
    try:
        s = _read(inputs)
        _save_settings(s)
        sel = inputs.itemById('body_sel')
        bodies = [sel.selection(i).entity for i in range(sel.selectionCount)]
        if not _state.get('editing'):
            bodies = bodies or _state.get('picked', [])
        sel = inputs.itemById('face_sel')
        face = sel.selection(0).entity if sel.selectionCount else None
        html, layers = _analyse(design, s, bodies, face, _state.get('run', False))
        _state.pop('run', None)
        if html is None:
            html = _prompt()
            _state.pop('last', None)   # no hay nada pintado que mantener al cerrar
        else:
            _state['last'] = {'design': design, 'settings': s, 'bodies': bodies, 'face': face}
    except Exception:
        html = '<b><font color="#d33">✖ %s</font></b><br>%s' % (
            tr('Error interno del complemento:'), traceback.format_exc().replace('\n', '<br>'))
    try:
        rows, lines = _ov_marked()
    except Exception:
        rows, lines = [], []
    if rows and _state.get('last'):
        html += '<br><br>' + '<br>'.join(rows)
    if _state.get('html') != html:
        _state['html'] = html
        inputs.itemById('info').formattedText = html
    if design:
        _paint(design, layers, GROUP_ID)
        if lines and _state.get('last'):
            _sl_paint(design, [], lines, GROUP_ID)
    _app.activeViewport.refresh()


# ------------------------------------------------ soportes en los voladizos, para Enviar al laminador
# El botón marca como soportes forzados las caras con voladizo de los cuerpos analizados. Se guarda al cerrar con
# Cerrar (execute), con los mismos atributos que Enviar al laminador, donde se ve y se corrige cara a cara: lo que se
# cambia en el diseño con el comando abierto, Fusion lo deshace si se cancela.

OV_ROLES = ['sl_sup_on', 'sl_sup_off']   # papeles de Enviar al laminador que se ven aquí


def _is_solid(body):
    return bool(adsk.fusion.BRepBody.cast(body)) and getattr(body, 'isSolid', False)


def _ov_marked():
    """(líneas del resultado, contornos [(puntos, color)]) de las caras con soportes de los cuerpos analizados, una
    vez pulsado el botón: el contorno lleva el color del papel, como en Enviar al laminador."""
    roles = dict((k, (rgb, label)) for k, _, _, rgb, label in SL_ROLES)
    sq = '<font color="#%02x%02x%02x">■</font> %s'
    rows, lines = [], []
    analysed = _state.get('geom') or {}
    shown = [m for t, (b, m) in (_state.get('marks') or {}).items() if t in analysed and b.isValid]
    for key in OV_ROLES:
        faces = [f for m in shown for f in m[key] if f.isValid]
        if not faces:
            continue
        rgb, label = roles[key]
        rows.append(sq % (rgb + ('%s: %s' % (tr(label), _count(0, len(faces))),)))
        for f in faces:
            lines += [(_sl_edge(e, f.body), rgb) for e in f.edges]
    return rows, lines


def _ov_load(bodies):
    """Lee lo guardado para los cuerpos que aún no están en _state['marks'] {token: (cuerpo, {papel: [caras]})}."""
    design = adsk.fusion.Design.cast(_app.activeProduct)
    marks = _state.setdefault('marks', {})
    for b in bodies:
        if not design or b.entityToken in marks:
            continue
        try:
            name, listed = _api_body(design, b)
        except ValueError:
            continue
        cfg = _api_cfg(design, name, listed)
        marks[b.entityToken] = (b, dict((k, [e for e in cfg[k] if e.isValid and adsk.fusion.BRepFace.cast(e)])
                                        for k in OV_ROLES))


def _face_overhang(face, body, up, bed, angle):
    """Área en voladizo de una cara (cm²), con su propia malla fina."""
    _, (c, n, idx) = _sl_face(face, body)
    return A.classify(c, n, idx, up, bed, angle, False, TOL_CM)[3]['overhang']


def _bridge_points(body, s, up, bed):
    """Centros de los triángulos de puente (hasta Puente máximo) de la malla analizada del cuerpo. Una cara sola no
    sabe si es un puente: hace falta ver las paredes de al lado."""
    c, _, idx, gap, _ = _mesh(body, s['quality'])
    cos_lim = math.cos(math.radians(max(0.0, s['angle'] - A.MARGIN_DEG)))
    pts = []
    for t, span in A.find_bridges(c, idx, up, bed, TOL_CM, gap, cos_lim).items():
        if span <= s['bridge_max'] / 10.0 + TOL_CM:
            v = [3 * idx[t + k] for k in range(3)]
            pts.append(tuple(sum(c[i + j] for i in v) / 3.0 for j in range(3)))
    return pts


def _is_bridge_face(face, pts):
    """Si alguno de los puntos de puente está sobre la cara (solo caras planas: los techos de puente lo son)."""
    if face.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
        return False
    bb, ev = face.boundingBox, face.evaluator
    lo, hi = bb.minPoint.asArray(), bb.maxPoint.asArray()
    for p in pts:
        if any(p[k] < lo[k] - TOL_CM or p[k] > hi[k] + TOL_CM for k in range(3)):
            continue
        pt = adsk.core.Point3D.create(*p)
        ok, prm = ev.getParameterAtPoint(pt)
        if not (ok and ev.isParameterOnFace(prm)):
            continue
        ok, q = ev.getPointAtParameter(prm)
        if ok and q.distanceTo(pt) < 10 * TOL_CM:
            return True
    return False


def _ov_add_overhangs(inputs):
    """Marca como soportes forzados las caras con voladizo de los cuerpos analizados, con los ajustes del diálogo y
    sin los puentes; las que ya tienen soportes (forzados o bloqueados) se quedan como están."""
    s = _read(inputs)
    geom = _state.get('geom') or {}
    bodies = [b for b, _, _ in geom.values() if _is_solid(b) and b.isValid]
    _ov_load(bodies)
    marks = _state['marks']
    for b in bodies:
        if b.entityToken not in marks:
            continue
        roles = marks[b.entityToken][1]
        have = set(_native_token(f) for k in roles for f in roles[k])
        _, up, bed = geom[b.entityToken]
        bridges = _bridge_points(b, s, up, bed) if s['bridge'] else []
        for face in b.faces:
            if _native_token(face) in have:
                continue
            if _face_overhang(face, b, up, bed, s['angle']) < API_MIN_OVERHANG:
                continue
            if bridges and _is_bridge_face(face, bridges):
                continue
            roles['sl_sup_on'].append(face)


def _ov_store(design):
    """Guarda en el diseño los soportes marcados de cada cuerpo analizado: sustituyen a las caras de esos papeles;
    las aristas y lo demás se quedan."""
    for b, faces in (_state.get('marks') or {}).values():
        if not b.isValid:
            continue
        try:
            name, listed = _api_body(design, b)
        except ValueError:
            continue
        cfg = _api_cfg(design, name, listed)
        for k, fs in faces.items():
            cfg[k] = ([e for e in cfg[k] if e.isValid and not adsk.fusion.BRepFace.cast(e)]
                      + [f for f in fs if f.isValid])
        _api_store(design, listed, cfg)


def _ov_store_bed(design, face):
    """Guarda la cara de la cama elegida como cama de su cuerpo en Enviar al laminador."""
    try:
        name, listed = _api_body(design, face.body)
    except ValueError:
        return   # no es de un sólido visible
    cfg = _api_cfg(design, name, listed)
    if cfg['bed'] == 'face' and cfg['face'] and cfg['face'].isValid \
            and _native_token(cfg['face']) == _native_token(face):
        return
    cfg['bed'], cfg['face'] = 'face', face
    _api_store(design, listed, cfg)


def _repaint_keep():
    """Vuelve a pintar la capa que se quedó al cerrar (fuera del diálogo, así que no se deshace sola).
    Recalcula las mallas: el modelo puede haber cambiado."""
    design = _keep.get('design')
    if not design or not design.isValid:
        _keep.clear()
        return
    _clear(KEEP_ID, design)
    _meshes.clear()
    try:
        bodies = [b for b in _keep['bodies'] if b.isValid]
        face = _keep['face'] if _keep['face'] and _keep['face'].isValid else None
        _, layers = _analyse(design, _keep['settings'], bodies, face)
        _paint(design, layers, KEEP_ID)
    finally:
        _meshes.clear()
    _app.activeViewport.refresh()


def _drop_keep():
    _clear(KEEP_ID, _keep.get('design'))
    _keep.clear()


def _analyse(design, s, picked, face, may_compute=True):
    """(html del resultado, [(coords, normales, colores) de cada cuerpo con algo que pintar]).
    s son los ajustes del diálogo (_read); picked, los cuerpos elegidos; face, la cara de la cama o None.
    Sin may_compute, si falta calcular alguna malla, devuelve (None, []) para esperar al botón."""
    _state.pop('geom', None)   # los cuerpos analizados: solo los del último análisis
    if not design:
        return tr('Abre un diseño (espacio de trabajo DISEÑO).'), []
    root = design.rootComponent

    if s['bodies'] == 'pick':
        bodies = picked
        if not bodies:
            return tr('Elige los cuerpos.'), []
    else:
        bodies = _visible_bodies(root)
        if not bodies:
            return tr('No hay cuerpos que analizar.'), []

    if s['bed'] == 'face':
        face = adsk.fusion.BRepFace.cast(face)
        if not face:
            return tr('Elige la cara plana que va sobre la cama.'), []
        _, n = face.evaluator.getNormalAtPoint(face.pointOnFace)
        up = A.unit((-n.x, -n.y, -n.z))   # la normal de la cara apunta hacia la cama
    else:
        up = (0.0, 0.0, 1.0) if s['bed'] == 'z' else (0.0, 1.0, 0.0)

    if not may_compute and any((b.entityToken, s['quality']) not in _meshes for b in bodies):
        return None, []

    t0 = time.time()
    meshes = [(b, _mesh(b, s['quality'])) for b in bodies]
    lows = [A.lowest(c, up) for _, (c, _, _, _, _) in meshes]
    bed = min(lows)
    _state['geom'] = dict((b.entityToken, (b, up, low if s['own_bed'] else bed)) for (b, _), low in zip(meshes, lows))

    total = over = on_bed = bridge = 0.0
    worst, span, long_span, tris, rows, layers = None, None, None, 0, [], []
    bridge_max = s['bridge_max'] / 10.0 if s['bridge'] else None   # cm
    for (b, (c, n, idx, gap, shown)), low in zip(meshes, lows):
        tc, tn, tcol, st = A.classify(c, n, idx, up, low if s['own_bed'] else bed, s['angle'], s['gradient'], TOL_CM,
                                      bridge_max, gap)
        tris += len(idx) // 3
        total, over, on_bed = total + st['total'], over + st['overhang'], on_bed + st['bed']
        bridge += st['bridge']
        span = max(span or 0.0, st['span']) if st['span'] is not None else span
        long_span = max(long_span or 0.0, st['long_span']) if st['long_span'] is not None else long_span
        if st['worst'] is not None:
            worst = st['worst'] if worst is None else min(worst, st['worst'])
            rows.append((st['overhang'], b.name))
        if tc:
            layers.append((A.lift_layer(tc, tn, shown, gap) if shown is not None else A.offset(tc, tn, gap), tn, tcol))

    lines = [_legend(s), '']
    if s['bodies'] == 'pick':   # el botón de la selección solo nombra hasta dos
        lines.append(tr('Cuerpos: %s') % ', '.join(b.name for b in bodies))
    if over:
        lines.append(tr('Voladizo: <b>%.0f mm²</b> (%.1f %% de la superficie), el peor a %.0f°')
                     % (over * 100, 100 * over / total, worst))
        if len(rows) > 1:
            lines += ['&nbsp; • %s: %.0f mm²' % (name, a * 100) for a, name in sorted(rows, reverse=True)]
    else:
        lines.append(tr('Sin voladizos.'))
    if bridge:
        lines.append(tr('Puentes: <b>%.0f mm²</b>, el más largo %s mm') % (bridge * 100, _mm(span * 10)))
    if long_span:
        lines.append('<font color="#c80">⚠ %s</font>' % (tr('Puente de %s mm, más que el máximo: sigue en rojo.')
                                                         % _mm(long_span * 10)))
    if on_bed:
        lines.append(tr('Apoyo en la cama: %.0f mm²') % (on_bed * 100))
    else:
        lines.append('<font color="#c80">⚠ %s</font>'
                     % tr('Nada apoya en plano sobre la cama: reorienta la pieza o usa borde de adherencia.'))
    lines.append('<font color="#888">%s</font>' % (tr('%d triángulos en %.2f s') % (tris, time.time() - t0)))
    _state['result'] = {'total': total, 'overhang': over, 'bed': on_bed, 'worst': worst, 'bridge': bridge,
                        'span': span, 'long_span': long_span}
    return '<br>'.join(lines), layers


class _CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            _state['cmd'] = cmd
            _drop_keep()   # mientras el diálogo está abierto se ve la vista previa
            _state.pop('html', None)
            _state.pop('run', None)
            for k in ('picked', 'editing', 'marks', 'geom', 'zoom', 'camera'):
                _state.pop(k, None)
            # Cerrar guarda los soportes marcados para el laminador (execute); Cancelar los descarta
            cmd.okButtonText = tr('Cerrar')
            cmd.cancelButtonText = tr('Cancelar')
            # el tamaño inicial, para que Fusion lo tenga en cuenta al colocar el diálogo la primera vez: con
            # solo el mínimo, lo coloca con su ancho por defecto y luego crece fuera de la pantalla
            cmd.setDialogInitialSize(380, 620)
            cmd.setDialogMinimumSize(380, 300)
            inputs = cmd.commandInputs
            s = _load_settings()

            dd = inputs.addDropDownCommandInput('bodies', tr('Cuerpos'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in BODIES:
                dd.listItems.add(tr(label), key == s['bodies'])
            sel = inputs.addSelectionInput('body_sel', tr('Selección'), tr('Elige los cuerpos.'))
            for f in ('SolidBodies', 'SurfaceBodies', 'MeshBodies'):
                sel.addSelectionFilter(f)
            sel.setSelectionLimits(0, 0)
            # al analizar, el campo se vacía (el resaltado taparía la capa) y en su sitio sale este botón
            btn = inputs.addBoolValueInput('body_btn', tr('Selección'), False, '', False)
            btn.tooltip = tr('Los cuerpos analizados. Pulsa para cambiarlos.')
            solo = inputs.addBoolValueInput('ov_solo', tr('Ver solo los elegidos'), True, '', bool(s['ov_solo']))
            solo.tooltip = tr('Al analizar, oculta todo lo demás y acerca la vista a los cuerpos elegidos. Mientras '
                              'los cambias se ve todo, para poder elegir otros. Al cerrar el diálogo vuelve a verse '
                              'todo, como estaba.')

            dd = inputs.addDropDownCommandInput('bed', tr('Cama'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in BEDS:
                dd.listItems.add(tr(label), key == s['bed'])
            sel = inputs.addSelectionInput('face_sel', tr('Cara sobre la cama'),
                                           tr('Elige la cara plana que va sobre la cama.'))
            sel.addSelectionFilter('PlanarFaces')
            sel.setSelectionLimits(0, 1)
            inputs.addBoolValueInput('own_bed', tr('Cada cuerpo sobre la cama'), True, '', bool(s['own_bed']))

            sl = inputs.addIntegerSliderCommandInput('angle', tr('Ángulo límite (°)'), 0, 89)
            sl.valueOne = int(s['angle'])
            inputs.addBoolValueInput('gradient', tr('Degradado'), True, '', bool(s['gradient']))
            br = inputs.addBoolValueInput('bridge', tr('Detectar puentes'), True, '', bool(s['bridge']))
            br.tooltip = tr('Pinta en otro color los techos planos tendidos entre dos paredes, que se imprimen sin '
                            'soporte si no son muy largos. Sin marcar, salen como voladizo.')
            inputs.addValueInput('bridge_max', tr('Puente máximo'), 'mm',
                                 adsk.core.ValueInput.createByString('%s mm' % s['bridge_max']))
            dd = inputs.addDropDownCommandInput('quality', tr('Calidad de la malla'),
                                                adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label, _ in QUALITIES:
                dd.listItems.add(tr(label), key == s['quality'])
            keep = inputs.addBoolValueInput('keep', tr('Mantener al cerrar'), True, '', bool(s['keep']))
            keep.tooltip = tr('La capa se queda al cerrar el diálogo y se recalcula cada vez que cambia el modelo. '
                              'Se quita al volver a abrir el diálogo. No se guarda en el archivo.')
            _add_run_button(inputs, 'run')
            btn = inputs.addBoolValueInput('ov_add_over', '', False, '', False)
            btn.text = tr('Soportes en los voladizos')
            btn.isFullWidth = True
            btn.tooltip = tr('Marca como soportes forzados, para Enviar al laminador, las caras de los cuerpos '
                             'analizados con al menos 1 mm² en voladizo, sin los puentes. Se guarda al cerrar con '
                             'Cerrar (no con Cancelar); cada cara se corrige en Enviar al laminador.')
            inputs.addTextBoxCommandInput('info', tr('Resultado'), '', 10, True).isFullWidth = True
            _update_visibility(inputs)

            for ev, h in ((cmd.executePreview, _PreviewHandler()), (cmd.inputChanged, _ChangedHandler()),
                          (cmd.execute, _ExecuteHandler()), (cmd.destroy, _DestroyHandler())):
                ev.add(h)
                _handlers.append(h)
        except Exception:
            _ui.messageBox(tr('Voladizos FDM: error') + '\n' + traceback.format_exc())


def _ov_solo_bodies(inputs):
    """Los cuerpos analizados que se ven solos (Ver solo los elegidos), o [] si se ve todo: con Todos los visibles,
    y mientras se cambia la selección, para poder elegir otros."""
    if not (inputs.itemById('ov_solo').value and _choice(inputs, 'bodies', BODIES) == 'pick'
            and not _state.get('editing')):
        return []
    return [b for b in _state.get('picked') or [] if b.isValid]


class _PreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        inputs = args.command.commandInputs
        bodies = _ov_solo_bodies(inputs)
        if bodies:
            # antes de pintar, como en Enviar al laminador: Fusion acaba de volver a encenderlo todo
            try:
                _sl_isolate(adsk.fusion.Design.cast(_app.activeProduct), bodies)
            except Exception:
                pass   # verlo todo no impide trabajar
        _draw(inputs)
        zoom = _state.pop('zoom', None)
        if zoom:
            try:
                _state.setdefault('camera', _app.activeViewport.camera)   # la de antes del diálogo
                if zoom == 'all':
                    _app.activeViewport.fit()
                elif bodies:
                    _sl_zoom(bodies)
            except Exception:
                pass


class _ExecuteHandler(adsk.core.CommandEventHandler):
    """Cerrar (y empezar otro comando con este abierto): guarda para Enviar al laminador los soportes marcados y
    la cara de la cama elegida."""
    def notify(self, args):
        try:
            design = adsk.fusion.Design.cast(_app.activeProduct)
            if not design:
                return
            # la cara de la cama se lee antes: tocar los atributos de una cara la quita de su campo
            inputs = args.command.commandInputs
            sel = inputs.itemById('face_sel')
            face = sel.selection(0).entity if _choice(inputs, 'bed', BEDS) == 'face' and sel.selectionCount else None
            if _state.get('marks'):
                _ov_store(design)
            if face and face.isValid:
                _ov_store_bed(design, face)
        except Exception:
            _ui.messageBox(tr('Voladizos FDM: error') + '\n' + traceback.format_exc())


class _ChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        if args.input.id == 'info':
            return
        # args.inputs puede ser solo parte del diálogo: hacen falta todos los del comando
        inputs = args.firingEvent.sender.commandInputs
        if args.input.id == 'run':
            _state['run'] = True   # lo atiende la vista previa que Fusion lanza a continuación
            # el resaltado de la selección tapa la capa: se vacía el campo, se recuerdan los cuerpos y en su sitio
            # sale un botón con sus nombres
            sel = inputs.itemById('body_sel')
            if _choice(inputs, 'bodies', BODIES) == 'pick' and (sel.selectionCount or _state.get('editing')):
                _state['picked'] = [sel.selection(i).entity for i in range(sel.selectionCount)]
                _state['editing'] = False   # antes de vaciar: la vista previa que lanza ya usa los recordados
                _state['zoom'] = 'bodies'   # si se ven solos, la vista va a ellos (_PreviewHandler)
                sel.clearSelection()
                _update_visibility(inputs)
            return
        if args.input.id == 'body_btn':
            # vuelve el campo con los cuerpos analizados, para quitar o añadir
            _state['editing'] = True
            sel = inputs.itemById('body_sel')
            sel.clearSelection()
            for b in _state.get('picked') or []:
                if b.isValid:
                    sel.addSelection(b)
            _update_visibility(inputs)
            sel.hasFocus = True
            return
        if args.input.id == 'ov_add_over':
            _ov_add_overhangs(inputs)
            return
        if args.input.id == 'ov_solo':
            _state['zoom'] = 'bodies' if args.input.value else 'all'
        _update_visibility(inputs)
        if args.input.id == 'bodies' and _choice(inputs, 'bodies', BODIES) == 'pick':
            inputs.itemById('body_sel').hasFocus = True
        elif args.input.id == 'bed' and _choice(inputs, 'bed', BEDS) == 'face':
            inputs.itemById('face_sel').hasFocus = True


class _DestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            if _state.get('cmd') is not None and args.command != _state['cmd']:
                return   # se ha vuelto a pulsar el botón con el diálogo abierto: el nuevo ya está en marcha
            _clear()
            _meshes.clear()
            _state.pop('cmd', None)
            _state.pop('html', None)
            _state.pop('zoom', None)
            camera = _state.pop('camera', None)
            if camera:
                _app.activeViewport.camera = camera   # el acercamiento dura lo que el diálogo
            last = _state.pop('last', None)
            if last and last['settings'].get('keep') and last['design']:
                _keep.update(last)
                # se pinta cuando el comando ya ha terminado: lo que se pinta dentro, Fusion lo deshace
                _app.fireCustomEvent(KEEP_EVENT)
            _app.activeViewport.refresh()
        except Exception:
            pass


class _KeepHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        try:
            _repaint_keep()
        except Exception:
            pass
