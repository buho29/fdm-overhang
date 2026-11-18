# Comando "Espesor y espacios": mapa de color del espesor de las paredes o del espacio entre superficies (rojo lo
# estrecho -> azul lo ancho), o solo lo que no llega al mínimo. Mide con rayos contra cuerpos de malla temporales.
import time
import traceback

import adsk.core
import adsk.fusion

from .. import analysis as A
from .. import thickness as T
from ..i18n import tr
from .common import (BODIES, BUSY_DELAY, BUSY_EVERY, GAP_BACK, GAP_MARGIN, GAP_SURFACE_TOL, LAYERS, MODES, PAINTS,
                     RESOLUTIONS, TH_GROUP_ID, TH_KEEP_EVENT, TH_KEEP_ID, TH_SURFACE_TOL, XRAY, _add_run_button, _app,
                     _choice, _clear, _display_tolerance, _foreign, _handlers, _load_settings, _mm, _paint, _prompt,
                     _save_settings, _ui, _visible_bodies)


_th_state = {}  # comando abierto y último resultado (útil para depurar)
_th_meshes = {}
_gap_cache = {}  # (cuerpos, resolución) -> medida de todos juntos, porque cada uno depende de los demás
_th_keep = {}   # 'design', 'layers', 'sig': la capa de espesor que queda al cerrar (no se puede recalcular fuera)


def _th_read(inputs):
    return {'th_bodies': _choice(inputs, 'th_bodies', BODIES), 'th_res': _choice(inputs, 'th_res', RESOLUTIONS),
            'th_paint': _choice(inputs, 'th_paint', PAINTS),
            'th_limit': round(inputs.itemById('th_limit').value * 10, 4),   # mm
            'th_lo': round(inputs.itemById('th_lo').value * 10, 4), 'th_hi': round(inputs.itemById('th_hi').value * 10, 4),
            'th_keep': inputs.itemById('th_keep').value, 'th_mode': _choice(inputs, 'th_mode', MODES),
            'th_xray': _choice(inputs, 'th_xray', XRAY), 'th_layer': _choice(inputs, 'th_layer', LAYERS),
            'gap_limit': round(inputs.itemById('gap_limit').value * 10, 4),
            'gap_lo': round(inputs.itemById('gap_lo').value * 10, 4),
            'gap_hi': round(inputs.itemById('gap_hi').value * 10, 4),
            'gap_others': inputs.itemById('gap_others').value}


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
            _th_state.setdefault('busy_errors', []).append(str(e))
        _th_state['busy'] = self

    def drawing(self):
        # sin tocar la barra: si llega al máximo, la ventana se cierra sola
        if self.dlg:
            try:
                self.dlg.message = tr('Dibujando…')
            except RuntimeError as e:
                _th_state.setdefault('busy_errors', []).append(str(e))
                self.dlg = None

    def advance(self, i, f):
        if self.dlg:
            try:
                self.dlg.progressValue = int(1000 * (i + f) / self.steps)
            except RuntimeError as e:
                _th_state.setdefault('busy_errors', []).append(str(e))
                self.dlg = None

    def close(self):
        if self.dlg:
            try:
                self.dlg.hide()
            except RuntimeError as e:
                _th_state.setdefault('busy_errors', []).append(str(e))


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
    y su resultado es None. El de cada cuerpo es {'all': (espacios, tipos, cuerpo de enfrente), 'others': lo
    mismo sin contar su propio cuerpo}, para la casilla Solo entre cuerpos."""
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
            other_vals, other_kinds, other_who = [], [], []
            total = len(m[2]) // 3
            for ray in T.rays(m[0], m[2], outward=True):
                if len(vals) % BUSY_EVERY == 0:
                    busy.advance(step, len(vals) / total)
                if not ray:
                    vals.append(T.NO_HIT), kinds.append(T.GAP), who.append(-1)
                    other_vals.append(T.NO_HIT), other_kinds.append(T.GAP), other_who.append(-1)
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
                kind, dist, j = T.combine(None, others)
                other_vals.append(dist), other_kinds.append(kind), other_who.append(j)
            results[i] = {'all': (vals, kinds, who), 'others': (other_vals, other_kinds, other_who)}
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
    for i, (m, r) in enumerate(zip(meshes, results)):
        vals, kinds, who = r['others' if s['gap_others'] else 'all']
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
            last = _th_state.get('last')
            opacity = dict((k, o) for k, _, o in XRAY)[last['settings']['th_xray']] if last else None
            _paint(design, layers, TH_GROUP_ID, solid=opacity is not None and last['settings']['th_layer'] == 'inplace')
            if opacity is not None:
                # dentro de la vista previa: Fusion devuelve la opacidad de cada cuerpo al cambiar un campo y al cerrar.
                # Menos en los de un componente referenciado: la opacidad es del cuerpo en su archivo, que Fusion no
                # deshace (medido: se quedaban transparentes y el otro archivo, modificado). Esos no se tocan.
                for b in bodies:
                    if not _foreign(b):
                        b.opacity = opacity
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
    inputs.itemById('gap_others').isVisible = is_gap
    inputs.itemById('gap_lo').isVisible = is_map and is_gap
    inputs.itemById('gap_hi').isVisible = is_map and is_gap
    inputs.itemById('th_layer').isVisible = _choice(inputs, 'th_xray', XRAY) != 'off'


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
                            'delante, de otro cuerpo o, sin Solo entre cuerpos, también del mismo.')
            dd = inputs.addDropDownCommandInput('th_bodies', tr('Cuerpos'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in BODIES:
                dd.listItems.add(tr(label), key == s['th_bodies'])
            sel = inputs.addSelectionInput('th_body_sel', tr('Selección'), tr('Elige los cuerpos.'))
            for f in ('SolidBodies', 'MeshBodies'):
                sel.addSelectionFilter(f)
            sel.setSelectionLimits(0, 0)
            inputs.addValueInput('th_limit', tr('Espesor mínimo'), 'mm', VS('%s mm' % s['th_limit']))
            inputs.addValueInput('gap_limit', tr('Espacio mínimo'), 'mm', VS('%s mm' % s['gap_limit']))
            others = inputs.addBoolValueInput('gap_others', tr('Solo entre cuerpos'), True, '', bool(s['gap_others']))
            others.tooltip = tr('Solo mide las holguras con otros cuerpos. Desmarcada, también las ranuras, los '
                                'agujeros y los grabados estrechos de cada cuerpo.')
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
            dd = inputs.addDropDownCommandInput('th_xray', tr('Ver a través'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label, _ in XRAY:
                dd.listItems.add(tr(label), key == s['th_xray'])
            dd.tooltip = tr('Pone los cuerpos medidos en transparencia mientras el diálogo está abierto, para ver '
                            'lo que queda por dentro. Al cerrar vuelven a su opacidad.')
            dd = inputs.addDropDownCommandInput('th_layer', tr('Capa'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in LAYERS:
                dd.listItems.add(tr(label), key == s['th_layer'])
            dd.tooltip = tr('Por encima: la capa se ve con su color vivo a través de los cuerpos, pero Fusion la '
                            'pinta desordenada con ellos y donde se mira a través de un cuerpo puede salir a trozos. '
                            'En su sitio: se ve entera, tras los cuerpos transparentes, y por eso más pálida.')
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
