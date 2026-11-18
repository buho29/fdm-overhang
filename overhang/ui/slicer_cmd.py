# Comando "Enviar al laminador": exporta uno o varios cuerpos en STL con su cama y dónde forzar o prohibir la
# costura y los soportes, y los pasa a slicer-paint, que genera el 3MF pintado. Lo elegido se guarda en atributos
# buhoFdm del diseño (también lo usan Voladizos FDM y la API).
import json
import math
import os
import traceback

import adsk.core
import adsk.fusion

from .. import analysis as A
from .. import slicer as S
from ..i18n import tr
from .common import (API_GROUP_ID, BEDS, SL_CMD_ID, SL_DONE_EVENT, SL_GROUP_ID, SL_RESET_EVENT, SL_SAVE_EVENT,
                     SL_SHOW_EVENT, _app, _choice, _clear, _default_bed, _display_tolerance, _foreign, _handlers,
                     _load_settings, _native_token, _paint, _save_settings, _sl_defaults, _ui, _visible_bodies)


OPEN_IN = [('orca', 'OrcaSlicer'), ('bambu', 'Bambu Studio'), ('none', 'No abrir')]
# Malla del STL: (clave, texto, separación máxima de la superficie en mm, giro máximo entre triángulos en grados).
# Muy alta es la separación con la que Orca y Bambu Studio mallan un STEP al importarlo.
SL_MESH = [('low', 'Baja (0,05 mm)', 0.05, 12.0), ('medium', 'Media (0,025 mm)', 0.025, 6.0),
           ('high', 'Alta (0,01 mm)', 0.01, 3.0), ('ultra', 'Muy alta (0,003 mm)', 0.003, 1.5)]
FACE_TOL = 0.002    # cm: malla de las caras elegidas; solo sirve para reconocer sus triángulos en el STL
STROKE_TOL = 0.001  # cm: puntos de las aristas elegidas
# (campo, tipo, papel, color, texto de la leyenda)
SL_ROLES = [('sl_seam_on', 'seam', 'enforce', (0, 190, 230), 'costura forzada'),
            ('sl_seam_off', 'seam', 'block', (255, 150, 0), 'costura prohibida'),
            ('sl_sup_on', 'support', 'enforce', (60, 200, 60), 'soportes forzados'),
            ('sl_sup_off', 'support', 'block', (220, 30, 30), 'soportes bloqueados')]
SL_WHAT = [('one', 'Este cuerpo'), ('plate', 'Varios en una placa')]
ROLE_KEYS = [r[0] for r in SL_ROLES]
# Lo elegido para cada cuerpo se guarda en el diseño, con atributos de Fusion, y se recupera al volver a abrirlo:
ATTR_GROUP = 'buhoFdm'
ATTR_BODY = 'slicer'       # en el cuerpo: {"bed": "z", "plate": true}
ATTR_ROLE = 'slicerRole'   # en cada cara o arista elegida: sus campos (sl_face, sl_seam_on…), separados por comas
# Los cuerpos de un componente referenciado (de otro archivo) no pueden llevar los atributos: irían al otro archivo,
# que no se guarda con este, y findAttributes de este diseño no los ve. Lo suyo va en un atributo del diseño:
# {"ruta de la ocurrencia|cuerpo": {"bed": "face", "plate": true, "roles": [[entityToken, "sl_face"], …]}}
ATTR_REFS = 'slicerRefs'
PLATE_MARK = '  ✔'         # en la lista de cuerpos, los que van en la placa
# 'bodies': [(nombre, cuerpo)] de la lista; 'cfgs': {índice: lo elegido para ese cuerpo}; 'current': el índice que
# muestra el diálogo, cuya configuración está en los campos y no en 'cfgs'; 'touched': los que hay que guardar
_sl_state = {}


def _sl_index(inputs):
    item = inputs.itemById('sl_body').selectedItem
    return item.index if item and item.index < len(_sl_state.get('bodies', [])) else None


def _sl_read(inputs):
    """Los ajustes que valen para todos los cuerpos. La cama se guarda también: es la de un cuerpo nuevo."""
    i = _sl_index(inputs)
    return {'sl_body': _sl_state['bodies'][i][0] if i is not None else None,
            'sl_what': _choice(inputs, 'sl_what', SL_WHAT), 'sl_bed': _choice(inputs, 'sl_bed', BEDS),
            'sl_mesh': _choice(inputs, 'sl_mesh', SL_MESH),
            'sl_open': _choice(inputs, 'sl_open', OPEN_IN), 'sl_color': inputs.itemById('sl_color').value,
            'sl_solo': inputs.itemById('sl_solo').value}


def _picked(inputs, key):
    sel = inputs.itemById(key)
    return [sel.selection(i).entity for i in range(sel.selectionCount)]


def _sl_bodies(design):
    """[(nombre para la lista, cuerpo)] de los sólidos visibles. Con el componente si el nombre se repite."""
    bodies = [b for b in _visible_bodies(design.rootComponent) if getattr(b, 'isSolid', False)] if design else []
    labels = [b.name for b in bodies]
    # Los nombres tienen que ser únicos: el diálogo elige por nombre, y con dos iguales la lista marcaba uno y los
    # campos eran del otro (Cuerpo298 en gear base:1+Gear:1 y en gear pan:1+Gear:1). Primero con la ocurrencia y,
    # si no basta, con la ruta entera.
    for detail in (lambda o: o.name, lambda o: o.fullPathName.replace('+', ' › ')):
        labels = [('%s (%s)' % (b.name, detail(b.assemblyContext)) if labels.count(label) > 1 and b.assemblyContext
                   else label) for label, b in zip(labels, bodies)]
    repeated = {label for label in labels if labels.count(label) > 1}
    seen = {}
    for i, label in enumerate(labels):
        if label in repeated:
            seen[label] = seen.get(label, 0) + 1
            labels[i] = '%s #%d' % (label, seen[label])
    return list(zip(labels, bodies))


def _sl_body(inputs):
    """El cuerpo elegido en la lista, o None. Es una lista y no un campo de selección porque Fusion resalta en azul
    el cuerpo seleccionado entero y taparía lo que se pinta encima."""
    i = _sl_index(inputs)
    if i is None:
        return None
    body = _sl_state['bodies'][i][1]
    return body if body.isValid else None


# ------------------------------------------------ lo elegido para cada cuerpo

def _sl_empty(bed):
    return dict({'bed': bed, 'face': None, 'plate': False}, **{k: [] for k in ROLE_KEYS})


def _sl_cfg_read(inputs):
    """Lo elegido en el diálogo para el cuerpo que muestra."""
    face = _picked(inputs, 'sl_face')
    cfg = {'bed': _choice(inputs, 'sl_bed', BEDS), 'face': face[0] if face else None,
           'plate': inputs.itemById('sl_plate').value}
    for k in ROLE_KEYS:
        cfg[k] = _picked(inputs, k)
    return cfg


def _sl_cfg_show(inputs, cfg, selections=True):
    """Pone en el diálogo lo elegido para un cuerpo. 'loading' evita que los cambios cuenten como del usuario.
    Al abrir el diálogo, las selecciones se ponen después, en _SlShowHandler."""
    _sl_state['loading'] = True
    try:
        dd = inputs.itemById('sl_bed')
        for i, (key, _) in enumerate(BEDS):
            if key == cfg['bed']:
                dd.listItems.item(i).isSelected = True
        inputs.itemById('sl_plate').value = cfg['plate']
        if not selections:
            return
        chosen = [('sl_face', [cfg['face']] if cfg['face'] else [])] + [(k, cfg[k]) for k in ROLE_KEYS]
        # primero se vacían todos: una cara elegida en dos campos es una sola selección, y vaciar un campo la quita
        # también del otro
        for key, _ in chosen:
            inputs.itemById(key).clearSelection()
        for key, ents in chosen:
            for e in ents:
                if e and e.isValid:
                    inputs.itemById(key).addSelection(e)
    finally:
        _sl_state['loading'] = False


def _sl_cfg(inputs, i):
    """Lo elegido para el cuerpo i de la lista: el del diálogo si es el que muestra."""
    if i == _sl_state.get('current'):
        return _sl_cfg_read(inputs)
    return _sl_state['cfgs'].get(i) or _sl_empty(_load_settings()['sl_bed'])


def _sl_plate(inputs):
    """[(índice, nombre, cuerpo, lo elegido)] de los cuerpos que van en la placa, en el orden de la lista."""
    out = []
    for i, (name, body) in enumerate(_sl_state.get('bodies', [])):
        cfg = _sl_cfg(inputs, i)
        if cfg['plate'] and body.isValid:
            out.append((i, name, body, cfg))
    return out


def _sl_marks(inputs):
    """Marca en la lista los cuerpos que van en la placa."""
    dd = inputs.itemById('sl_body')
    _sl_state['loading'] = True
    try:
        for i, (name, _) in enumerate(_sl_state.get('bodies', [])):
            label = name + (PLATE_MARK if _sl_cfg(inputs, i)['plate'] else '')
            item = dd.listItems.item(i)
            if item.name != label:
                item.name = label
    finally:
        _sl_state['loading'] = False


def _ref_key(body):
    return '%s|%s' % (body.assemblyContext.fullPathName, body.name)


def _ref_read(design):
    a = design.attributes.itemByName(ATTR_GROUP, ATTR_REFS)
    try:
        return json.loads(a.value) if a else {}
    except ValueError:
        return {}


def _ref_write(design, refs):
    if refs:
        design.attributes.add(ATTR_GROUP, ATTR_REFS, json.dumps(refs, ensure_ascii=False))
    else:
        a = design.attributes.itemByName(ATTR_GROUP, ATTR_REFS)
        if a:
            a.deleteMe()


def _ref_entities(design, body, saved):
    """[(cara o arista en el contexto del cuerpo, campos)] de lo guardado para un cuerpo referenciado."""
    out = []
    occ, token = body.assemblyContext, _native_token(body)
    for ent_token, value in saved.get('roles', []):
        try:
            found = design.findEntityByToken(ent_token)
        except Exception:
            continue
        for e in found:
            e = adsk.fusion.BRepFace.cast(e) or adsk.fusion.BRepEdge.cast(e)
            if e and e.isValid and _native_token(e.body) == token:
                out.append(((e.nativeObject or e).createForAssemblyContext(occ), S.role_keys(value)))
                break
    return out


def _sl_load(design, bodies):
    """{índice: lo elegido} de los cuerpos de la lista que lo tienen guardado en el diseño. Los atributos están en
    los objetos nativos: dos ocurrencias del mismo componente comparten lo elegido."""
    by_token = {}
    for i, (_, b) in enumerate(bodies):
        by_token.setdefault(_native_token(b), []).append(i)
    default = _load_settings()['sl_bed']
    out = {}
    for a in design.findAttributes(ATTR_GROUP, ATTR_BODY):
        if not a.parent:
            continue
        try:
            d = json.loads(a.value)
        except ValueError:
            continue
        for i in by_token.get(a.parent.entityToken, []):
            cfg = out[i] = _sl_empty(d.get('bed') if d.get('bed') in dict(BEDS) else default)
            cfg['plate'] = bool(d.get('plate'))
    for a in design.findAttributes(ATTR_GROUP, ATTR_ROLE):
        ent = a.parent
        if not ent:
            continue
        for i in by_token.get(ent.body.entityToken, []):
            occ = bodies[i][1].assemblyContext
            proxy = ent.createForAssemblyContext(occ) if occ else ent
            cfg = out.setdefault(i, _sl_empty(default))
            for key in S.role_keys(a.value):
                if key == 'sl_face':
                    cfg['face'] = proxy
                elif key in cfg:
                    cfg[key].append(proxy)
    refs = _ref_read(design)
    for i, (_, b) in enumerate(bodies if refs else []):
        saved = refs.get(_ref_key(b)) if _foreign(b) else None
        if not saved:
            continue
        cfg = out[i] = _sl_empty(saved.get('bed') if saved.get('bed') in dict(BEDS) else default)
        cfg['plate'] = bool(saved.get('plate'))
        for proxy, keys in _ref_entities(design, b, saved):
            for key in keys:
                if key == 'sl_face':
                    cfg['face'] = proxy
                elif key in cfg:
                    cfg[key].append(proxy)
    return out


def _sl_store(design, current_cfg):
    """Guarda en el diseño lo elegido para los cuerpos que se han tocado en el diálogo; current_cfg es lo del que se
    ve, leído antes: borrar el atributo de una cara la quita de su campo de selección. Un cuerpo sin nada elegido,
    fuera de la placa y con la cama por defecto deja de estar guardado."""
    cfgs = dict(_sl_state['cfgs'])
    current = _sl_state.get('current')
    if current is not None:
        cfgs[current] = current_cfg
    touched = _sl_state['touched'] | ({current} if current is not None else set())
    old_roles = list(design.findAttributes(ATTR_GROUP, ATTR_ROLE))
    for i in sorted(touched):
        body, cfg = _sl_state['bodies'][i][1], cfgs[i]
        if body.isValid:
            _sl_store_one(design, body, cfg, old_roles)


def _sl_store_one(design, body, cfg, old_roles):
    """Guarda en el diseño lo elegido para un cuerpo (cfg), en sus objetos nativos; el de un componente referenciado,
    en el diseño (ATTR_REFS). old_roles: los atributos de papel del diseño leídos antes de cambiar nada; se borran
    los de este cuerpo."""
    chosen = [('sl_face', [cfg['face']] if cfg['face'] and cfg['bed'] == 'face' else [])]
    if _foreign(body):
        roles = {}
        for key, ents in chosen + [(k, cfg[k]) for k in ROLE_KEYS]:
            for e in ents:
                if e.isValid:
                    roles.setdefault(e.entityToken, []).append(key)
        refs = _ref_read(design)
        if roles or cfg['plate'] or cfg['bed'] != _default_bed():
            refs[_ref_key(body)] = {'bed': cfg['bed'], 'plate': cfg['plate'],
                                    'roles': [[t, S.role_value(keys)] for t, keys in roles.items()]}
        else:
            refs.pop(_ref_key(body), None)
        _ref_write(design, refs)
        return
    native = body.nativeObject or body
    token = native.entityToken
    for a in old_roles:
        if a.isValid and a.parent and a.parent.body.entityToken == token:
            a.deleteMe()
    marks = {}
    for key, ents in chosen + [(k, cfg[k]) for k in ROLE_KEYS]:
        for e in ents:
            if e.isValid:
                n = e.nativeObject or e
                marks.setdefault(n.entityToken, (n, []))[1].append(key)
    for n, keys in marks.values():
        n.attributes.add(ATTR_GROUP, ATTR_ROLE, S.role_value(keys))
    old = native.attributes.itemByName(ATTR_GROUP, ATTR_BODY)
    if marks or cfg['plate'] or cfg['bed'] != _default_bed():
        native.attributes.add(ATTR_GROUP, ATTR_BODY, json.dumps({'bed': cfg['bed'], 'plate': cfg['plate']}))
    elif old:
        old.deleteMe()


def _same_body(entity, body):
    """Si la arista o la cara es del cuerpo, también dentro de una ocurrencia."""
    try:
        return entity.body.entityToken == body.entityToken
    except Exception:
        return False


def _sl_isolate(design, bodies):
    """Apaga todo lo que no son los cuerpos, solo en la vista previa: Fusion lo vuelve a encender al rehacerla y al
    cerrar el diálogo. Se apagan las ocurrencias que no llevan a ninguno y, en el raíz y en las que sí, los demás
    cuerpos. No se apaga el cuerpo nativo de otra ocurrencia del mismo componente: la bombilla de un cuerpo es de su
    componente, y apagaría también el elegido."""
    path, keep = set(), set()
    for body in bodies:
        keep.add((body.nativeObject or body).entityToken)
        occ = body.assemblyContext
        while occ:
            path.add(occ.fullPathName)
            occ = occ.assemblyContext

    def others(found):
        for b in list(found):
            if b.isLightBulbOn and (b.nativeObject or b).entityToken not in keep:
                b.isLightBulbOn = False

    def walk(occurrences):
        for o in list(occurrences):
            if o.fullPathName in path:
                others(o.bRepBodies)
                others(o.meshBodies)
                walk(o.childOccurrences)
            elif o.isLightBulbOn:
                o.isLightBulbOn = False

    root = design.rootComponent
    others(root.bRepBodies)
    others(root.meshBodies)
    walk(root.occurrences)


def _sl_zoom(bodies):
    """Acerca la cámara a los cuerpos sin girarla: misma dirección de vista, centrada en su caja y a la distancia
    en la que caben enteros. La cámara no es parte del diseño: Fusion no la repone al rehacer la vista previa."""
    box = None
    for b in bodies:   # de un proxy, la caja ya está en coordenadas del raíz
        if box is None:
            box = b.boundingBox.copy()
        else:
            box.combine(b.boundingBox)
    if box is None:
        return
    lo, hi = box.minPoint, box.maxPoint
    center = adsk.core.Point3D.create((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, (lo.z + hi.z) / 2)
    radius = max(lo.distanceTo(hi) / 2, 0.1)
    vp = _app.activeViewport
    cam = vp.camera
    look = cam.target.vectorTo(cam.eye)
    look.normalize()
    angle = cam.perspectiveAngle if cam.perspectiveAngle > 0.01 else math.radians(30)
    look.scaleBy(radius * 1.15 / math.sin(angle / 2))   # la esfera de la caja cabe en el cono de la vista
    eye = center.copy()
    eye.translateBy(look)
    cam.target = center
    cam.eye = eye
    cam.viewExtents = radius * 1.15   # en ortográfica manda esto, no la distancia
    cam.isFitView = False
    cam.isSmoothTransition = True
    vp.camera = cam


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


def _sl_bed(cfg, body):
    """Normal hacia fuera de la cara de la cama, o un texto de error."""
    if cfg['bed'] != 'face':
        return S.bed_vector(cfg['bed'])
    if not cfg['face'] or not cfg['face'].isValid:
        return tr('Elige la cara plana que va sobre la cama.')
    face = adsk.fusion.BRepFace.cast(cfg['face'])
    native = face.nativeObject or face
    _, n = native.evaluator.getNormalAtPoint(native.pointOnFace)   # en un sólido, hacia fuera
    n = [n.x, n.y, n.z]
    tf = _to_root(body)
    if tf:
        n = A.transform([], n, tf)[1]
    return S.bed_vector('face', n)


def _sl_rgb(entity, cache):
    """'#RRGGBB' del aspecto que se ve en un cuerpo o una cara (el suyo o el heredado), o None si no tiene un color
    fijo. cache: {aspecto: color}, para no leer el mismo aspecto en cada cara. La clave lleva el nombre porque un
    aspecto copiado de otro conserva su id; dentro del diseño, el nombre no se repite."""
    ap = entity.appearance
    if not ap:
        return None
    key = (ap.id, ap.name)
    if key not in cache:
        props = []
        for p in ap.appearanceProperties:
            if isinstance(p, adsk.core.ColorProperty):
                v = p.value
                props.append((p.id, (v.red, v.green, v.blue) if v else None))
        cache[key] = S.appearance_rgb(props)
    return cache[key]


def _sl_colors(body, cache=None):
    """(color del cuerpo, [(cara, color)] de las caras que tienen otro)."""
    cache = {} if cache is None else cache
    body_rgb = _sl_rgb(body, cache)
    faces = []
    for face in body.faces:
        rgb = _sl_rgb(face, cache)
        if rgb != body_rgb:
            faces.append((face, rgb))
    return body_rgb, faces


def TOO_MANY_COLORS():
    return tr('Demasiados colores: slicer-paint pinta hasta %d filamentos.') % S.MAX_FILAMENT


def _sl_palette(bodies):
    """{color: filamento} de los cuerpos que se envían, en ese orden (S.palette)."""
    cache = {}
    pieces = []
    for body in bodies:
        body_rgb, faces = _sl_colors(body, cache)
        pieces.append((body_rgb, [rgb for _, rgb in faces]))
    return S.palette(pieces)


def _count(n_edges, n_faces):
    parts = []
    if n_edges:
        parts.append(tr('%d arista') % n_edges if n_edges == 1 else tr('%d aristas') % n_edges)
    if n_faces:
        parts.append(tr('%d cara') % n_faces if n_faces == 1 else tr('%d caras') % n_faces)
    return ', '.join(parts)


def _sl_collect(body, cfg, pal=None, send=False):
    """(archivo de pieza o None, html, capas, aristas [(coords, color)]) de un cuerpo con lo elegido para él (cfg).
    pal: {color: filamento} si se envían los colores (_sl_palette). Las caras de color solo se mallan al enviar
    (send): en la vista previa basta con contarlas."""
    bed = _sl_bed(cfg, body)
    if isinstance(bed, str):
        return None, bed, [], []
    layers, lines, roles, rows = [], [], {}, []
    lift = None   # pedir la malla de pantalla cuesta unos 40 ms: una vez por cuerpo, no por cara
    sq = '<font color="#%02x%02x%02x">■</font> %s'
    for key, kind, role, rgb, label in SL_ROLES:
        edges, faces = [], []
        for ent in cfg[key]:
            if not ent.isValid:
                continue
            if not _same_body(ent, body):
                return None, tr('Lo elegido tiene que ser del cuerpo que se envía.'), [], []
            face, edge = adsk.fusion.BRepFace.cast(ent), adsk.fusion.BRepEdge.cast(ent)
            if face:
                data, (c, n, idx) = _sl_face(face, body)
                faces.append(data)
                if lift is None:
                    lift = A.lift(FACE_TOL, _display_tolerance(body.nativeObject or body))
                layers.append(_soup(c, n, idx, rgb, lift))
                # el resaltado de Fusion tapa la cara elegida, pero no las líneas: el contorno lleva el color
                lines += [(_sl_edge(e, body), rgb) for e in face.edges]
            elif edge:
                pts = _sl_edge(edge, body)
                edges.append(S.edge([pts[i:i + 3] for i in range(0, len(pts), 3)]))
                lines.append((pts, rgb))
        roles['%s_%s' % (kind, role)] = S.selection(edges, faces)
        if edges or faces:
            rows.append(sq % (rgb + ('%s: %s' % (tr(label), _count(len(edges), len(faces))),)))

    color, color_rows = None, []
    if pal is not None:
        body_rgb, faces = _sl_colors(body)
        groups = {}
        for face, rgb in faces:
            groups.setdefault(rgb, []).append(face)
        zones = [(rgb, [_sl_face(f, body)[0] for f in fs] if send else fs) for rgb, fs in groups.items()]
        color = S.color_section(body_rgb, zones, pal)
        for rgb, what in [(body_rgb, tr('cuerpo'))] + [(rgb, _count(0, len(fs))) for rgb, fs in groups.items()]:
            dot = '<font color="%s">■</font> ' % rgb if rgb else '□ '
            color_rows.append(dot + tr('filamento %d: %s') % (pal[rgb], what + (' %s' % rgb if rgb else '')))

    job = S.job(body.name, bed, color if send else None, **roles)
    html = [tr('Cuerpo: <b>%s</b>') % body.name, tr('Cama: %s') % tr(dict(BEDS)[cfg['bed']]), '']
    html += rows or [tr('Nada elegido a mano.')]
    if color_rows:
        html += ['', tr('Colores (carga cada uno en su filamento):')] + color_rows
    return job, '<br>'.join(html), layers, lines


def _sl_paint(design, layers, lines, group_id=SL_GROUP_ID):
    _paint(design, layers, group_id)
    if not lines:
        return
    groups = [g for g in design.rootComponent.customGraphicsGroups if g.id == group_id]
    grp = groups[0] if groups else design.rootComponent.customGraphicsGroups.add()
    grp.id = group_id
    for pts, rgb in lines:
        ln = grp.addLines(adsk.fusion.CustomGraphicsCoordinates.create(pts), [], True)
        ln.weight = 4
        ln.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(*(rgb + (255,))))
        ln.depthPriority = 2


def _sl_sig(inputs):
    """Lo que hay en el diálogo (valores y selecciones), sin lo que no cambia el resultado, como abrir un grupo."""
    out = []

    def walk(coll):
        for i in range(coll.count):
            inp = coll.item(i)
            sel = adsk.core.SelectionCommandInput.cast(inp)
            if sel:
                out.append((inp.id, tuple(sel.selection(j).entity.entityToken for j in range(sel.selectionCount))))
                continue
            grp = adsk.core.GroupCommandInput.cast(inp)
            if grp:
                walk(grp.children)
                continue
            dd = adsk.core.DropDownCommandInput.cast(inp)
            if dd:
                out.append((inp.id, dd.selectedItem.name if dd.selectedItem else None))
                continue
            bv = adsk.core.BoolValueCommandInput.cast(inp)
            if bv:
                out.append((inp.id, bv.value))
    walk(inputs)
    return tuple(out)


def _sl_draw(inputs):
    """Como _draw: resultado y capa con lo que va a cada papel. Si en el diálogo no ha cambiado nada que cuente
    (al abrir o cerrar un grupo, Fusion rehace igual la vista previa), repinta lo de la vez anterior: calcularlo
    lleva medio segundo con una placa de 12 cuerpos y colores."""
    _clear(SL_GROUP_ID)
    layers, lines = [], []
    design = adsk.fusion.Design.cast(_app.activeProduct)
    try:
        sig = _sl_sig(inputs)
    except Exception:
        sig = None
    last = _sl_state.get('drawn')
    if sig is not None and last and last[0] == sig and design:
        _sl_paint(design, last[1], last[2])
        _app.activeViewport.refresh()
        return
    try:
        s = _sl_read(inputs)
        _save_settings(s)
        body = _sl_body(inputs) if design else None
        if not design:
            html = tr('Abre un diseño (espacio de trabajo DISEÑO).')
        elif not body:
            html = tr('No hay ningún cuerpo sólido visible.')
        else:
            cfg = _sl_cfg_read(inputs)
            head = []
            plate = _sl_plate(inputs) if s['sl_what'] == 'plate' else []
            if s['sl_what'] == 'plate':
                head.append(tr('Placa: <b>%s</b>') % ', '.join(n for _, n, _, _ in plate) if plate else
                            tr('Ningún cuerpo en la placa: marca <b>Incluir en la placa</b>.'))
                if plate and not cfg['plate']:
                    head.append(tr('Este cuerpo no va en la placa.'))
                head.append('')
            pal = None
            if s['sl_color']:
                bodies = [b for _, _, b, _ in plate] if s['sl_what'] == 'plate' else []
                if all(b.entityToken != body.entityToken for b in bodies):
                    bodies.append(body)
                try:
                    pal = _sl_palette(bodies)
                except ValueError:
                    head += [TOO_MANY_COLORS(), '']
            _, html, layers, lines = _sl_collect(body, cfg, pal)
            exe = S.find_exe(_load_settings()['slicer_paint'])
            tail = ['', '<font color="#888">slicer-paint: %s</font>' % exe if exe else
                    '<font color="#c80">⚠ %s</font>' % tr('No encuentro slicer-paint: al enviar te preguntaré '
                                                          'dónde está.')]
            html = '<br>'.join(head + [html] + tail)
    except Exception:
        html = '<b><font color="#d33">✖ %s</font></b><br>%s' % (
            tr('Error interno del complemento:'), traceback.format_exc().replace('\n', '<br>'))
    if _sl_state.get('html') != html:
        _sl_state['html'] = html
        inputs.itemById('sl_info').formattedText = html
    _sl_state['drawn'] = (sig, layers, lines)
    if design:
        _sl_paint(design, layers, lines)
    _app.activeViewport.refresh()


def _sl_update_visibility(inputs):
    inputs.itemById('sl_face').isVisible = _choice(inputs, 'sl_bed', BEDS) == 'face'
    inputs.itemById('sl_plate').isVisible = _choice(inputs, 'sl_what', SL_WHAT) == 'plate'


def _sl_target(s, name):
    """Ruta del 3MF que elige el usuario, o None si cancela."""
    dlg = _ui.createFileDialog()
    dlg.title = tr('Enviar al laminador')
    dlg.filter = '3MF (*.3mf)'
    if s.get('sl_dir') and os.path.isdir(s['sl_dir']):
        dlg.initialDirectory = s['sl_dir']
    dlg.initialFilename = S.safe_name(name)
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


def _sl_export(body, stl, quality):
    """Escribe el STL del cuerpo, en mm y en las coordenadas del raíz, con la calidad de malla elegida. Un texto de
    error, o None. No usa la exportación STL de Fusion: por la API no hace caso de la separación de la superficie, y
    sus calidades Baja, Media y Alta dan la misma malla."""
    _, _, dev_mm, turn_deg = next(q for q in SL_MESH if q[0] == quality)
    native = body.nativeObject or body
    calc = native.meshManager.createMeshCalculator()
    calc.surfaceTolerance = dev_mm / S.MM_PER_CM
    calc.maxNormalDeviation = turn_deg   # en grados, aunque la ayuda de la API dice radianes (medido)
    m = calc.calculate()
    coords = list(m.nodeCoordinatesAsDouble)
    tf = _to_root(body)
    if tf:   # la malla sale en las coordenadas del componente del cuerpo
        coords, _ = A.transform(coords, [], tf)
    try:
        S.write_stl(stl, coords, list(m.nodeIndices))
    except OSError as e:
        return tr('No se pudo exportar el STL: %s') % ('%s\n%s' % (stl, e))
    bb = body.boundingBox
    body_box = (bb.minPoint.asArray(), bb.maxPoint.asArray())
    stl_box = S.stl_bounds(stl)
    if not S.bounds_match(stl_box, body_box):
        return tr('El STL no está en las coordenadas del diseño: las zonas no caerían sobre la pieza.\n'
                  'STL (mm): %s\nCuerpo (cm): %s') % (stl_box, body_box)
    return None


def _sl_send(design, s, inputs):
    """Guarda en el diseño lo elegido, exporta los STL, escribe los archivos de pieza (y el de placa) y lanza
    slicer-paint. Devuelve un mensaje para el usuario, '' si no hay nada que decir todavía (slicer-paint avisa al
    acabar) o None si se cancela."""
    body = _sl_body(inputs)
    if not body:
        return tr('No hay ningún cuerpo sólido visible.')
    current_cfg = _sl_cfg_read(inputs)
    plate = s['sl_what'] == 'plate'
    if plate:
        items = [(name, b, cfg) for _, name, b, cfg in _sl_plate(inputs)]
    else:
        items = [(_sl_state['bodies'][_sl_state['current']][0], body, current_cfg)]
    _sl_store(design, current_cfg)   # después de leer el diálogo, que guardar vacía campos
    if not items:
        return tr('Ningún cuerpo en la placa: marca Incluir en la placa en los que quieras enviar.')
    jobs = _sl_jobs(items, s['sl_color'], plate)
    if isinstance(jobs, str):
        return jobs
    names = [name for name, _, _ in items]
    target = _sl_target(_load_settings(), tr('placa') if plate else names[0])
    if not target:
        return None
    _save_settings({'sl_dir': os.path.dirname(target)})
    exe = _sl_exe()   # antes de exportar, para que los dos diálogos vayan seguidos
    open_in = None if s['sl_open'] == 'none' else s['sl_open']
    return _sl_write_run(items, jobs, target, plate, s['sl_mesh'], open_in, exe)[0]


def _sl_jobs(items, color, plate):
    """[archivo de pieza] de cada (nombre, cuerpo, lo elegido), o un texto de error. color: con los colores (AMS)."""
    try:
        pal = _sl_palette([b for _, b, _ in items]) if color else None
    except ValueError:
        return TOO_MANY_COLORS()
    jobs = []
    for name, body, cfg in items:
        job, html, _, _ = _sl_collect(body, cfg, pal, send=True)
        if job is None:
            return ('%s: %s' % (name, html) if plate else html).replace('<br>', '\n')
        jobs.append(job)
    return jobs


def _sl_write_run(items, jobs, target, plate, mesh, open_in, exe, quiet=False):
    """Exporta los STL, escribe los archivos de pieza (y el de placa) junto al 3MF 'target' y lanza slicer-paint (exe)
    si lo hay. Devuelve (mensaje para el usuario, datos): el mensaje es '' si slicer-paint avisa al acabar; los datos,
    {'out', 'plate', 'files', 'log', 'command', 'running'}. quiet: al acabar, sin ventanas (para la API)."""
    names = [name for name, _, _ in items]
    if plate:
        plate_path, out, files = S.plate_paths(target, names)
    else:
        plate_path = None
        stl, job_path, out = S.paths(target)
        files = [(stl, job_path)]
    info = {'out': out, 'plate': plate_path, 'files': files, 'log': None, 'command': None, 'running': False}
    for (_, body, _), job, (stl, job_path) in zip(items, jobs, files):
        err = _sl_export(body, stl, mesh)
        if err:
            return err, info
        with open(job_path, 'w', encoding='utf-8') as f:
            json.dump(job, f, ensure_ascii=False)
    if plate:
        with open(plate_path, 'w', encoding='utf-8') as f:
            json.dump(S.plate(names, files), f, ensure_ascii=False, indent=2)
    if not exe:
        if plate:
            argv = ' '.join('"%s"' % a for a in S.plate_command('slicer-paint', plate_path, out))
            info['command'] = argv
            return tr('Guardados la placa %s y sus piezas.\n\nSin slicer-paint. Para generar el 3MF, ejecútalo a '
                      'mano:\n%s') % (plate_path, argv), info
        argv = ' '.join('"%s"' % a for a in S.command('slicer-paint', files[0][0], files[0][1], out))
        info['command'] = argv
        return tr('Guardados %s y %s.\n\nSin slicer-paint. Para generar el 3MF, ejecútalo a mano:\n%s') % (
            files[0][0], files[0][1], argv), info
    argv = (S.plate_command(exe, plate_path, out, open_in) if plate
            else S.command(exe, files[0][0], files[0][1], out, open_in))
    log = os.path.splitext(target)[0] + '.log'
    info.update(log=log, command=argv, running=True)
    _sl_run(argv, out, log, open_in, quiet)
    return '', info


def _sl_run(argv, out, log, open_in, quiet=False):
    """Lanza slicer-paint sin esperar y avisa al acabar con SL_DONE_EVENT: Fusion sigue libre mientras. quiet: el
    aviso solo se guarda en _sl_state['done'], sin ventanas."""
    import subprocess
    import threading

    _sl_state['done'] = {'running': True, 'out': out, 'log': log}

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
        _app.fireCustomEvent(SL_DONE_EVENT, json.dumps({'code': code, 'out': out, 'log': log, 'open': open_in,
                                                        'quiet': quiet}))

    threading.Thread(target=wait, daemon=True).start()


class _SlDoneHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        try:
            r = json.loads(args.additionalInfo)
            _sl_state['done'] = r
            if r['code'] == -1:   # no se pudo lanzar: se vuelve a preguntar la próxima vez
                _save_settings({'slicer_paint': ''})
            if r.get('quiet'):
                return
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
            _sl_state.pop('shown', None)
            # lo que esté seleccionado al abrir, Fusion lo mete en el campo que tiene el foco: también lo del envío
            # anterior, que podría acabar en otro papel
            _ui.activeSelections.clear()
            _clear(API_GROUP_ID)   # lo que pintó show(): el diálogo pinta lo suyo y lo que cambie dejaría de valer
            cmd.okButtonText = tr('Enviar')   # guarda, envía y cierra
            cmd.cancelButtonText = tr('Cerrar')   # guarda y cierra (_SlDestroyHandler)
            cmd.isExecutedWhenPreEmpted = False   # abrir otro comando no debe enviar
            cmd.setDialogInitialSize(380, 640)
            cmd.setDialogMinimumSize(380, 300)
            inputs = cmd.commandInputs
            s = _load_settings()
            dd = inputs.addDropDownCommandInput('sl_what', tr('Enviar'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in SL_WHAT:
                dd.listItems.add(tr(label), key == s['sl_what'])
            dd.tooltip = tr('Un cuerpo en su 3MF, o varios en una sola placa: los marcados con Incluir en la placa, '
                            'cada uno con lo que tenga elegido.')
            dd = inputs.addDropDownCommandInput('sl_body', tr('Cuerpo'), adsk.core.DropDownStyles.TextListDropDownStyle)
            dd.tooltip = tr('El cuerpo que vas a imprimir.')
            design = adsk.fusion.Design.cast(_app.activeProduct)
            bodies = _sl_bodies(design)
            _sl_state['bodies'] = bodies
            names = [n for n, _ in bodies]
            last = s.get('sl_body') if s.get('sl_body') in names else (names[0] if names else None)
            for name in names:
                dd.listItems.add(name, name == last)
            _sl_state['cfgs'] = _sl_load(design, bodies) if design else {}
            _sl_state['touched'] = set()
            _sl_state['current'] = names.index(last) if last is not None else None
            _sl_state.pop('camera', None)
            _sl_state['zoom'] = 'body' if s['sl_solo'] else None   # la cámara va al cuerpo (_SlPreviewHandler)
            solo = inputs.addBoolValueInput('sl_solo', tr('Ver solo este cuerpo'), True, '', s['sl_solo'])
            solo.tooltip = tr('Mientras el diálogo está abierto, oculta todo lo demás. Al cerrarlo vuelve a verse.')
            plate = inputs.addBoolValueInput('sl_plate', tr('Incluir en la placa'), True, '', False)
            plate.tooltip = tr('Este cuerpo va en la placa. Lo elegido para cada cuerpo se guarda en el diseño.')
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
            grp = inputs.addGroupCommandInput('grp_general', tr('Opciones generales'))
            grp.isExpanded = False
            grp.tooltip = tr('Valen para todos los cuerpos y todos los diseños.')
            gi = grp.children
            col = gi.addBoolValueInput('sl_color', tr('Colores (AMS)'), True, '', s['sl_color'])
            col.tooltip = tr('Pinta cada cara con el filamento de su color, según los aspectos de Fusion. Cada color '
                             'distinto va a un filamento: el del primer cuerpo es el 1 y los demás, por orden de '
                             'aparición. En el laminador, carga cada color en su número.')
            dd = gi.addDropDownCommandInput('sl_mesh', tr('Malla del STL'),
                                                adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label, _, _ in SL_MESH:
                dd.listItems.add(tr(label), key == s['sl_mesh'])
            dd.tooltip = tr('Separación máxima entre los triángulos y la superficie real. Alta basta para imprimir; '
                            'Muy alta es la de Orca y Bambu Studio al importar un STEP, pero da muchos más triángulos '
                            'y slicer-paint tarda más.')
            dd = gi.addDropDownCommandInput('sl_open', tr('Abrir en'), adsk.core.DropDownStyles.TextListDropDownStyle)
            for key, label in OPEN_IN:
                dd.listItems.add(tr(label), key == s['sl_open'])
            btn = inputs.addBoolValueInput('sl_reset', tr('Restablecer'), False, '', False)
            btn.text = tr('Restablecer')
            btn.tooltip = tr('Borra lo elegido en todos los cuerpos de este diseño (cama, placa, costura y soportes) y '
                             'vuelve las opciones a sus valores por defecto.')
            inputs.addTextBoxCommandInput('sl_info', tr('Resultado'), '', 9, True).isFullWidth = True
            current = _sl_state['current']
            if current is not None:
                _sl_cfg_show(inputs, _sl_state['cfgs'].get(current) or _sl_empty(s['sl_bed']), False)
                _sl_marks(inputs)
            _sl_update_visibility(inputs)

            for ev, h in ((cmd.executePreview, _SlPreviewHandler()), (cmd.inputChanged, _SlChangedHandler()),
                          (cmd.execute, _SlExecuteHandler()), (cmd.preSelect, _SlPreSelectHandler()),
                          (cmd.activate, _SlActivateHandler()), (cmd.destroy, _SlDestroyHandler())):
                ev.add(h)
                _handlers.append(h)
        except Exception:
            _ui.messageBox(tr('Enviar al laminador: error') + '\n' + traceback.format_exc())


class _SlActivateHandler(adsk.core.CommandEventHandler):
    """Al abrir el diálogo, pide poner las selecciones guardadas del cuerpo que se ve (_SlShowHandler)."""
    def notify(self, args):
        if not _sl_state.get('shown'):
            _sl_state['shown'] = True
            _app.fireCustomEvent(SL_SHOW_EVENT)


class _SlShowHandler(adsk.core.CustomEventHandler):
    """Pone las selecciones guardadas del cuerpo que se ve. Va en un evento aparte porque, en commandCreated o en
    activate, Fusion todavía está montando el diálogo y copia lo seleccionado en otros campos."""
    def notify(self, args):
        try:
            cmd, current = _sl_state.get('cmd'), _sl_state.get('current')
            design = adsk.fusion.Design.cast(_app.activeProduct)
            if cmd and cmd.isValid and design and not _sl_state.get('touched'):
                # se vuelve a leer: si este diálogo se abrió con Voladizos FDM abierto, Voladizos guarda sus caras
                # (execute) después de que este haya leído el diseño en commandCreated
                _sl_state['cfgs'] = _sl_load(design, _sl_state.get('bodies', []))
                _sl_marks(cmd.commandInputs)
            cfg = _sl_state.get('cfgs', {}).get(current)
            if cmd and cmd.isValid and cfg:
                _sl_cfg_show(cmd.commandInputs, cfg)
                cmd.doExecutePreview()   # las vistas previas de cada selección se saltan (_SlPreviewHandler)
        except Exception:
            _ui.messageBox(tr('Enviar al laminador: error') + '\n' + traceback.format_exc())


class _SlPreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        # Al rellenar los campos, Fusion pide una vista previa por cada addSelection y en el momento: con las 68
        # caras de la base eran 69 vistas previas, cada una más lenta (dos minutos). Se pinta una vez al acabar.
        if _sl_state.get('loading'):
            return
        inputs = args.command.commandInputs
        body = _sl_body(inputs)
        # Fusion deshace la vista previa anterior antes de llamar aquí, también lo apagado (incluso lo apagado fuera
        # de la vista previa, medido): se apaga lo primero, antes de pintar, que es lo lento, para que no se vea todo
        # mientras tanto
        if body and inputs.itemById('sl_solo').value:
            try:
                _sl_isolate(adsk.fusion.Design.cast(_app.activeProduct), [body])
            except Exception:
                pass   # verlo todo no impide trabajar
        _sl_draw(inputs)
        # sin esto, al volver a marcar la casilla el navegador ya lo tiene apagado pero la vista no cambia
        _app.activeViewport.refresh()
        zoom = _sl_state.pop('zoom', None)
        if zoom:
            try:
                _sl_state.setdefault('camera', _app.activeViewport.camera)   # la de antes del diálogo
                if zoom == 'all':
                    _app.activeViewport.fit()   # ya se ve todo: que quepa
                elif body:
                    _sl_zoom([body])
            except Exception:
                pass


class _SlChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        if args.input.id == 'sl_info':
            return
        if _sl_state.get('loading'):
            return
        inputs = args.firingEvent.sender.commandInputs
        if args.input.id == 'sl_reset':
            _sl_ask_reset()
            return
        try:
            if args.input.id == 'sl_body':
                # lo del cuerpo anterior sigue en los campos: se aparta y se ponen los del nuevo
                prev, new = _sl_state.get('current'), _sl_index(inputs)
                if prev is not None and prev != new:
                    _sl_state['cfgs'][prev] = _sl_cfg_read(inputs)
                    _sl_state['touched'].add(prev)
                _sl_state['current'] = new
                if new is not None and new != prev:
                    _sl_state['zoom'] = 'body'
                    _sl_cfg_show(inputs, _sl_state['cfgs'].get(new) or _sl_empty(_load_settings()['sl_bed']))
            elif args.input.id == 'sl_solo':
                _sl_state['zoom'] = 'body' if args.input.value else 'all'
            elif args.input.id == 'sl_what' and _choice(inputs, 'sl_what', SL_WHAT) == 'plate':
                if not _sl_plate(inputs):
                    inputs.itemById('sl_plate').value = True   # al pasar a placa, empieza por el cuerpo que se ve
            _sl_marks(inputs)
        except Exception:
            _ui.messageBox(tr('Enviar al laminador: error') + '\n' + traceback.format_exc())
        _sl_update_visibility(inputs)
        if args.input.id in ['sl_face', 'sl_bed', 'sl_plate'] + ROLE_KEYS:
            _sl_state['dirty'] = True
        if _sl_state.get('dirty'):
            # Cerrar guarda: lo que se escribe en el diseño con el diálogo abierto (o en destroy) Fusion lo deshace
            # al cerrarlo, y ejecutar el comando sin cerrarlo falla con "reentrancy" si hay algo seleccionado. Se
            # aparta una copia y se escribe cuando el diálogo ya se ha cerrado (_SlDestroyHandler, _SlSaveHandler)
            try:
                _sl_state['last'] = _sl_snapshot(inputs)
            except Exception:
                pass
        if args.input.id == 'sl_bed' and _choice(inputs, 'sl_bed', BEDS) == 'face':
            inputs.itemById('sl_face').hasFocus = True


def _sl_ask_reset():
    """Pide confirmación y restablece desde un evento aparte: con el diálogo abierto, lo que se borra del diseño
    Fusion lo repone al cerrarlo."""
    answer = _ui.messageBox(
        tr('¿Borrar lo elegido en todos los cuerpos de este diseño (cama, placa, costura y soportes) y volver las '
           'opciones a sus valores por defecto?\n\nEl diálogo se cierra y se vuelve a abrir vacío.'),
        tr('Restablecer'), adsk.core.MessageBoxButtonTypes.YesNoButtonType,
        adsk.core.MessageBoxIconTypes.QuestionIconType)
    if answer == adsk.core.DialogResults.DialogYes:
        import threading
        _sl_state['resets'] = 0
        _sl_state['no_store'] = True   # al cerrarse para restablecer, no se guarda lo que había
        threading.Timer(0.1, lambda: _app.fireCustomEvent(SL_RESET_EVENT)).start()


def _sl_reset(design):
    """Borra del diseño lo elegido para Enviar al laminador y vuelve las opciones a sus valores por defecto.
    Devuelve cuántas marcas ha borrado."""
    gone = 0
    for name in (ATTR_ROLE, ATTR_BODY):
        for a in list(design.findAttributes(ATTR_GROUP, name)):
            if a.isValid:
                a.deleteMe()
                gone += 1
    refs = _ref_read(design)
    gone += sum(1 + len(r.get('roles', [])) for r in refs.values())
    _ref_write(design, {})
    _save_settings(_sl_defaults())
    return gone


def _sl_snapshot(inputs):
    """Copia de lo elegido en el diálogo para cada cuerpo tocado, con entityToken en vez de objetos, para escribirla
    en el diseño cuando el diálogo ya no esté (_sl_write_snapshot)."""
    cfgs = dict(_sl_state['cfgs'])
    current = _sl_state.get('current')
    touched = set(_sl_state['touched'])
    if current is not None:
        cfgs[current] = _sl_cfg_read(inputs)
        touched.add(current)

    def tokens(ents):
        return [e.entityToken for e in ents if e and e.isValid]
    bodies = []
    for i in sorted(touched):
        cfg = cfgs[i]
        frozen = {'bed': cfg['bed'], 'plate': cfg['plate'], 'face': tokens([cfg['face']])}
        for k in ROLE_KEYS:
            frozen[k] = tokens(cfg[k])
        bodies.append((_sl_state['bodies'][i][1].entityToken, frozen))
    return {'bodies': bodies}


def _sl_write_snapshot(design, snap):
    """Escribe en el diseño la copia de _sl_snapshot."""
    def find(token):
        found = design.findEntityByToken(token) if token else []
        return found[0] if found else None
    old_roles = list(design.findAttributes(ATTR_GROUP, ATTR_ROLE))
    for body_token, frozen in snap['bodies']:
        body = find(body_token)
        if not body:
            continue
        cfg = {'bed': frozen['bed'], 'plate': frozen['plate'],
               'face': next((e for e in map(find, frozen['face']) if e), None)}
        for k in ROLE_KEYS:
            cfg[k] = [e for e in map(find, frozen[k]) if e]
        _sl_store_one(design, body, cfg, old_roles)


class _SlSaveHandler(adsk.core.CustomEventHandler):
    """Escribe en el diseño lo elegido, en cuanto el diálogo se ha cerrado con Cerrar."""
    def notify(self, args):
        try:
            if _ui.activeCommand == SL_CMD_ID:   # aún se está cerrando: otra vez en un momento
                _sl_state['save_tries'] = _sl_state.get('save_tries', 0) + 1
                if _sl_state['save_tries'] < 20:
                    import threading
                    threading.Timer(0.2, lambda: _app.fireCustomEvent(SL_SAVE_EVENT)).start()
                return
            snap = _sl_state.pop('to_write', None)
            design = adsk.fusion.Design.cast(_app.activeProduct)
            if snap and design:
                _sl_write_snapshot(design, snap)
                _api_refresh()
        except Exception:
            _ui.messageBox(tr('Enviar al laminador: error') + '\n' + traceback.format_exc())


class _SlResetHandler(adsk.core.CustomEventHandler):
    """Cierra el diálogo, restablece (_sl_reset) y lo vuelve a abrir."""
    def notify(self, args):
        try:
            if _ui.activeCommand == SL_CMD_ID:
                _ui.terminateActiveCommand()
            if _ui.activeCommand == SL_CMD_ID:   # aún se está cerrando: otra vez en un momento
                _sl_state['resets'] = _sl_state.get('resets', 0) + 1
                if _sl_state['resets'] < 20:
                    import threading
                    threading.Timer(0.2, lambda: _app.fireCustomEvent(SL_RESET_EVENT)).start()
                return
            design = adsk.fusion.Design.cast(_app.activeProduct)
            if design:
                _sl_reset(design)
                _api_refresh()
            _ui.commandDefinitions.itemById(SL_CMD_ID).execute()
        except Exception:
            _ui.messageBox(tr('Enviar al laminador: error') + '\n' + traceback.format_exc())


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
            _sl_state.pop('last', None)   # Enviar ya guarda (_sl_send): al cerrarse no hay que escribir nada
            msg = _sl_send(design, _sl_read(inputs), inputs)
            _sl_state['sent'] = msg
            if msg:
                _ui.messageBox(msg, tr('Enviar al laminador'))
        except Exception:
            _ui.messageBox(tr('Enviar al laminador: error') + '\n' + traceback.format_exc())


class _SlDestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            if _sl_state.get('cmd') is not None and args.command != _sl_state['cmd']:
                return   # se ha vuelto a pulsar el botón con el diálogo abierto: el nuevo ya está en marcha
            _clear(SL_GROUP_ID)
            for k in ('cmd', 'html', 'cfgs', 'touched', 'current', 'bodies', 'shown', 'zoom', 'drawn'):
                _sl_state.pop(k, None)
            snap, dirty, no_store = (_sl_state.pop(k, None) for k in ('last', 'dirty', 'no_store'))
            if snap and dirty and not no_store:
                # cerrado con Cerrar (o con otro comando) después de cambiar algo
                _sl_state['to_write'] = snap
                _sl_state['save_tries'] = 0
                _app.fireCustomEvent(SL_SAVE_EVENT)
            camera = _sl_state.pop('camera', None)
            if camera:
                _app.activeViewport.camera = camera   # como ver solo el cuerpo, el acercamiento dura lo que el diálogo
            _app.activeViewport.refresh()
        except Exception:
            pass


def _api_body(design, body):
    """(nombre, cuerpo) de un sólido visible a partir del objeto, de su nombre en la lista del diálogo o de su
    entityToken. Con un cuerpo nativo de un componente que se usa en una ocurrencia, la primera de la lista."""
    bodies = _sl_bodies(design)
    if hasattr(body, 'entityToken'):
        for name, b in bodies:
            if b.entityToken == body.entityToken:
                return name, b
        token = _native_token(body)
        for name, b in bodies:
            if _native_token(b) == token:
                return name, b
        raise ValueError('%s no es un sólido visible.' % body.name)
    for name, b in bodies:
        if body in (name, b.name, b.entityToken):
            return name, b
    raise ValueError('No hay ningún sólido visible llamado %r. Hay: %s' % (body, ', '.join(n for n, _ in bodies)))


def _api_cfg(design, name, body):
    """Lo guardado para un cuerpo (como en el diálogo), o lo de un cuerpo sin nada."""
    return _sl_load(design, [(name, body)]).get(0) or _sl_empty(_load_settings()['sl_bed'])


def _api_store(design, body, cfg):
    _sl_store_one(design, body, cfg, list(design.findAttributes(ATTR_GROUP, ATTR_ROLE)))


def _api_refresh():
    """Vuelve a pintar las marcas si show() de la API las tiene a la vista. Se importa aquí porque api importa este
    módulo."""
    from .api import _api_refresh as refresh
    refresh()
