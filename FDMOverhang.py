# Add-in de Fusion 360 con dos comandos en INSPECCIONAR:
# - "Voladizos FDM": pinta encima del modelo, como la vista de soportes de un laminador, lo que mira hacia abajo
#   con menos del ángulo límite desde la horizontal (rojo -> naranja), los puentes (azul) y lo que apoya en la
#   cama (verde).
# - "Espesor y espacios": mapa de color del espesor de las paredes o del espacio entre superficies (rojo lo
#   estrecho -> azul lo ancho), o solo lo que no llega al mínimo.
# Son gráficos personalizados: no tocan el diseño ni la línea de tiempo y se borran al cerrar el diálogo.
# - "Enviar al laminador": exporta un cuerpo en STL con su cama, dónde forzar o prohibir la costura y los soportes
#   (lo elegido y lo que tiene poca holgura), y lo pasa a slicer-paint, que genera el 3MF pintado.
import importlib
import json
import os
import sys
import time
import traceback

import adsk.core
import adsk.fusion

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import overhang.i18n  # noqa: E402
import overhang.analysis  # noqa: E402
import overhang.thickness  # noqa: E402
import overhang.slicer  # noqa: E402
for _m in (overhang.i18n, overhang.analysis, overhang.thickness, overhang.slicer):   # recargar al reiniciar el add-in
    importlib.reload(_m)
from overhang import analysis as A  # noqa: E402
from overhang import thickness as T  # noqa: E402
from overhang import slicer as S  # noqa: E402
from overhang.i18n import tr, set_language  # noqa: E402

CMD_ID = 'buhoFdmOverhang'
WORKSPACE_ID = 'FusionSolidEnvironment'   # DISEÑO
PANEL_IDS = ('InspectPanel',)              # INSPECCIONAR (hay paneles con el mismo id en otros espacios)
GROUP_ID = 'fdm_overhang'          # capa de la vista previa, dentro del diálogo
KEEP_ID = 'fdm_overhang_keep'      # capa que se queda al cerrar con "Mantener al cerrar"
KEEP_EVENT = 'buhoFdmOverhangKeep'
TH_CMD_ID = 'buhoFdmThickness'
TH_GROUP_ID = 'fdm_thickness'
TH_KEEP_ID = 'fdm_thickness_keep'
TH_KEEP_EVENT = 'buhoFdmThicknessKeep'
SL_CMD_ID = 'buhoFdmSlicer'
SL_GROUP_ID = 'fdm_slicer'
SL_DONE_EVENT = 'buhoFdmSlicerDone'
SETTINGS = os.path.join(HERE, 'settings.json')
TOL_CM = 0.001   # lo que está a menos de 0.01 mm de la cama apoya en ella

BODIES = [('visible', 'Todos los visibles'), ('pick', 'Elegidos')]
BEDS = [('z', 'Plano XY (Z arriba)'), ('y', 'Plano XZ (Y arriba)'), ('face', 'Cara plana elegida')]
RESOLUTIONS = [('coarse', 'Rápida (2 mm)', 0.2), ('normal', 'Normal (1 mm)', 0.1), ('fine', 'Fina (0,5 mm)', 0.05)]
PAINTS = [('map', 'Mapa de color'), ('thin', 'Solo lo que no llega al mínimo')]
TH_SURFACE_TOL = 0.002   # cm: desviación de la malla del espesor respecto a la superficie
GAP_SURFACE_TOL = 0.0005  # cm: más fina, porque se miden holguras de décimas entre dos superficies curvas
GAP_BACK = 0.001          # cm: hasta 0,01 mm de separación o de solape cuenta como que dos caras se tocan
GAP_MARGIN = 2 * GAP_SURFACE_TOL   # cm: error de la medida entre dos curvas, una holgura justa no es fallo
MODES = [('thickness', 'Espesor'), ('gap', 'Espacio')]
XRAY_OPACITY = 0.25
BUSY_DELAY = 1       # s: si la medida acaba antes, no llega a salir la ventana de progreso
BUSY_EVERY = 2000    # rayos entre dos actualizaciones de la ventana de progreso
QUALITIES = [('low', 'Baja', adsk.fusion.TriangleMeshQualityOptions.LowQualityTriangleMesh),
             ('normal', 'Normal', adsk.fusion.TriangleMeshQualityOptions.NormalQualityTriangleMesh),
             ('high', 'Alta', adsk.fusion.TriangleMeshQualityOptions.HighQualityTriangleMesh)]

_app = adsk.core.Application.get()
_ui = _app.userInterface
_handlers = []
_state = {}     # comando abierto y último resultado (útil para depurar)
_meshes = {}    # (entityToken, calidad) -> malla en coordenadas del raíz; se vacía al cerrar el diálogo
_keep = {}      # capa que queda al cerrar: 'design', 'settings', 'bodies', 'face'. Solo en memoria
_th_state = {}  # lo mismo para el espesor de pared
_th_meshes = {}
_gap_cache = {}  # (cuerpos, resolución) -> medida de todos juntos, porque cada uno depende de los demás
_th_keep = {}   # 'design', 'layers', 'sig': la capa de espesor que queda al cerrar (no se puede recalcular fuera)


def _default_bed():
    try:
        z_up = (_app.preferences.generalPreferences.defaultModelingOrientation
                == adsk.core.DefaultModelingOrientations.ZUpModelingOrientation)
    except Exception:
        z_up = True
    return 'z' if z_up else 'y'


def _load_settings():
    s = {'bodies': 'visible', 'bed': _default_bed(), 'own_bed': False, 'angle': 45, 'gradient': True,
         'quality': 'normal', 'keep': False, 'bridge': True, 'bridge_max': 23.0,
         'th_bodies': 'visible', 'th_res': 'coarse', 'th_paint': 'map', 'th_limit': 0.8, 'th_lo': 0.0,
         'th_hi': 4.0, 'th_keep': False, 'th_mode': 'thickness', 'gap_limit': 0.1, 'gap_lo': 0.0, 'gap_hi': 2.0,
         'th_xray': True, 'sl_bed': _default_bed(), 'sl_gap': True, 'sl_gap_limit': 0.4, 'sl_res': 'normal',
         'sl_open': 'orca', 'sl_dir': '', 'slicer_paint': ''}
    try:
        with open(SETTINGS, encoding='utf-8') as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    # las selecciones no se guardan: se vuelve a lo que no necesita elegir nada
    for k in ('bodies', 'th_bodies'):
        if s[k] == 'pick':
            s[k] = 'visible'
    for k in ('bed', 'sl_bed'):
        if s[k] == 'face':
            s[k] = _default_bed()
    return s


def _save_settings(s):
    """Guarda los ajustes de un comando sin perder los del otro."""
    try:
        with open(SETTINGS, encoding='utf-8') as f:
            all_s = json.load(f)
    except (OSError, ValueError):
        all_s = {}
    all_s.update(s)
    try:
        with open(SETTINGS, 'w', encoding='utf-8') as f:
            json.dump(all_s, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def _add_run_button(inputs, key):
    """Botón que lanza el análisis: al abrir el diálogo no se calcula nada, porque en una pieza grande bloquearía
    Fusion antes de poder ajustar nada."""
    btn = inputs.addBoolValueInput(key, '', False, '', False)
    btn.text = tr('Analizar')
    btn.isFullWidth = True   # sin esto, el texto sale también como etiqueta a la izquierda
    btn.tooltip = tr('Calcula con los ajustes actuales. Después, lo que no necesita volver a medir se actualiza solo.')
    return btn


def _prompt():
    return tr('Pulsa <b>Analizar</b> para ver el resultado.')


def _choice(inputs, key, options):
    item = inputs.itemById(key).selectedItem
    return options[item.index][0] if item else options[0][0]


def _read(inputs):
    return {'bodies': _choice(inputs, 'bodies', BODIES), 'bed': _choice(inputs, 'bed', BEDS),
            'own_bed': inputs.itemById('own_bed').value, 'angle': inputs.itemById('angle').valueOne,
            'gradient': inputs.itemById('gradient').value, 'quality': _choice(inputs, 'quality', QUALITIES),
            'bridge': inputs.itemById('bridge').value,
            'bridge_max': round(inputs.itemById('bridge_max').value * 10, 4),   # mm
            'keep': inputs.itemById('keep').value}


def _visible_bodies(root):
    found = [b for b in root.bRepBodies if b.isVisible] + [b for b in root.meshBodies if b.isVisible]
    for occ in root.allOccurrences:
        found += [b for b in occ.bRepBodies if b.isVisible] + [b for b in occ.meshBodies if b.isVisible]
    return found


def _display_tolerance(native):
    """Tolerancia (cm) de la malla con la que Fusion pinta el cuerpo."""
    try:
        return native.meshManager.displayMeshes.bestMesh.surfaceTolerance
    except Exception:
        return 0.01


def _mesh(body, quality):
    """(coords, normales, índices, separación, tolerancia de pantalla) del cuerpo en coordenadas del raíz (cm),
    guardada mientras dure el diálogo. La separación es el peor caso de lo que se apartan las dos mallas (A.lift);
    la tolerancia de pantalla es None si se pinta la misma malla que se analiza."""
    key = (body.entityToken, quality)
    if key not in _meshes:
        native = body.nativeObject or body
        mesh_body = adsk.fusion.MeshBody.cast(native)
        if mesh_body:
            m = mesh_body.displayMesh
            gap, shown = A.lift(0.0, 0.0), None   # se pinta la misma malla que se analiza
        else:
            calc = native.meshManager.createMeshCalculator()
            calc.setQuality(dict((k, q) for k, _, q in QUALITIES)[quality])
            m = calc.calculate()
            shown = _display_tolerance(native)
            gap = A.lift(calc.surfaceTolerance, shown)
        coords, normals = list(m.nodeCoordinatesAsDouble), list(m.normalVectorsAsDouble)
        if body.assemblyContext:
            coords, normals = A.transform(coords, normals, body.assemblyContext.transform2.asArray())
        _meshes[key] = (coords, normals, list(m.nodeIndices), gap, shown)
    return _meshes[key]


def _clear(group_id=GROUP_ID, design=None):
    design = design or adsk.fusion.Design.cast(_app.activeProduct)
    if design and design.isValid:
        groups = design.rootComponent.customGraphicsGroups
        for g in [g for g in groups if g.id == group_id]:
            g.deleteMe()


def _paint(design, layers, group_id):
    if not layers:
        return
    grp = design.rootComponent.customGraphicsGroups.add()
    grp.id = group_id
    for tc, tn, tcol in layers:
        coords = adsk.fusion.CustomGraphicsCoordinates.create(tc)
        coords.colors = tcol
        mesh = grp.addMesh(coords, list(range(len(tc) // 3)), tn, [])
        mesh.color = adsk.fusion.CustomGraphicsVertexColorEffect.create()
        mesh.depthPriority = 1   # por encima del cuerpo donde coincidan


def _update_visibility(inputs):
    pick = _choice(inputs, 'bodies', BODIES) == 'pick'
    face = _choice(inputs, 'bed', BEDS) == 'face'
    inputs.itemById('body_sel').isVisible = pick
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
    if _state.get('html') != html:
        _state['html'] = html
        inputs.itemById('info').formattedText = html
    if design:
        _paint(design, layers, GROUP_ID)
    _app.activeViewport.refresh()


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
            cmd.isOKButtonVisible = False   # solo se mira: no hay nada que aceptar
            cmd.cancelButtonText = tr('Cerrar')
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
            inputs.addTextBoxCommandInput('info', tr('Resultado'), '', 10, True).isFullWidth = True
            _update_visibility(inputs)

            for ev, h in ((cmd.executePreview, _PreviewHandler()), (cmd.inputChanged, _ChangedHandler()),
                          (cmd.destroy, _DestroyHandler())):
                ev.add(h)
                _handlers.append(h)
        except Exception:
            _ui.messageBox(tr('Voladizos FDM: error') + '\n' + traceback.format_exc())


class _PreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        _draw(args.command.commandInputs)


class _ChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        if args.input.id == 'info':
            return
        if args.input.id == 'run':
            _state['run'] = True   # lo atiende la vista previa que Fusion lanza a continuación
            return
        # args.inputs puede ser solo parte del diálogo: hacen falta todos los del comando
        inputs = args.firingEvent.sender.commandInputs
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


class _TerminatedHandler(adsk.core.ApplicationCommandEventHandler):
    """Al terminar cualquier comando que pueda haber cambiado el modelo: recalcula la capa de voladizos
    mantenida y quita la de espesor si sus cuerpos han cambiado (esa no se puede recalcular fuera del diálogo)."""
    def notify(self, args):
        try:
            if (args.commandId in (CMD_ID, TH_CMD_ID, SL_CMD_ID, 'SelectCommand')
                    or args.terminationReason != adsk.core.CommandTerminationReason.CompletedTerminationReason):
                return
            design = _keep.get('design')
            if design and design.isValid and _app.activeProduct == design:
                _app.fireCustomEvent(KEEP_EVENT)
            if _th_keep:
                _app.fireCustomEvent(TH_KEEP_EVENT)
        except Exception:
            pass


# ======================================================================== espesor de pared

def _th_read(inputs):
    return {'th_bodies': _choice(inputs, 'th_bodies', BODIES), 'th_res': _choice(inputs, 'th_res', RESOLUTIONS),
            'th_paint': _choice(inputs, 'th_paint', PAINTS),
            'th_limit': round(inputs.itemById('th_limit').value * 10, 4),   # mm
            'th_lo': round(inputs.itemById('th_lo').value * 10, 4), 'th_hi': round(inputs.itemById('th_hi').value * 10, 4),
            'th_keep': inputs.itemById('th_keep').value, 'th_mode': _choice(inputs, 'th_mode', MODES),
            'th_xray': inputs.itemById('th_xray').value,
            'gap_limit': round(inputs.itemById('gap_limit').value * 10, 4),
            'gap_lo': round(inputs.itemById('gap_lo').value * 10, 4),
            'gap_hi': round(inputs.itemById('gap_hi').value * 10, 4)}


class _Busy:
    """Ventana de progreso mientras se mide: el diálogo no responde hasta que acaba la medida. steps es el número
    de cuerpos; advance(i, f) indica que va por la fracción f del cuerpo i, y drawing() que ya solo queda colorear y
    pintar. Se queda en _th_state['busy'] y la cierra _th_draw al acabar de pintar. Un fallo de la ventana no puede
    estropear la medida. No usar adsk.doEvents() aquí: dentro de una vista previa colgó y cerró Fusion."""

    def __init__(self, steps):
        self.steps = steps
        self.dlg = None
        try:
            dlg = _ui.createProgressDialog()
            dlg.isCancelButtonShown = False
            dlg.show(tr('Espesor y espacios'), tr('Midiendo… %p %'), 0, 1000, BUSY_DELAY)
            self.dlg = dlg
        except RuntimeError as e:
            _state.setdefault('busy_errors', []).append(str(e))
        _th_state['busy'] = self

    def drawing(self):
        # sin tocar la barra: si llega al máximo, la ventana se cierra sola
        if self.dlg:
            try:
                self.dlg.message = tr('Dibujando…')
            except RuntimeError as e:
                _state.setdefault('busy_errors', []).append(str(e))
                self.dlg = None

    def advance(self, i, f):
        if self.dlg:
            try:
                self.dlg.progressValue = int(1000 * (i + f) / self.steps)
            except RuntimeError as e:
                _state.setdefault('busy_errors', []).append(str(e))
                self.dlg = None

    def close(self):
        if self.dlg:
            try:
                self.dlg.hide()
            except RuntimeError as e:
                _state.setdefault('busy_errors', []).append(str(e))


def _th_cast(mesh_body, coords, indices, tick=None):
    """Espesor (cm) de cada triángulo: distancia desde su centro, por la normal hacia dentro, hasta el primer
    choque con la malla (sin contar el propio triángulo, que está a distancia 0). tick(f) avisa de la fracción hecha."""
    P, V = adsk.core.Point3D.create, adsk.core.Vector3D.create
    out = []
    total = len(indices) // 3
    for ray in T.rays(coords, indices):
        if tick and len(out) % BUSY_EVERY == 0:
            tick(len(out) / total)
        w = T.NO_HIT
        if ray:
            o = P(*ray[0])
            for hit in mesh_body.calculateCollisionsWithRay(o, V(*ray[1])):
                d = o.distanceTo(hit)
                if d > 1e-5:
                    w = d
                    break
        out.append(w)
    return out


def _temp_meshes(design, meshes):
    """Crea cuerpos de malla temporales: los rayos solo se pueden lanzar contra cuerpos de malla. Devuelve los
    objetos creados, el último es la operación base si la hay; se borran con _drop_temp (dentro de la vista
    previa, Fusion los desharía igualmente)."""
    root = design.rootComponent
    base = None
    if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        base = root.features.baseFeatures.add()
        base.startEdit()
    tmps = []
    try:
        for coords, indices in meshes:
            tmp = root.meshBodies.addByTriangleMeshData(coords, indices, [], [])
            tmp.isLightBulbOn = False
            tmps.append(tmp)
    finally:
        if base:
            base.finishEdit()
    return tmps + ([base] if base else [])


def _drop_temp(objs):
    for obj in objs:   # borrar la base no borra los cuerpos de malla: ella va la última
        try:
            if obj and obj.isValid:
                obj.deleteMe()
        except Exception:
            pass


def _th_solid(native, coords, indices, tick=None):
    """Espesor de los triángulos de un cuerpo sólido, con una copia temporal en malla."""
    design = adsk.fusion.Design.cast(native.parentComponent.parentDesign)
    objs = _temp_meshes(design, [(coords, indices)])
    try:
        return _th_cast(objs[0], coords, indices, tick)
    finally:
        _drop_temp(objs)


def _th_mesh(body, res, tick=None):
    """(coords, normales, índices, espesor de cada triángulo, malla cerrada, separación) del cuerpo en
    coordenadas del raíz (cm), guardada mientras dure el diálogo."""
    key = (body.entityToken, res)
    if key not in _th_meshes:
        native = body.nativeObject or body
        mesh_body = adsk.fusion.MeshBody.cast(native)
        if mesh_body:
            pm = mesh_body.mesh
            coords, normals, idx = T.refine(list(pm.nodeCoordinatesAsDouble), list(pm.triangleNodeIndices),
                                            dict((k, v) for k, _, v in RESOLUTIONS)[res])
            thick, closed, gap = _th_cast(mesh_body, coords, idx, tick), mesh_body.isClosed, A.lift(0.0, 0.0)
        else:
            calc = native.meshManager.createMeshCalculator()
            calc.maxSideLength = dict((k, v) for k, _, v in RESOLUTIONS)[res]
            calc.surfaceTolerance = TH_SURFACE_TOL
            m = calc.calculate()
            coords, normals, idx = list(m.nodeCoordinatesAsDouble), list(m.normalVectorsAsDouble), list(m.nodeIndices)
            thick, closed = _th_solid(native, coords, idx, tick), True
            gap = A.lift(TH_SURFACE_TOL, _display_tolerance(native))
        thick = T.convex_min(coords, idx, thick)   # cantos de las paredes finas
        if body.assemblyContext:   # el espesor no cambia al mover la pieza
            coords, normals = A.transform(coords, normals, body.assemblyContext.transform2.asArray())
        _th_meshes[key] = (coords, normals, idx, thick, closed, gap)
    return _th_meshes[key]


def _th_legend(s, prefix='th_'):
    sq = '<font color="#%02x%02x%02x">■</font>'
    if s['th_paint'] == 'thin':
        return '%s %s' % (sq % T.THIN[:3], tr('menos de %s mm') % _mm(s[prefix + 'limit']))
    lo, hi = s[prefix + 'lo'], s[prefix + 'hi']
    steps = [lo + (hi - lo) * k / 4.0 for k in range(5)]
    return ' '.join('%s %s' % (sq % T.color(v, lo, hi)[:3], _mm(v)) for v in steps) + ' mm'


def _mm(v):
    return ('%.2f' % v).rstrip('0').rstrip('.')


def _th_signature(bodies):
    """Lo que cambia si cambia la geometría de los cuerpos: para saber si la capa mantenida sigue valiendo."""
    sig = []
    for b in bodies:
        if not b.isValid:
            return None
        bb = b.boundingBox
        sig.append((round(getattr(b, 'volume', 0.0), 9), round(getattr(b, 'area', 0.0), 9),
                    tuple(round(v, 6) for v in bb.minPoint.asArray() + bb.maxPoint.asArray())))
    return sig


def _gap_mesh(body, res):
    """(coords, normales, índices, malla cerrada, separación de la capa) del cuerpo en coordenadas del raíz."""
    native = body.nativeObject or body
    mesh_body = adsk.fusion.MeshBody.cast(native)
    if mesh_body:
        pm = mesh_body.mesh
        coords, normals, idx = T.refine(list(pm.nodeCoordinatesAsDouble), list(pm.triangleNodeIndices),
                                        dict((k, v) for k, _, v in RESOLUTIONS)[res])
        closed, lift = mesh_body.isClosed, A.lift(0.0, 0.0)
    else:
        calc = native.meshManager.createMeshCalculator()
        calc.maxSideLength = dict((k, v) for k, _, v in RESOLUTIONS)[res]
        calc.surfaceTolerance = GAP_SURFACE_TOL
        m = calc.calculate()
        coords, normals, idx = list(m.nodeCoordinatesAsDouble), list(m.normalVectorsAsDouble), list(m.nodeIndices)
        closed, lift = True, A.lift(GAP_SURFACE_TOL, _display_tolerance(native))
    if body.assemblyContext:
        coords, normals = A.transform(coords, normals, body.assemblyContext.transform2.asArray())
    return coords, normals, idx, closed, lift


def _gap_key(bodies, res, cast=None):
    return tuple(b.entityToken for b in bodies), res, cast


def _gap_measure(design, bodies, res, cast=None):
    """Lo que tiene delante cada triángulo de cada cuerpo: su propio cuerpo u otro. Cada cuerpo se mira por
    separado para poder distinguir el espacio del contacto y del solape. Se guarda mientras dure el diálogo.
    cast: índices de los cuerpos desde los que se lanzan rayos (None, todos); los demás solo sirven de obstáculo
    y su resultado es None."""
    key = _gap_key(bodies, res, cast)
    if key in _gap_cache:
        return _gap_cache[key]
    P, V = adsk.core.Point3D.create, adsk.core.Vector3D.create
    meshes = [_gap_mesh(b, res) for b in bodies]
    boxes = []
    for m in meshes:
        xyz = [m[0][i::3] for i in range(3)]
        boxes.append((tuple(min(v) for v in xyz), tuple(max(v) for v in xyz)))
    cast = range(len(meshes)) if cast is None else cast
    busy = _Busy(len(cast))
    objs = _temp_meshes(design, [(m[0], m[2]) for m in meshes])
    results = [None] * len(meshes)

    def other_body(j, point, direction, vec):
        back = P(point[0] - GAP_BACK * direction[0], point[1] - GAP_BACK * direction[1],
                 point[2] - GAP_BACK * direction[2])
        hits = [back.distanceTo(h) for h in objs[j].calculateCollisionsWithRay(back, vec)]
        return T.classify_other(hits, GAP_BACK, meshes[j][3])

    try:
        for step, i in enumerate(cast):
            m = meshes[i]
            vals, kinds, who = [], [], []
            total = len(m[2]) // 3
            for ray in T.rays(m[0], m[2], outward=True):
                if len(vals) % BUSY_EVERY == 0:
                    busy.advance(step, len(vals) / total)
                if not ray:
                    vals.append(T.NO_HIT), kinds.append(T.GAP), who.append(-1)
                    continue
                o, d = ray
                vec = V(*d)
                org = P(*o)
                own = None
                for hit in objs[i].calculateCollisionsWithRay(org, vec):
                    dist = org.distanceTo(hit)
                    if dist > 1e-5:
                        own = dist
                        break
                others = []
                p = (o[0] - GAP_BACK * d[0], o[1] - GAP_BACK * d[1], o[2] - GAP_BACK * d[2])
                for j in range(len(meshes)):
                    if j != i and T.ray_box(p, d, *boxes[j]):
                        kind, dist = other_body(j, o, d, vec)
                        if kind == T.OVERLAP:
                            kind, dist = T.settle_overlap([other_body(j, q, d, vec)
                                                           for q in T.retry_origins(m[0], m[2], len(vals))])
                        others.append((kind, dist, j))
                kind, dist, j = T.combine(own, others)
                vals.append(dist), kinds.append(kind), who.append(j)
            results[i] = (vals, kinds, who)
    finally:
        _drop_temp(objs)
    busy.drawing()
    _gap_cache[key] = (meshes, results)
    return _gap_cache[key]


def _gap_analyse(design, s, bodies, may_measure=True):
    """(html del resultado, capas, cuerpos analizados) midiendo el espacio delante de cada cara.
    Sin may_measure, si falta medir, devuelve (None, [], []) para esperar al botón."""
    if s['gap_limit'] <= 0:
        return tr('El espacio mínimo tiene que ser mayor que 0.'), [], bodies
    if s['th_paint'] == 'map' and s['gap_hi'] <= s['gap_lo']:
        return tr('El final de la escala tiene que ser mayor que el principio.'), [], bodies
    if not may_measure and _gap_key(bodies, s['th_res']) not in _gap_cache:
        return None, [], []
    t0 = time.time()
    lo, hi, limit = s['gap_lo'] / 10.0, s['gap_hi'] / 10.0, s['gap_limit'] / 10.0   # cm
    meshes, results = _gap_measure(design, bodies, s['th_res'])
    layers, rows, overlaps = [], [], set()
    thin = contact = overlap = 0.0
    tris = 0
    for i, (m, (vals, kinds, who)) in enumerate(zip(meshes, results)):
        c, n, idx, _, lift = m
        tc, tn, tcol, st = T.colorize_gaps(c, n, idx, vals, kinds, lo, hi, limit, s['th_paint'] == 'thin', GAP_MARGIN)
        tris += len(idx) // 3
        thin, contact, overlap = thin + st['thin'], contact + st['contact'], overlap + st['overlap']
        overlaps |= set(tuple(sorted((bodies[i].name, bodies[j].name))) for k, j in zip(kinds, who) if k == T.OVERLAP)
        if st['min'] is not None:
            j = who[st['tri']]
            where = bodies[i].name if j < 0 else ' ↔ '.join(sorted((bodies[i].name, bodies[j].name)))
            rows.append((st['min'], where, st['thin'], bodies[i].name))
        if tc:
            layers.append((A.offset(tc, tn, lift), tn, tcol))

    sq = '<font color="#%02x%02x%02x">■</font>'
    lines = [_th_legend(s, 'gap_'),
             '%s %s &nbsp; %s %s' % (sq % T.CONTACT_COLOR[:3], tr('en contacto'), sq % T.OVERLAP_COLOR[:3], tr('interferencia')),
             '']
    if rows:
        rows.sort()
        wmin, where = rows[0][:2]
        state = ('<font color="#d33">✖</font>' if wmin < limit - GAP_MARGIN or overlap
                 else '<font color="#3a3">✔</font>')
        lines.append(tr('%s Lo más estrecho: <b>%s mm</b> (%s)') % (state, _mm(wmin * 10), where))
        lines.append(tr('Por debajo de %s mm: <b>%.0f mm²</b>') % (_mm(s['gap_limit']), thin * 100))
        if len(rows) > 1:
            lines += ['&nbsp; • %s: %s mm, %.0f mm²' % (nm, _mm(w * 10), a * 100)
                      for w, _, a, nm in sorted(rows, key=lambda r: r[3])]
    elif not (contact or overlap):
        lines.append(tr('Ninguna cara tiene otra enfrente.'))
    if contact:
        lines.append('%s %s' % (sq % T.CONTACT_COLOR[:3], tr('Caras en contacto: %.0f mm²') % (contact * 100)))
    if overlap:
        pairs = ', '.join(' ↔ '.join(p) for p in sorted(overlaps))
        lines.append('%s %s' % (sq % T.OVERLAP_COLOR[:3], tr('Interferencia: <b>%.0f mm²</b> (%s)') % (overlap * 100, pairs)))
    lines.append('<font color="#888">%s</font>' % (tr('%d triángulos en %.2f s') % (tris, time.time() - t0)))
    _th_state['result'] = {'mode': 'gap', 'min': rows[0][0] * 10 if rows else None, 'where': rows[0][1] if rows else None,
                           'thin': thin * 100, 'contact': contact * 100, 'overlap': overlap * 100}
    return '<br>'.join(lines), layers, bodies


def _th_analyse(design, s, picked, may_measure=True):
    """(html del resultado, capas, cuerpos analizados). Sin may_measure, si falta medir algún cuerpo, devuelve
    (None, [], []) para esperar al botón."""
    if not design:
        return tr('Abre un diseño (espacio de trabajo DISEÑO).'), [], []
    if s['th_bodies'] == 'pick':
        bodies = picked
        if not bodies:
            return tr('Elige los cuerpos.'), [], []
    else:
        bodies = _visible_bodies(design.rootComponent)
    # las superficies no tienen espesor
    bodies = [b for b in bodies if adsk.fusion.MeshBody.cast(b) or getattr(b, 'isSolid', False)]
    if not bodies:
        return tr('No hay cuerpos sólidos que medir.'), [], []
    if s['th_mode'] == 'gap':
        return _gap_analyse(design, s, bodies, may_measure)
    if s['th_limit'] <= 0:
        return tr('El espesor mínimo tiene que ser mayor que 0.'), [], bodies
    if s['th_paint'] == 'map' and s['th_hi'] <= s['th_lo']:
        return tr('El final de la escala tiene que ser mayor que el principio.'), [], bodies

    pending = [b for b in bodies if (b.entityToken, s['th_res']) not in _th_meshes]
    if pending and not may_measure:
        return None, [], []

    t0 = time.time()
    lo, hi, limit = s['th_lo'] / 10.0, s['th_hi'] / 10.0, s['th_limit'] / 10.0   # cm
    layers, rows, open_bodies = [], [], []
    thin = total = 0.0
    tris = 0
    if pending:
        busy = _Busy(len(pending))
        for i, b in enumerate(pending):
            _th_mesh(b, s['th_res'], lambda f, i=i: busy.advance(i, f))
        busy.drawing()
    for b in bodies:
        c, n, idx, thick, closed, gap = _th_mesh(b, s['th_res'])
        if not closed:
            open_bodies.append(b.name)
        tc, tn, tcol, st = T.colorize(c, n, idx, thick, lo, hi, limit, s['th_paint'] == 'thin')
        tris += len(idx) // 3
        thin, total = thin + st['thin'], total + st['total']
        if st['min'] is not None:
            rows.append((st['min'], b.name, st['thin']))
        if tc:
            layers.append((A.offset(tc, tn, gap), tn, tcol))

    lines = [_th_legend(s), '']
    if rows:
        rows.sort()
        wmin, name, _ = rows[0]
        state = ('<font color="#d33">✖</font>' if wmin < limit else '<font color="#3a3">✔</font>')
        lines.append(tr('%s Lo más fino: <b>%s mm</b> (%s)') % (state, _mm(wmin * 10), name))
        lines.append(tr('Por debajo de %s mm: <b>%.0f mm²</b> (%.1f %% de la superficie)')
                     % (_mm(s['th_limit']), thin * 100, 100 * thin / total if total else 0))
        if len(rows) > 1:
            lines += ['&nbsp; • %s: %s mm, %.0f mm²' % (nm, _mm(w * 10), a * 100) for w, nm, a in rows]
    if open_bodies:
        lines.append('<font color="#c80">⚠ %s</font>' % (tr('Malla abierta, puede medir de más: %s')
                                                         % ', '.join(open_bodies)))
    lines.append('<font color="#888">%s</font>' % (tr('%d triángulos en %.2f s') % (tris, time.time() - t0)))
    _th_state['result'] = {'min': rows[0][0] * 10 if rows else None, 'thin': thin * 100, 'total': total * 100}
    return '<br>'.join(lines), layers, bodies


def _th_draw(inputs):
    """Como _draw, para el espesor."""
    _clear(TH_GROUP_ID)
    layers, bodies = [], []
    design = adsk.fusion.Design.cast(_app.activeProduct)
    try:
        s = _th_read(inputs)
        _save_settings(s)
        sel = inputs.itemById('th_body_sel')
        picked = [sel.selection(i).entity for i in range(sel.selectionCount)]
        html, layers, bodies = _th_analyse(design, s, picked, _th_state.get('run', False))
        _th_state.pop('run', None)
        if html is None:
            html = _prompt()
            _th_state.pop('last', None)   # no hay nada pintado que mantener al cerrar
        else:
            _th_state['last'] = {'design': design, 'settings': s, 'layers': layers, 'bodies': bodies}
    except Exception:
        html = '<b><font color="#d33">✖ %s</font></b><br>%s' % (
            tr('Error interno del complemento:'), traceback.format_exc().replace('\n', '<br>'))
    if _th_state.get('html') != html:
        _th_state['html'] = html
        inputs.itemById('th_info').formattedText = html
    try:
        if design:
            _paint(design, layers, TH_GROUP_ID)
            if _th_state.get('last') and _th_state['last']['settings']['th_xray']:
                # dentro de la vista previa: Fusion devuelve la opacidad de cada cuerpo al cambiar un campo y al cerrar
                for b in bodies:
                    b.opacity = XRAY_OPACITY
        _app.activeViewport.refresh()
    finally:
        busy = _th_state.pop('busy', None)
        if busy:
            busy.close()


def _th_drop_keep():
    _clear(TH_KEEP_ID, _th_keep.get('design'))
    _th_keep.clear()


def _th_update_visibility(inputs):
    inputs.itemById('th_body_sel').isVisible = _choice(inputs, 'th_bodies', BODIES) == 'pick'
    is_map = _choice(inputs, 'th_paint', PAINTS) == 'map'
    is_gap = _choice(inputs, 'th_mode', MODES) == 'gap'
    inputs.itemById('th_limit').isVisible = not is_gap
    inputs.itemById('th_lo').isVisible = is_map and not is_gap
    inputs.itemById('th_hi').isVisible = is_map and not is_gap
    inputs.itemById('gap_limit').isVisible = is_gap
    inputs.itemById('gap_lo').isVisible = is_map and is_gap
    inputs.itemById('gap_hi').isVisible = is_map and is_gap


class _ThCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            _th_state['cmd'] = cmd
            _th_drop_keep()
            _th_state.pop('html', None)
            _th_state.pop('run', None)
            cmd.isOKButtonVisible = False
            cmd.cancelButtonText = tr('Cerrar')
            # el tamaño inicial, para que Fusion lo tenga en cuenta al colocar el diálogo la primera vez: con
            # solo el mínimo, lo coloca con su ancho por defecto y luego crece fuera de la pantalla
            cmd.setDialogInitialSize(380, 620)
            cmd.setDialogMinimumSize(380, 300)
            inputs = cmd.commandInputs
            s = _load_settings()
            VS = adsk.core.ValueInput.createByString

            dd = inputs.addDropDownCommandInput('th_mode', tr('Medir'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in MODES:
                dd.listItems.add(tr(label), key == s['th_mode'])
            dd.tooltip = tr('Espesor: de cada pared hasta su otra cara. Espacio: de cada cara hasta lo que tiene '
                            'delante, sea del mismo cuerpo o de otro.')
            dd = inputs.addDropDownCommandInput('th_bodies', tr('Cuerpos'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in BODIES:
                dd.listItems.add(tr(label), key == s['th_bodies'])
            sel = inputs.addSelectionInput('th_body_sel', tr('Selección'), tr('Elige los cuerpos.'))
            for f in ('SolidBodies', 'MeshBodies'):
                sel.addSelectionFilter(f)
            sel.setSelectionLimits(0, 0)
            inputs.addValueInput('th_limit', tr('Espesor mínimo'), 'mm', VS('%s mm' % s['th_limit']))
            inputs.addValueInput('gap_limit', tr('Espacio mínimo'), 'mm', VS('%s mm' % s['gap_limit']))
            dd = inputs.addDropDownCommandInput('th_paint', tr('Pintar'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in PAINTS:
                dd.listItems.add(tr(label), key == s['th_paint'])
            inputs.addValueInput('th_lo', tr('Escala desde'), 'mm', VS('%s mm' % s['th_lo']))
            inputs.addValueInput('th_hi', tr('Escala hasta'), 'mm', VS('%s mm' % s['th_hi']))
            inputs.addValueInput('gap_lo', tr('Escala desde'), 'mm', VS('%s mm' % s['gap_lo']))
            inputs.addValueInput('gap_hi', tr('Escala hasta'), 'mm', VS('%s mm' % s['gap_hi']))
            dd = inputs.addDropDownCommandInput('th_res', tr('Resolución'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label, _ in RESOLUTIONS:
                dd.listItems.add(tr(label), key == s['th_res'])
            dd.tooltip = tr('Lado máximo de los triángulos con los que se mide. Más fina, más detalle y más lento.')
            xray = inputs.addBoolValueInput('th_xray', tr('Ver a través'), True, '', bool(s['th_xray']))
            xray.tooltip = tr('Pone los cuerpos medidos en transparencia mientras el diálogo está abierto, para ver '
                              'lo que queda por dentro. Al cerrar vuelven a su opacidad.')
            keep = inputs.addBoolValueInput('th_keep', tr('Mantener al cerrar'), True, '', bool(s['th_keep']))
            keep.tooltip = tr('La capa se queda al cerrar el diálogo, hasta que cambie alguno de los cuerpos o se '
                              'vuelva a abrir el diálogo. No se guarda en el archivo.')
            _add_run_button(inputs, 'th_run')
            inputs.addTextBoxCommandInput('th_info', tr('Resultado'), '', 13, True).isFullWidth = True
            _th_update_visibility(inputs)

            for ev, h in ((cmd.executePreview, _ThPreviewHandler()), (cmd.inputChanged, _ThChangedHandler()),
                          (cmd.destroy, _ThDestroyHandler())):
                ev.add(h)
                _handlers.append(h)
        except Exception:
            _ui.messageBox(tr('Espesor y espacios: error') + '\n' + traceback.format_exc())


class _ThPreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        _th_draw(args.command.commandInputs)


class _ThChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        if args.input.id == 'th_info':
            return
        if args.input.id == 'th_run':
            _th_state['run'] = True   # lo atiende la vista previa que Fusion lanza a continuación
            return
        inputs = args.firingEvent.sender.commandInputs
        _th_update_visibility(inputs)
        if args.input.id == 'th_bodies' and _choice(inputs, 'th_bodies', BODIES) == 'pick':
            inputs.itemById('th_body_sel').hasFocus = True


class _ThDestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            if _th_state.get('cmd') is not None and args.command != _th_state['cmd']:
                return   # se ha vuelto a pulsar el botón con el diálogo abierto: el nuevo ya está en marcha
            _clear(TH_GROUP_ID)
            _th_meshes.clear()
            _gap_cache.clear()
            _th_state.pop('cmd', None)
            _th_state.pop('html', None)
            last = _th_state.pop('last', None)
            if last and last['settings'].get('th_keep') and last['design'] and last['layers']:
                _th_keep.update(design=last['design'], layers=last['layers'], sig=_th_signature(last['bodies']),
                                bodies=last['bodies'], painted=False)
                _app.fireCustomEvent(TH_KEEP_EVENT)
            _app.activeViewport.refresh()
        except Exception:
            pass


class _ThKeepHandler(adsk.core.CustomEventHandler):
    """Pinta la capa mantenida al cerrar y la quita cuando cambian los cuerpos."""
    def notify(self, args):
        try:
            design = _th_keep.get('design')
            if not design or not design.isValid:
                _th_keep.clear()
                return
            if not _th_keep['painted']:
                _paint(design, _th_keep['layers'], TH_KEEP_ID)
                _th_keep['painted'] = True
            elif _th_signature(_th_keep['bodies']) != _th_keep['sig']:
                _th_drop_keep()
            _app.activeViewport.refresh()
        except Exception:
            pass


# ======================================================================== enviar al laminador

OPEN_IN = [('orca', 'OrcaSlicer'), ('bambu', 'Bambu Studio'), ('none', 'No abrir')]
FACE_TOL = 0.002    # cm: malla de las caras elegidas; solo sirve para reconocer sus triángulos en el STL
STROKE_TOL = 0.001  # cm: puntos de las aristas elegidas
# (campo, tipo, papel, color, texto de la leyenda)
SL_ROLES = [('sl_seam_on', 'seam', 'enforce', (0, 190, 230), 'costura forzada'),
            ('sl_seam_off', 'seam', 'block', (255, 150, 0), 'costura prohibida'),
            ('sl_sup_on', 'support', 'enforce', (60, 200, 60), 'soportes forzados'),
            ('sl_sup_off', 'support', 'block', (220, 30, 30), 'soportes bloqueados')]
SL_TIGHT_COLOR = (240, 220, 0)   # poca holgura: también costura prohibida, pero medida y no elegida
_sl_state = {}


def _sl_read(inputs):
    item = inputs.itemById('sl_body').selectedItem
    return {'sl_body': item.name if item else None, 'sl_bed': _choice(inputs, 'sl_bed', BEDS), 'sl_gap': inputs.itemById('sl_gap').value,
            'sl_gap_limit': round(inputs.itemById('sl_gap_limit').value * 10, 4),   # mm
            'sl_res': _choice(inputs, 'sl_res', RESOLUTIONS), 'sl_open': _choice(inputs, 'sl_open', OPEN_IN)}


def _picked(inputs, key):
    sel = inputs.itemById(key)
    return [sel.selection(i).entity for i in range(sel.selectionCount)]


def _sl_bodies(design):
    """[(nombre para la lista, cuerpo)] de los sólidos visibles. Con el componente si el nombre se repite."""
    bodies = [b for b in _visible_bodies(design.rootComponent) if getattr(b, 'isSolid', False)] if design else []
    names = [b.name for b in bodies]
    return [(b.name if names.count(b.name) == 1 or not b.assemblyContext
             else '%s (%s)' % (b.name, b.assemblyContext.name), b) for b in bodies]


def _sl_body(inputs):
    """El cuerpo elegido en la lista, o None. Es una lista y no un campo de selección porque Fusion resalta en azul
    el cuerpo seleccionado entero y taparía lo que se pinta encima."""
    item = inputs.itemById('sl_body').selectedItem
    bodies = _sl_state.get('bodies', [])
    if not item or item.index >= len(bodies):
        return None
    body = bodies[item.index][1]
    return body if body.isValid else None


def _same_body(entity, body):
    """Si la arista o la cara es del cuerpo, también dentro de una ocurrencia."""
    try:
        return entity.body.entityToken == body.entityToken
    except Exception:
        return False


def _to_root(body):
    """Matriz (Matrix3D.asArray) que lleva del componente del cuerpo al raíz, o None."""
    return body.assemblyContext.transform2.asArray() if body.assemblyContext else None


def _sl_face(face, body):
    """(cara del formato, (coords, normales, índices) en cm en el raíz) de una cara elegida."""
    native = face.nativeObject or face
    calc = native.meshManager.createMeshCalculator()
    calc.surfaceTolerance = FACE_TOL
    m = calc.calculate()
    coords, normals, idx = list(m.nodeCoordinatesAsDouble), list(m.normalVectorsAsDouble), list(m.nodeIndices)
    tf = _to_root(body)
    if tf:
        coords, normals = A.transform(coords, normals, tf)
    return S.face(coords, idx, native.area), (coords, normals, idx)


def _sl_edge(edge, body):
    """Puntos de una arista elegida, en cm en el raíz (planos, x y z seguidos)."""
    ev = (edge.nativeObject or edge).evaluator
    ok, t0, t1 = ev.getParameterExtents()
    ok2, pts = ev.getStrokes(t0, t1, STROKE_TOL)
    if not (ok and ok2):
        raise ValueError(tr('No se pudo recorrer una arista.'))
    flat = [v for p in pts for v in p.asArray()]
    tf = _to_root(body)
    return A.transform(flat, [], tf)[0] if tf else flat


def _soup(coords, normals, idx, rgb, lift):
    """Capa (coords, normales, colores) con tres vértices propios por triángulo, separada 'lift' de la cara."""
    tc, tn = [], []
    for k in idx:
        tc += coords[3 * k:3 * k + 3]
        tn += normals[3 * k:3 * k + 3]
    return A.offset(tc, tn, lift), tn, list(rgb + (255,)) * len(idx)


def _sl_bed(s, inputs, body):
    """Normal hacia fuera de la cara de la cama, o un texto de error."""
    if s['sl_bed'] != 'face':
        return S.bed_vector(s['sl_bed'])
    picked = _picked(inputs, 'sl_face')
    if not picked:
        return tr('Elige la cara plana que va sobre la cama.')
    face = adsk.fusion.BRepFace.cast(picked[0])
    native = face.nativeObject or face
    _, n = native.evaluator.getNormalAtPoint(native.pointOnFace)   # en un sólido, hacia fuera
    n = [n.x, n.y, n.z]
    tf = _to_root(body)
    if tf:
        n = A.transform([], n, tf)[1]
    return S.bed_vector('face', n)


def _gap_bodies(design, body):
    """El cuerpo que se envía, el primero, y los demás sólidos y mallas visibles, que pueden quitarle holgura."""
    others = [b for b in _visible_bodies(design.rootComponent) if b.entityToken != body.entityToken
              and (adsk.fusion.MeshBody.cast(b) or getattr(b, 'isSolid', False))]
    return [body] + others


def _count(n_edges, n_faces):
    parts = []
    if n_edges:
        parts.append(tr('%d arista') % n_edges if n_edges == 1 else tr('%d aristas') % n_edges)
    if n_faces:
        parts.append(tr('%d cara') % n_faces if n_faces == 1 else tr('%d caras') % n_faces)
    return ', '.join(parts)


def _sl_collect(design, s, inputs, may_measure):
    """(archivo de pieza o None, html, capas, aristas [(coords, color)]). Sin may_measure, la poca holgura solo
    entra si ya está medida: medir puede tardar y no se hace al abrir ni con cada cambio."""
    body = _sl_body(inputs)
    if not body:
        return None, tr('No hay ningún cuerpo sólido visible.'), [], []
    bed = _sl_bed(s, inputs, body)
    if isinstance(bed, str):
        return None, bed, [], []
    layers, lines, roles, rows = [], [], {}, []
    sq = '<font color="#%02x%02x%02x">■</font> %s'
    for key, kind, role, rgb, label in SL_ROLES:
        edges, faces = [], []
        for ent in _picked(inputs, key):
            if not _same_body(ent, body):
                return None, tr('Lo elegido tiene que ser del cuerpo que se envía.'), [], []
            face, edge = adsk.fusion.BRepFace.cast(ent), adsk.fusion.BRepEdge.cast(ent)
            if face:
                data, (c, n, idx) = _sl_face(face, body)
                faces.append(data)
                layers.append(_soup(c, n, idx, rgb, A.lift(FACE_TOL, _display_tolerance(body.nativeObject or body))))
                # el resaltado de Fusion tapa la cara elegida, pero no las líneas: el contorno lleva el color
                lines += [(_sl_edge(e, body), rgb) for e in face.edges]
            elif edge:
                pts = _sl_edge(edge, body)
                edges.append(S.edge([pts[i:i + 3] for i in range(0, len(pts), 3)]))
                lines.append((pts, rgb))
        roles['%s_%s' % (kind, role)] = [edges, faces, []]
        if edges or faces:
            rows.append(sq % (rgb + ('%s: %s' % (tr(label), _count(len(edges), len(faces))),)))

    tight_html = ''
    if s['sl_gap']:
        if s['sl_gap_limit'] <= 0:
            return None, tr('El espacio mínimo tiene que ser mayor que 0.'), layers, lines
        bodies = _gap_bodies(design, body)
        if not may_measure and _gap_key(bodies, s['sl_res'], (0,)) not in _gap_cache:
            tight_html = tr('La holgura se mide al pulsar <b>Medir holgura</b> o al enviar.')
        else:
            meshes, results = _gap_measure(design, bodies, s['sl_res'], (0,))
            (c, n, idx, _, lift), (vals, kinds, _) = meshes[0], results[0]
            tris = S.tight_triangles(vals, kinds, s['sl_gap_limit'] / 10.0, GAP_MARGIN)
            zone = S.patch(c, idx, tris)
            if zone:
                roles['seam_block'][2].append(zone)
                layers.append(_soup(c, n, [idx[3 * t + k] for t in tris for k in range(3)], SL_TIGHT_COLOR, lift))
                area = sum(T._tri(c, idx, 3 * t)[2] for t in tris) * 100
                tight_html = sq % (SL_TIGHT_COLOR + (tr('poca holgura (menos de %s mm): %.0f mm², costura prohibida')
                                                     % (_mm(s['sl_gap_limit']), area),))
            else:
                tight_html = tr('Ninguna cara tiene menos de %s mm de holgura.') % _mm(s['sl_gap_limit'])

    job = S.job(body.name, bed, **{k: S.selection(*v) for k, v in roles.items()})
    html = [tr('Cuerpo: <b>%s</b>') % body.name, tr('Cama: %s') % tr(dict(BEDS)[s['sl_bed']]), '']
    html += rows or [tr('Nada elegido a mano.')]
    if tight_html:
        html.append(tight_html)
    exe = S.find_exe(_load_settings()['slicer_paint'])
    html.append('')
    if exe:
        html.append('<font color="#888">slicer-paint: %s</font>' % exe)
    else:
        html.append('<font color="#c80">⚠ %s</font>' % tr('No encuentro slicer-paint: al enviar te preguntaré '
                                                           'dónde está.'))
    return job, '<br>'.join(html), layers, lines


def _sl_paint(design, layers, lines):
    _paint(design, layers, SL_GROUP_ID)
    if not lines:
        return
    groups = [g for g in design.rootComponent.customGraphicsGroups if g.id == SL_GROUP_ID]
    grp = groups[0] if groups else design.rootComponent.customGraphicsGroups.add()
    grp.id = SL_GROUP_ID
    for pts, rgb in lines:
        ln = grp.addLines(adsk.fusion.CustomGraphicsCoordinates.create(pts), [], True)
        ln.weight = 4
        ln.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(*(rgb + (255,))))
        ln.depthPriority = 2


def _close_busy():
    busy = _th_state.pop('busy', None)
    if busy:
        busy.close()


def _sl_draw(inputs):
    """Como _draw: resultado y capa con lo que va a cada papel."""
    _clear(SL_GROUP_ID)
    layers, lines = [], []
    design = adsk.fusion.Design.cast(_app.activeProduct)
    try:
        s = _sl_read(inputs)
        _save_settings(s)
        if not design:
            html = tr('Abre un diseño (espacio de trabajo DISEÑO).')
        else:
            _, html, layers, lines = _sl_collect(design, s, inputs, _sl_state.pop('run', False))
    except Exception:
        html = '<b><font color="#d33">✖ %s</font></b><br>%s' % (
            tr('Error interno del complemento:'), traceback.format_exc().replace('\n', '<br>'))
    if _sl_state.get('html') != html:
        _sl_state['html'] = html
        inputs.itemById('sl_info').formattedText = html
    try:
        if design:
            _sl_paint(design, layers, lines)
        _app.activeViewport.refresh()
    finally:
        _close_busy()


def _sl_update_visibility(inputs):
    inputs.itemById('sl_face').isVisible = _choice(inputs, 'sl_bed', BEDS) == 'face'
    gap = inputs.itemById('sl_gap').value
    for k in ('sl_gap_limit', 'sl_res', 'sl_measure'):
        inputs.itemById(k).isVisible = gap


def _sl_target(s, body_name):
    """Ruta del 3MF que elige el usuario, o None si cancela."""
    dlg = _ui.createFileDialog()
    dlg.title = tr('Enviar al laminador')
    dlg.filter = '3MF (*.3mf)'
    if s.get('sl_dir') and os.path.isdir(s['sl_dir']):
        dlg.initialDirectory = s['sl_dir']
    dlg.initialFilename = ''.join(ch for ch in body_name if ch not in '\\/:*?"<>|') or 'pieza'
    if dlg.showSave() != adsk.core.DialogResults.DialogOK:
        return None
    path = dlg.filename
    return path if path.lower().endswith('.3mf') else path + '.3mf'


def _sl_exe():
    """Ruta de slicer-paint. Si no la encuentra, la pregunta y la recuerda en settings.json. None si el usuario
    cancela o elige otro programa."""
    exe = S.find_exe(_load_settings()['slicer_paint'])
    if exe:
        return exe
    dlg = _ui.createFileDialog()
    dlg.title = tr('¿Dónde está slicer-paint? Si cancelas, solo se guardan el STL y el JSON')
    everything = tr('Todos los archivos')
    dlg.filter = ('slicer-paint (slicer-paint.exe);;%s (*.*)' % everything if os.name == 'nt'
                  else '%s (*)' % everything)
    if dlg.showOpen() != adsk.core.DialogResults.DialogOK:
        return None
    if not S.looks_like_exe(dlg.filename):
        _ui.messageBox(tr('%s no es slicer-paint.') % dlg.filename, tr('Enviar al laminador'))
        return None
    _save_settings({'slicer_paint': dlg.filename})
    return dlg.filename


def _sl_send(design, s, inputs):
    """Exporta el STL, escribe el archivo de pieza y lanza slicer-paint. Devuelve un mensaje para el usuario, ''
    si no hay nada que decir todavía (slicer-paint avisa al acabar) o None si se cancela."""
    job, html, _, _ = _sl_collect(design, s, inputs, True)
    _close_busy()
    if job is None:
        return html.replace('<br>', '\n')
    body = _sl_body(inputs)
    target = _sl_target(_load_settings(), body.name)
    if not target:
        return None
    _save_settings({'sl_dir': os.path.dirname(target)})
    exe = _sl_exe()   # antes de exportar, para que los dos diálogos vayan seguidos
    stl, job_path, out = S.paths(target)
    em = design.exportManager
    opts = em.createSTLExportOptions(body, stl)
    opts.isBinaryFormat = True
    opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
    opts.sendToPrintUtility = False
    if not em.execute(opts) or not os.path.isfile(stl):
        return tr('No se pudo exportar el STL: %s') % stl
    tf = _to_root(body)
    if tf:   # Fusion lo exporta en las coordenadas de su componente
        S.move_stl(stl, tf)
    bb = body.boundingBox
    body_box = (bb.minPoint.asArray(), bb.maxPoint.asArray())
    stl_box = S.stl_bounds(stl)
    if not S.bounds_match(stl_box, body_box):
        return tr('El STL no está en las coordenadas del diseño: las zonas no caerían sobre la pieza.\n'
                  'STL (mm): %s\nCuerpo (cm): %s') % (stl_box, body_box)
    with open(job_path, 'w', encoding='utf-8') as f:
        json.dump(job, f, ensure_ascii=False)
    if not exe:
        return tr('Guardados %s y %s.\n\nSin slicer-paint. Para generar el 3MF, ejecútalo a mano:\n%s') % (
            stl, job_path, ' '.join('"%s"' % a for a in S.command('slicer-paint', stl, job_path, out)))
    open_in = None if s['sl_open'] == 'none' else s['sl_open']
    _sl_run(S.command(exe, stl, job_path, out, open_in), out, os.path.splitext(target)[0] + '.log', open_in)
    return ''


def _sl_run(argv, out, log, open_in):
    """Lanza slicer-paint sin esperar y avisa al acabar con SL_DONE_EVENT: Fusion sigue libre mientras."""
    import subprocess
    import threading

    def wait():
        try:
            with open(log, 'w', encoding='utf-8', errors='replace') as f:
                code = subprocess.call(argv, stdout=f, stderr=subprocess.STDOUT,
                                       env=dict(os.environ, PYTHONIOENCODING='utf-8'),   # el log se lee en UTF-8
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception as e:
            code = -1
            with open(log, 'a', encoding='utf-8') as f:
                f.write(str(e))
        _app.fireCustomEvent(SL_DONE_EVENT, json.dumps({'code': code, 'out': out, 'log': log, 'open': open_in}))

    threading.Thread(target=wait, daemon=True).start()


class _SlDoneHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        try:
            r = json.loads(args.additionalInfo)
            _sl_state['done'] = r
            if r['code'] == -1:   # no se pudo lanzar: se vuelve a preguntar la próxima vez
                _save_settings({'slicer_paint': ''})
            if r['code'] != 0:
                try:
                    with open(r['log'], encoding='utf-8', errors='replace') as f:
                        tail = f.read()[-1500:]
                except OSError:
                    tail = ''
                _ui.messageBox(tr('slicer-paint ha fallado (código %d):') % r['code'] + '\n\n' + tail,
                               tr('Enviar al laminador'))
            elif not r['open']:
                _ui.messageBox(tr('Guardado: %s') % r['out'], tr('Enviar al laminador'))
        except Exception:
            pass


class _SlCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            _sl_state['cmd'] = cmd
            _sl_state.pop('html', None)
            _sl_state.pop('run', None)
            cmd.okButtonText = tr('Enviar')
            cmd.cancelButtonText = tr('Cerrar')
            cmd.setDialogInitialSize(380, 640)
            cmd.setDialogMinimumSize(380, 300)
            inputs = cmd.commandInputs
            s = _load_settings()
            VS = adsk.core.ValueInput.createByString

            dd = inputs.addDropDownCommandInput('sl_body', tr('Cuerpo'), adsk.core.DropDownStyles.TextListDropDownStyle)
            dd.tooltip = tr('El cuerpo que vas a imprimir. Los demás cuerpos visibles solo cuentan al medir la holgura.')
            bodies = _sl_bodies(adsk.fusion.Design.cast(_app.activeProduct))
            _sl_state['bodies'] = bodies
            names = [n for n, _ in bodies]
            last = s.get('sl_body') if s.get('sl_body') in names else (names[0] if names else None)
            for name in names:
                dd.listItems.add(name, name == last)
            dd = inputs.addDropDownCommandInput('sl_bed', tr('Cama'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in BEDS:
                dd.listItems.add(tr(label), key == s['sl_bed'])
            sel = inputs.addSelectionInput('sl_face', tr('Cara sobre la cama'),
                                           tr('Elige la cara plana que va sobre la cama.'))
            sel.addSelectionFilter('PlanarFaces')
            sel.setSelectionLimits(0, 1)

            tips = {'sl_seam_on': tr('Aristas o caras donde poner la costura. Una arista solo vale si sube respecto '
                                     'a las capas.'),
                    'sl_seam_off': tr('Caras o aristas donde no puede ir la costura.'),
                    'sl_sup_on': tr('Caras donde forzar soportes. Solo cuenta lo que mire hacia abajo una vez '
                                    'orientada la pieza.'),
                    'sl_sup_off': tr('Caras donde no puede haber soportes.')}
            labels = {'sl_seam_on': tr('Forzar en'), 'sl_seam_off': tr('Prohibir en'),
                      'sl_sup_on': tr('Forzar en'), 'sl_sup_off': tr('Bloquear en')}
            for title, keys in ((tr('Costura'), ('sl_seam_on', 'sl_seam_off')),
                                (tr('Soportes'), ('sl_sup_on', 'sl_sup_off'))):
                grp = inputs.addGroupCommandInput('grp_' + keys[0], title)
                grp.isExpanded = True
                gi = grp.children
                for key in keys:
                    sel = gi.addSelectionInput(key, labels[key], tips[key])
                    sel.addSelectionFilter('Faces')
                    sel.addSelectionFilter('Edges')
                    sel.setSelectionLimits(0, 0)
                    sel.tooltip = tips[key]
                if keys[0] != 'sl_seam_on':
                    continue
                gap = gi.addBoolValueInput('sl_gap', tr('Prohibir donde hay poca holgura'), True, '', bool(s['sl_gap']))
                gap.tooltip = tr('Mide el espacio delante de cada cara, como Espesor y espacios, y prohíbe la costura '
                                 'donde no llega al mínimo, toca otra pieza o se mete en ella: la costura abulta.')
                gi.addValueInput('sl_gap_limit', tr('Espacio mínimo'), 'mm', VS('%s mm' % s['sl_gap_limit']))
                dd = gi.addDropDownCommandInput('sl_res', tr('Resolución'), adsk.core.DropDownStyles.TextListDropDownStyle)
                for key, label, _ in RESOLUTIONS:
                    dd.listItems.add(tr(label), key == s['sl_res'])
                btn = gi.addBoolValueInput('sl_measure', '', False, '', False)
                btn.text = tr('Medir holgura')
                btn.isFullWidth = True
                btn.tooltip = tr('Mide ahora para ver en amarillo dónde se prohibirá la costura. Si no, se mide al '
                                 'enviar.')
            dd = inputs.addDropDownCommandInput('sl_open', tr('Abrir en'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in OPEN_IN:
                dd.listItems.add(tr(label), key == s['sl_open'])
            inputs.addTextBoxCommandInput('sl_info', tr('Resultado'), '', 9, True).isFullWidth = True
            _sl_update_visibility(inputs)

            for ev, h in ((cmd.executePreview, _SlPreviewHandler()), (cmd.inputChanged, _SlChangedHandler()),
                          (cmd.execute, _SlExecuteHandler()), (cmd.preSelect, _SlPreSelectHandler()),
                          (cmd.destroy, _SlDestroyHandler())):
                ev.add(h)
                _handlers.append(h)
        except Exception:
            _ui.messageBox(tr('Enviar al laminador: error') + '\n' + traceback.format_exc())


class _SlPreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        _sl_draw(args.command.commandInputs)


class _SlChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        if args.input.id == 'sl_info':
            return
        if args.input.id == 'sl_measure':
            _sl_state['run'] = True   # lo atiende la vista previa que Fusion lanza a continuación
            return
        inputs = args.firingEvent.sender.commandInputs
        _sl_update_visibility(inputs)
        if args.input.id == 'sl_bed' and _choice(inputs, 'sl_bed', BEDS) == 'face':
            inputs.itemById('sl_face').hasFocus = True


class _SlPreSelectHandler(adsk.core.SelectionEventHandler):
    """Fuera del campo Cuerpo, solo se puede elegir lo del cuerpo que se envía."""
    def notify(self, args):
        try:
            body = _sl_body(args.firingEvent.sender.commandInputs)
            if body and not _same_body(args.selection.entity, body):
                args.isSelectable = False
        except Exception:
            pass


class _SlExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            design = adsk.fusion.Design.cast(_app.activeProduct)
            inputs = args.command.commandInputs
            msg = _sl_send(design, _sl_read(inputs), inputs)
            _sl_state['sent'] = msg
            if msg:
                _ui.messageBox(msg, tr('Enviar al laminador'))
        except Exception:
            _ui.messageBox(tr('Enviar al laminador: error') + '\n' + traceback.format_exc())
        finally:
            _close_busy()


class _SlDestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            if _sl_state.get('cmd') is not None and args.command != _sl_state['cmd']:
                return   # se ha vuelto a pulsar el botón con el diálogo abierto: el nuevo ya está en marcha
            _clear(SL_GROUP_ID)
            _gap_cache.clear()
            _sl_state.pop('cmd', None)
            _sl_state.pop('html', None)
            _app.activeViewport.refresh()
        except Exception:
            pass


def _language():
    """'es' si Fusion está en castellano; si no, 'en'."""
    try:
        spanish = _app.preferences.generalPreferences.userLanguage == adsk.core.UserLanguages.SpanishLanguage
    except Exception:
        spanish = False
    return 'es' if spanish else 'en'


def _panel(pid):
    ws = _ui.workspaces.itemById(WORKSPACE_ID)
    return ws.toolbarPanels.itemById(pid) if ws else None


def run(context):
    try:
        set_language(_language())
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
        cmd_def = _ui.commandDefinitions.addButtonDefinition(
            CMD_ID, tr('Voladizos FDM'),
            tr('Pinta como un laminador lo que necesitará soporte: en rojo lo que mira hacia abajo con menos del '
               'ángulo límite desde la horizontal, en azul los puentes y en verde lo que apoya en la cama. '
               'No modifica el diseño.'),
            os.path.join(HERE, 'resources'))
        h = _CreatedHandler()
        cmd_def.commandCreated.add(h)
        _handlers.append(h)
        _app.unregisterCustomEvent(KEEP_EVENT)   # por si quedó de una carga anterior
        h = _KeepHandler()
        _app.registerCustomEvent(KEEP_EVENT).add(h)
        _handlers.append(h)
        h = _TerminatedHandler()
        _ui.commandTerminated.add(h)
        _handlers.append(h)
        th_def = _ui.commandDefinitions.itemById(TH_CMD_ID)
        if th_def:
            th_def.deleteMe()
        th_def = _ui.commandDefinitions.addButtonDefinition(
            TH_CMD_ID, tr('Espesor y espacios'),
            tr('Mapa de color del espesor de las paredes o del espacio entre superficies, de rojo (estrecho) a '
               'azul (ancho), o solo lo que no llega al mínimo. No modifica el diseño.'),
            os.path.join(HERE, 'resources', 'thickness'))
        h = _ThCreatedHandler()
        th_def.commandCreated.add(h)
        _handlers.append(h)
        _app.unregisterCustomEvent(TH_KEEP_EVENT)
        h = _ThKeepHandler()
        _app.registerCustomEvent(TH_KEEP_EVENT).add(h)
        _handlers.append(h)
        sl_def = _ui.commandDefinitions.itemById(SL_CMD_ID)
        if sl_def:
            sl_def.deleteMe()
        sl_def = _ui.commandDefinitions.addButtonDefinition(
            SL_CMD_ID, tr('Enviar al laminador'),
            tr('Exporta un cuerpo con su cama y con dónde forzar o prohibir la costura y los soportes, también donde '
               'hay poca holgura, y lo abre en el laminador con slicer-paint.'),
            os.path.join(HERE, 'resources', 'slicer'))
        h = _SlCreatedHandler()
        sl_def.commandCreated.add(h)
        _handlers.append(h)
        _app.unregisterCustomEvent(SL_DONE_EVENT)
        h = _SlDoneHandler()
        _app.registerCustomEvent(SL_DONE_EVENT).add(h)
        _handlers.append(h)
        for pid in PANEL_IDS:
            panel = _panel(pid)
            for cid, cdef in ((CMD_ID, cmd_def), (TH_CMD_ID, th_def), (SL_CMD_ID, sl_def)):
                if panel and not panel.controls.itemById(cid):
                    panel.controls.addCommand(cdef)
    except Exception:
        _ui.messageBox(tr('Voladizos FDM: error al arrancar') + '\n' + traceback.format_exc())


def stop(context):
    try:
        _clear()
        _drop_keep()
        _clear(TH_GROUP_ID)
        _th_drop_keep()
        for h in _handlers:
            if isinstance(h, _TerminatedHandler):
                _ui.commandTerminated.remove(h)
        _app.unregisterCustomEvent(KEEP_EVENT)
        _app.unregisterCustomEvent(TH_KEEP_EVENT)
        _clear(SL_GROUP_ID)
        _app.unregisterCustomEvent(SL_DONE_EVENT)
        for pid in PANEL_IDS:
            panel = _panel(pid)
            for cid in (CMD_ID, TH_CMD_ID, SL_CMD_ID):
                ctrl = panel.controls.itemById(cid) if panel else None
                if ctrl:
                    ctrl.deleteMe()
        for cid in (CMD_ID, TH_CMD_ID, SL_CMD_ID):
            cmd_def = _ui.commandDefinitions.itemById(cid)
            if cmd_def:
                cmd_def.deleteMe()
        _handlers.clear()
    except Exception:
        _ui.messageBox(tr('Voladizos FDM: error al parar') + '\n' + traceback.format_exc())
