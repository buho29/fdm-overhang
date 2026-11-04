# Add-in de Fusion 360 con dos comandos en INSPECCIONAR:
# - "Voladizos FDM": pinta encima del modelo, como la vista de soportes de un laminador, lo que mira hacia abajo
#   con menos del ángulo límite desde la horizontal (rojo -> naranja) y lo que apoya en la cama (verde).
# - "Espesor de pared": mapa de color del espesor (rojo fino -> azul grueso) o solo lo que no llega al mínimo.
# Son gráficos personalizados: no tocan el diseño ni la línea de tiempo y se borran al cerrar el diálogo.
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
for _m in (overhang.i18n, overhang.analysis, overhang.thickness):   # recargar al reiniciar el add-in
    importlib.reload(_m)
from overhang import analysis as A  # noqa: E402
from overhang import thickness as T  # noqa: E402
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
SETTINGS = os.path.join(HERE, 'settings.json')
TOL_CM = 0.001   # lo que está a menos de 0.01 mm de la cama apoya en ella

BODIES = [('visible', 'Todos los visibles'), ('pick', 'Elegidos')]
BEDS = [('z', 'Plano XY (Z arriba)'), ('y', 'Plano XZ (Y arriba)'), ('face', 'Cara plana elegida')]
RESOLUTIONS = [('coarse', 'Rápida (2 mm)', 0.2), ('normal', 'Normal (1 mm)', 0.1), ('fine', 'Fina (0,5 mm)', 0.05)]
PAINTS = [('map', 'Mapa de color'), ('thin', 'Solo lo que no llega al mínimo')]
TH_SURFACE_TOL = 0.002   # cm: desviación de la malla del espesor respecto a la superficie
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
         'quality': 'normal', 'keep': False,
         'th_bodies': 'visible', 'th_res': 'normal', 'th_paint': 'map', 'th_limit': 0.8, 'th_lo': 0.0,
         'th_hi': 4.0, 'th_keep': False}
    try:
        with open(SETTINGS, encoding='utf-8') as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    # las selecciones no se guardan: se vuelve a lo que no necesita elegir nada
    for k in ('bodies', 'th_bodies'):
        if s[k] == 'pick':
            s[k] = 'visible'
    if s['bed'] == 'face':
        s['bed'] = _default_bed()
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


def _choice(inputs, key, options):
    item = inputs.itemById(key).selectedItem
    return options[item.index][0] if item else options[0][0]


def _read(inputs):
    return {'bodies': _choice(inputs, 'bodies', BODIES), 'bed': _choice(inputs, 'bed', BEDS),
            'own_bed': inputs.itemById('own_bed').value, 'angle': inputs.itemById('angle').valueOne,
            'gradient': inputs.itemById('gradient').value, 'quality': _choice(inputs, 'quality', QUALITIES),
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
    """(coords, normales, índices, separación) del cuerpo en coordenadas del raíz (cm), guardada mientras dure
    el diálogo. La separación es lo que hay que apartar la capa para que se vea entera (ver A.lift)."""
    key = (body.entityToken, quality)
    if key not in _meshes:
        native = body.nativeObject or body
        mesh_body = adsk.fusion.MeshBody.cast(native)
        if mesh_body:
            m = mesh_body.displayMesh
            gap = A.lift(0.0, 0.0)   # se pinta la misma malla que se analiza
        else:
            calc = native.meshManager.createMeshCalculator()
            calc.setQuality(dict((k, q) for k, _, q in QUALITIES)[quality])
            m = calc.calculate()
            gap = A.lift(calc.surfaceTolerance, _display_tolerance(native))
        coords, normals = list(m.nodeCoordinatesAsDouble), list(m.normalVectorsAsDouble)
        if body.assemblyContext:
            coords, normals = A.transform(coords, normals, body.assemblyContext.transform2.asArray())
        _meshes[key] = (coords, normals, list(m.nodeIndices), gap)
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


def _legend(angle):
    sq = '<font color="#%02x%02x%02x">■</font> %s'
    return '%s &nbsp; %s' % (sq % (A.RED[:3] + (tr('voladizo (menos de %d° desde la horizontal)') % angle,)),
                             sq % (A.BED_COLOR[:3] + (tr('apoyo en la cama'),)))


def _draw(inputs):
    """Escribe el resultado y pinta la capa. Se llama desde executePreview: Fusion deshace la capa de la
    vista previa anterior al cambiar cualquier campo, y la de la última al cerrar el diálogo.
    El texto va antes que la capa porque cambiar un campo también deshace lo pintado; solo se cambia si es
    distinto, para no lanzar otra vista previa."""
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
        _state['last'] = {'design': design, 'settings': s, 'bodies': bodies, 'face': face}
        html, layers = _analyse(design, s, bodies, face)
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


def _analyse(design, s, picked, face):
    """(html del resultado, [(coords, normales, colores) de cada cuerpo con algo que pintar]).
    s son los ajustes del diálogo (_read); picked, los cuerpos elegidos; face, la cara de la cama o None."""
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

    t0 = time.time()
    meshes = [(b, _mesh(b, s['quality'])) for b in bodies]
    lows = [A.lowest(c, up) for _, (c, _, _, _) in meshes]
    bed = min(lows)

    total = over = on_bed = 0.0
    worst, tris, rows, layers = None, 0, [], []
    for (b, (c, n, idx, gap)), low in zip(meshes, lows):
        tc, tn, tcol, st = A.classify(c, n, idx, up, low if s['own_bed'] else bed, s['angle'], s['gradient'], TOL_CM)
        tris += len(idx) // 3
        total, over, on_bed = total + st['total'], over + st['overhang'], on_bed + st['bed']
        if st['worst'] is not None:
            worst = st['worst'] if worst is None else min(worst, st['worst'])
            rows.append((st['overhang'], b.name))
        if tc:
            layers.append((A.offset(tc, tn, gap), tn, tcol))

    lines = [_legend(s['angle']), '']
    if over:
        lines.append(tr('Voladizo: <b>%.0f mm²</b> (%.1f %% de la superficie), el peor a %.0f°')
                     % (over * 100, 100 * over / total, worst))
        if len(rows) > 1:
            lines += ['&nbsp; • %s: %.0f mm²' % (name, a * 100) for a, name in sorted(rows, reverse=True)]
    else:
        lines.append(tr('Sin voladizos.'))
    if on_bed:
        lines.append(tr('Apoyo en la cama: %.0f mm²') % (on_bed * 100))
    else:
        lines.append('<font color="#c80">⚠ %s</font>'
                     % tr('Nada apoya en plano sobre la cama: reorienta la pieza o usa borde de adherencia.'))
    lines.append('<font color="#888">%s</font>' % (tr('%d triángulos en %.2f s') % (tris, time.time() - t0)))
    _state['result'] = {'total': total, 'overhang': over, 'bed': on_bed, 'worst': worst}
    return '<br>'.join(lines), layers


class _CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            _state['cmd'] = cmd
            _drop_keep()   # mientras el diálogo está abierto se ve la vista previa
            _state.pop('html', None)
            cmd.isOKButtonVisible = False   # solo se mira: no hay nada que aceptar
            cmd.cancelButtonText = tr('Cerrar')
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
            dd = inputs.addDropDownCommandInput('quality', tr('Calidad de la malla'),
                                                adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label, _ in QUALITIES:
                dd.listItems.add(tr(label), key == s['quality'])
            keep = inputs.addBoolValueInput('keep', tr('Mantener al cerrar'), True, '', bool(s['keep']))
            keep.tooltip = tr('La capa se queda al cerrar el diálogo y se recalcula cada vez que cambia el modelo. '
                              'Para quitarla, vuelve a abrir el diálogo y desmárcala. No se guarda en el archivo.')
            inputs.addTextBoxCommandInput('info', tr('Resultado'), '', 8, True)
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
            if (args.commandId in (CMD_ID, TH_CMD_ID, 'SelectCommand')
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
            'th_keep': inputs.itemById('th_keep').value}


def _th_cast(mesh_body, coords, indices):
    """Espesor (cm) de cada triángulo: distancia desde su centro, por la normal hacia dentro, hasta el primer
    choque con la malla (sin contar el propio triángulo, que está a distancia 0)."""
    P, V = adsk.core.Point3D.create, adsk.core.Vector3D.create
    out = []
    for ray in T.rays(coords, indices):
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


def _th_solid(native, coords, indices):
    """Espesor de los triángulos de un cuerpo sólido. Los rayos solo se pueden lanzar contra cuerpos de malla,
    así que se crea uno temporal con la misma malla y se borra en seguida (dentro de la vista previa, Fusion
    lo desharía igualmente)."""
    design = adsk.fusion.Design.cast(native.parentComponent.parentDesign)
    root = design.rootComponent
    base = None
    if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        base = root.features.baseFeatures.add()
        base.startEdit()
    try:
        tmp = root.meshBodies.addByTriangleMeshData(coords, indices, [], [])
    finally:
        if base:
            base.finishEdit()
    try:
        tmp.isLightBulbOn = False
        return _th_cast(tmp, coords, indices)
    finally:
        for obj in (tmp, base):   # borrar la base no borra el cuerpo de malla
            try:
                if obj and obj.isValid:
                    obj.deleteMe()
            except Exception:
                pass


def _th_mesh(body, res):
    """(coords, normales, índices, espesor de cada triángulo, malla cerrada, separación) del cuerpo en
    coordenadas del raíz (cm), guardada mientras dure el diálogo."""
    key = (body.entityToken, res)
    if key not in _th_meshes:
        native = body.nativeObject or body
        mesh_body = adsk.fusion.MeshBody.cast(native)
        if mesh_body:
            pm = mesh_body.mesh
            coords, idx = list(pm.nodeCoordinatesAsDouble), list(pm.triangleNodeIndices)
            normals = list(pm.normalVectorsAsDouble)
            if len(normals) != len(coords):
                normals = T.vertex_normals(coords, idx)
            thick, closed, gap = _th_cast(mesh_body, coords, idx), mesh_body.isClosed, A.lift(0.0, 0.0)
        else:
            calc = native.meshManager.createMeshCalculator()
            calc.maxSideLength = dict((k, v) for k, _, v in RESOLUTIONS)[res]
            calc.surfaceTolerance = TH_SURFACE_TOL
            m = calc.calculate()
            coords, normals, idx = list(m.nodeCoordinatesAsDouble), list(m.normalVectorsAsDouble), list(m.nodeIndices)
            thick, closed = _th_solid(native, coords, idx), True
            gap = A.lift(TH_SURFACE_TOL, _display_tolerance(native))
        thick = T.convex_min(coords, idx, thick)   # cantos de las paredes finas
        if body.assemblyContext:   # el espesor no cambia al mover la pieza
            coords, normals = A.transform(coords, normals, body.assemblyContext.transform2.asArray())
        _th_meshes[key] = (coords, normals, idx, thick, closed, gap)
    return _th_meshes[key]


def _th_legend(s):
    sq = '<font color="#%02x%02x%02x">■</font>'
    if s['th_paint'] == 'thin':
        return '%s %s' % (sq % T.THIN[:3], tr('menos de %s mm') % _mm(s['th_limit']))
    lo, hi = s['th_lo'], s['th_hi']
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


def _th_analyse(design, s, picked):
    """(html del resultado, capas, cuerpos analizados)."""
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
    if s['th_limit'] <= 0:
        return tr('El espesor mínimo tiene que ser mayor que 0.'), [], bodies
    if s['th_paint'] == 'map' and s['th_hi'] <= s['th_lo']:
        return tr('El final de la escala tiene que ser mayor que el principio.'), [], bodies

    t0 = time.time()
    lo, hi, limit = s['th_lo'] / 10.0, s['th_hi'] / 10.0, s['th_limit'] / 10.0   # cm
    layers, rows, open_bodies = [], [], []
    thin = total = 0.0
    tris = 0
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
        html, layers, bodies = _th_analyse(design, s, picked)
        _th_state['last'] = {'design': design, 'settings': s, 'layers': layers, 'bodies': bodies}
    except Exception:
        html = '<b><font color="#d33">✖ %s</font></b><br>%s' % (
            tr('Error interno del complemento:'), traceback.format_exc().replace('\n', '<br>'))
    if _th_state.get('html') != html:
        _th_state['html'] = html
        inputs.itemById('th_info').formattedText = html
    if design:
        _paint(design, layers, TH_GROUP_ID)
    _app.activeViewport.refresh()


def _th_drop_keep():
    _clear(TH_KEEP_ID, _th_keep.get('design'))
    _th_keep.clear()


def _th_update_visibility(inputs):
    inputs.itemById('th_body_sel').isVisible = _choice(inputs, 'th_bodies', BODIES) == 'pick'
    is_map = _choice(inputs, 'th_paint', PAINTS) == 'map'
    inputs.itemById('th_lo').isVisible = is_map
    inputs.itemById('th_hi').isVisible = is_map


class _ThCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            _th_state['cmd'] = cmd
            _th_drop_keep()
            _th_state.pop('html', None)
            cmd.isOKButtonVisible = False
            cmd.cancelButtonText = tr('Cerrar')
            cmd.setDialogMinimumSize(380, 300)
            inputs = cmd.commandInputs
            s = _load_settings()
            VS = adsk.core.ValueInput.createByString

            dd = inputs.addDropDownCommandInput('th_bodies', tr('Cuerpos'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in BODIES:
                dd.listItems.add(tr(label), key == s['th_bodies'])
            sel = inputs.addSelectionInput('th_body_sel', tr('Selección'), tr('Elige los cuerpos.'))
            for f in ('SolidBodies', 'MeshBodies'):
                sel.addSelectionFilter(f)
            sel.setSelectionLimits(0, 0)
            inputs.addValueInput('th_limit', tr('Espesor mínimo'), 'mm', VS('%s mm' % s['th_limit']))
            dd = inputs.addDropDownCommandInput('th_paint', tr('Pintar'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in PAINTS:
                dd.listItems.add(tr(label), key == s['th_paint'])
            inputs.addValueInput('th_lo', tr('Escala desde'), 'mm', VS('%s mm' % s['th_lo']))
            inputs.addValueInput('th_hi', tr('Escala hasta'), 'mm', VS('%s mm' % s['th_hi']))
            dd = inputs.addDropDownCommandInput('th_res', tr('Resolución'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label, _ in RESOLUTIONS:
                dd.listItems.add(tr(label), key == s['th_res'])
            dd.tooltip = tr('Lado máximo de los triángulos con los que se mide. Más fina, más detalle y más lento.')
            keep = inputs.addBoolValueInput('th_keep', tr('Mantener al cerrar'), True, '', bool(s['th_keep']))
            keep.tooltip = tr('La capa se queda al cerrar el diálogo, hasta que cambie alguno de los cuerpos: '
                              'entonces se quita y hay que volver a abrir el diálogo. No se guarda en el archivo.')
            inputs.addTextBoxCommandInput('th_info', tr('Resultado'), '', 8, True)
            _th_update_visibility(inputs)

            for ev, h in ((cmd.executePreview, _ThPreviewHandler()), (cmd.inputChanged, _ThChangedHandler()),
                          (cmd.destroy, _ThDestroyHandler())):
                ev.add(h)
                _handlers.append(h)
        except Exception:
            _ui.messageBox(tr('Espesor de pared: error') + '\n' + traceback.format_exc())


class _ThPreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        _th_draw(args.command.commandInputs)


class _ThChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        if args.input.id == 'th_info':
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
               'ángulo límite desde la horizontal y en verde lo que apoya en la cama. No modifica el diseño.'),
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
            TH_CMD_ID, tr('Espesor de pared'),
            tr('Mapa de color del espesor de pared, de rojo (fino) a azul (grueso), o solo lo que no llega al '
               'espesor mínimo. No modifica el diseño.'),
            os.path.join(HERE, 'resources', 'thickness'))
        h = _ThCreatedHandler()
        th_def.commandCreated.add(h)
        _handlers.append(h)
        _app.unregisterCustomEvent(TH_KEEP_EVENT)
        h = _ThKeepHandler()
        _app.registerCustomEvent(TH_KEEP_EVENT).add(h)
        _handlers.append(h)
        for pid in PANEL_IDS:
            panel = _panel(pid)
            if panel and not panel.controls.itemById(CMD_ID):
                panel.controls.addCommand(cmd_def)
            if panel and not panel.controls.itemById(TH_CMD_ID):
                panel.controls.addCommand(th_def)
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
        for pid in PANEL_IDS:
            panel = _panel(pid)
            for cid in (CMD_ID, TH_CMD_ID):
                ctrl = panel.controls.itemById(cid) if panel else None
                if ctrl:
                    ctrl.deleteMe()
        for cid in (CMD_ID, TH_CMD_ID):
            cmd_def = _ui.commandDefinitions.itemById(cid)
            if cmd_def:
                cmd_def.deleteMe()
        _handlers.clear()
    except Exception:
        _ui.messageBox(tr('Voladizos FDM: error al parar') + '\n' + traceback.format_exc())
