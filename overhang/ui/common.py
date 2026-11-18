# Lo que comparten los comandos del add-in: identificadores, opciones de los desplegables, ajustes (settings.json),
# mallas de los cuerpos y las capas de gráficos personalizados.
import json
import os

import adsk.core
import adsk.fusion

from .. import analysis as A
from ..i18n import tr

# carpeta del add-in (la de FDMOverhang.py)
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
SL_SHOW_EVENT = 'buhoFdmSlicerShow'
SL_RESET_EVENT = 'buhoFdmSlicerReset'   # Restablecer: cierra el diálogo, borra y lo vuelve a abrir
SL_SAVE_EVENT = 'buhoFdmSlicerSave'   # Cerrar: escribe lo elegido en el diseño cuando el diálogo ya se ha cerrado
API_GROUP_ID = 'fdm_slicer_api'   # capa con lo marcado desde la API sin diálogo (show), fuera de cualquier comando
API_SEND_EVENT = 'buhoFdmApiSend'  # send() de la API exporta desde aquí: execute_code corta a los 30 s
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
# Ver a través: opacidad de los cuerpos medidos
XRAY = [('off', 'No', None), ('on', 'Transparencia 75 %', 0.25), ('vivid', 'Transparencia 88 %', 0.12)]
# Cómo se pinta la capa con los cuerpos transparentes (ver _paint)
LAYERS = [('top', 'Por encima (viva, puede tener huecos)'), ('inplace', 'En su sitio (sin huecos, más pálida)')]
BUSY_DELAY = 1       # s: si la medida acaba antes, no llega a salir la ventana de progreso
BUSY_EVERY = 2000    # rayos entre dos actualizaciones de la ventana de progreso
QUALITIES = [('low', 'Baja', adsk.fusion.TriangleMeshQualityOptions.LowQualityTriangleMesh),
             ('normal', 'Normal', adsk.fusion.TriangleMeshQualityOptions.NormalQualityTriangleMesh),
             ('high', 'Alta', adsk.fusion.TriangleMeshQualityOptions.HighQualityTriangleMesh)]

_app = adsk.core.Application.get()
_ui = _app.userInterface
_handlers = []


_meshes = {}    # (entityToken, calidad) -> malla en coordenadas del raíz; se vacía al cerrar el diálogo


def _default_bed():
    try:
        z_up = (_app.preferences.generalPreferences.defaultModelingOrientation
                == adsk.core.DefaultModelingOrientations.ZUpModelingOrientation)
    except Exception:
        z_up = True
    return 'z' if z_up else 'y'


def _sl_defaults():
    """Las opciones del diálogo Enviar al laminador por defecto; las que vuelven con Restablecer."""
    return {'sl_what': 'one', 'sl_body': None, 'sl_bed': _default_bed(), 'sl_mesh': 'high', 'sl_open': 'orca',
            'sl_color': False, 'sl_solo': True}


def _load_settings():
    s = {'bodies': 'visible', 'bed': _default_bed(), 'own_bed': False, 'angle': 45, 'gradient': True,
         'quality': 'normal', 'keep': False, 'bridge': True, 'bridge_max': 23.0, 'ov_solo': True,
         'th_bodies': 'visible', 'th_res': 'coarse', 'th_paint': 'map', 'th_limit': 0.8, 'th_lo': 0.0,
         'th_hi': 4.0, 'th_keep': False, 'th_mode': 'thickness', 'gap_limit': 0.1, 'gap_lo': 0.0, 'gap_hi': 2.0,
         'gap_others': True, 'th_xray': 'on', 'th_layer': 'inplace', 'sl_dir': '', 'slicer_paint': '', **_sl_defaults()}
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
    if isinstance(s['th_xray'], bool):   # antes era una casilla
        s['th_xray'] = 'on' if s['th_xray'] else 'off'
    return s


_saved = {}   # lo último escrito en settings.json: las vistas previas guardan cada vez, casi siempre lo mismo


def _save_settings(s):
    """Guarda los ajustes de un comando sin perder los del otro. Si no ha cambiado nada desde la última vez, no toca
    el archivo."""
    if _saved and all(k in _saved and _saved[k] == v for k, v in s.items()):
        return
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
        return
    _saved.clear()
    _saved.update(all_s)


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


def _paint(design, layers, group_id, solid=False):
    """Pinta las capas con color por vértice. Con solid, una malla de color sólido por color (A.split_by_color):
    hace falta con los cuerpos en transparencia, porque Fusion pinta las de color por vértice desordenadas con
    ellos y la capa se ve a trozos donde se mira a través de un cuerpo."""
    if not layers:
        return
    grp = design.rootComponent.customGraphicsGroups.add()
    grp.id = group_id
    for tc, tn, tcol in layers:
        if solid:
            for rgba, (pts, nrm) in A.split_by_color(tc, tn, tcol).items():
                mesh = grp.addMesh(adsk.fusion.CustomGraphicsCoordinates.create(pts), list(range(len(pts) // 3)), nrm, [])
                mesh.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(*rgba))
                mesh.depthPriority = 1
            continue
        coords = adsk.fusion.CustomGraphicsCoordinates.create(tc)
        coords.colors = tcol
        mesh = grp.addMesh(coords, list(range(len(tc) // 3)), tn, [])
        mesh.color = adsk.fusion.CustomGraphicsVertexColorEffect.create()
        mesh.depthPriority = 1   # por encima del cuerpo donde coincidan


def _mm(v):
    return ('%.2f' % v).rstrip('0').rstrip('.')


def _native_token(entity):
    return (entity.nativeObject or entity).entityToken


def _foreign(body):
    """Si el cuerpo es de un componente referenciado, también dentro de otro (ver ATTR_REFS)."""
    occ = body.assemblyContext
    while occ:
        if occ.isReferencedComponent:
            return True
        occ = occ.assemblyContext
    return False


API_MIN_OVERHANG = 0.01   # cm² (la API y Soportes en los voladizos): una cara cuenta como voladizo si tiene al menos 1 mm² en voladizo
