# API sin diálogo de Enviar al laminador: para marcar caras y aristas y enviar al laminador desde un script, sin abrir
# el diálogo. Así lo usa Claude por el MCP de Fusion (execute_code). Escribe los mismos atributos que el diálogo, así
# que lo marcado sale en él al abrirlo y se puede corregir a mano. Argumentos y resultados sencillos (nombres,
# entityToken, dicts) para poder envolverlas después en un servidor MCP. Medidas en mm, en las coordenadas del raíz.
# Desde execute_code:
#   m = sys.modules['overhang.ui.api']   (el módulo de FDMOverhang.py también las tiene)
#   m.mark(m.edges_where('Caja', along='up', box=((None, 30, None), None)), 'seam_on'); m.show()
#   m.send('Caja', r'C:\ruta\caja.3mf'); m.send_status()
# Papeles: 'seam_on', 'seam_off', 'support_on', 'support_off' (costura forzada o prohibida, soportes forzados o
# bloqueados). La cara de la cama y la placa van con set_body.

import os
import traceback

import adsk.core
import adsk.fusion

from .. import analysis as A
from .. import slicer as S
from .. import pick as P
from .common import (API_GROUP_ID, API_MIN_OVERHANG, API_SEND_EVENT, QUALITIES, _app, _clear, _default_bed, _foreign,
                     _load_settings, _mesh, _meshes, _native_token, _ui)
from .slicer_cmd import (ATTR_GROUP, ATTR_ROLE, OPEN_IN, ROLE_KEYS, SL_MESH, _api_body, _api_cfg, _api_store,
                         _ref_entities, _ref_key, _ref_read, _sl_bed, _sl_bodies, _sl_collect, _sl_empty, _sl_jobs,
                         _sl_load, _sl_paint, _sl_reset, _sl_rgb, _sl_state, _sl_write_run)
from .overhang_cmd import _analyse, _face_overhang, _state


_api_state = {'shown': False}   # si show() tiene pintadas las marcas, y de qué cuerpo (None: todos)


def _api_design():
    design = adsk.fusion.Design.cast(_app.activeProduct)
    if not design:
        raise RuntimeError('Abre un diseño (espacio de trabajo DISEÑO).')
    return design


def _api_writable():
    """El diseño, si se puede cambiar: lo que se crea o se borra con un comando abierto, Fusion lo deshace al cerrarlo
    o al reiniciarlo."""
    design = _api_design()
    cmd = _ui.activeCommand
    if cmd and cmd != 'SelectCommand':
        raise RuntimeError('Hay un comando abierto (%s): ciérralo antes.' % cmd)
    return design


def _api_entity(design, ent):
    """Cara o arista de un objeto o de su entityToken."""
    if isinstance(ent, str):
        found = design.findEntityByToken(ent)
        if not found:
            raise ValueError('No encuentro nada con el token %s…' % ent[:24])
        ent = found[0]
    face, edge = adsk.fusion.BRepFace.cast(ent), adsk.fusion.BRepEdge.cast(ent)
    if not (face or edge):
        raise ValueError('Solo se marcan caras y aristas (llegó %s).' % getattr(ent, 'objectType', ent))
    return face or edge


def _api_list(entities):
    return list(entities) if isinstance(entities, (list, tuple)) else [entities]


def _api_by_body(design, entities):
    """[(nombre, cuerpo, [caras y aristas en el contexto de ese cuerpo])], agrupadas por cuerpo y en orden."""
    out = {}
    for ent in _api_list(entities):
        e = _api_entity(design, ent)
        native = e.nativeObject or e
        name, body = _api_body(design, e.body)
        occ = body.assemblyContext
        proxy = native.createForAssemblyContext(occ) if occ else native
        out.setdefault(body.entityToken, (name, body, []))[2].append(proxy)
    return list(out.values())


def _api_refresh():
    """Vuelve a pintar las marcas si show() las tiene a la vista."""
    if _api_state['shown'] is not False:
        show(_api_state['shown'])


def _api_up(cfg, body):
    """Hacia arriba en la impresora, según la cama del cuerpo."""
    bed = _sl_bed(cfg, body)
    if isinstance(bed, str):
        raise ValueError(bed)
    return tuple(-v for v in bed)


def _api_enum(enum, value, suffix):
    """'plane', 'cylinder', 'line', 'circle'… de un valor de SurfaceTypes o Curve3DTypes."""
    for n in dir(enum):
        if n.endswith(suffix) and getattr(enum, n) == value:
            return n[:-len(suffix)].replace('3D', '').lower()
    return str(value)


def _api_mm(p):
    return [round(v * S.MM_PER_CM, 3) for v in p]


def _api_roles_of(entity):
    body = entity.body
    if body.assemblyContext and _foreign(body):
        design = _api_design()
        saved = _ref_read(design).get(_ref_key(body)) or {}
        token = _native_token(entity)
        keys = next((k for e, k in _ref_entities(design, body, saved) if _native_token(e) == token), [])
        return [P.role_name(k) for k in keys]
    a = (entity.nativeObject or entity).attributes.itemByName(ATTR_GROUP, ATTR_ROLE)
    return [P.role_name(k) for k in S.role_keys(a.value)] if a else []


def _api_line_dir(edge):
    """Dirección de una arista recta, o None si no lo es."""
    g = edge.geometry
    if g.curveType != adsk.core.Curve3DTypes.Line3DCurveType:
        return None
    a, b = g.startPoint.asArray(), g.endPoint.asArray()
    return [y - x for x, y in zip(a, b)]


def _api_describe(e, cache):
    bb = e.boundingBox
    d = {'token': e.entityToken, 'roles': _api_roles_of(e),
         'box_mm': [_api_mm(bb.minPoint.asArray()), _api_mm(bb.maxPoint.asArray())]}
    face = adsk.fusion.BRepFace.cast(e)
    if face:
        p = face.pointOnFace
        _, n = face.evaluator.getNormalAtPoint(p)   # en un sólido, hacia fuera
        d.update(kind='face', surface=_api_enum(adsk.core.SurfaceTypes, face.geometry.surfaceType, 'SurfaceType'),
                 area_mm2=round(face.area * S.MM_PER_CM ** 2, 3), point_mm=_api_mm(p.asArray()),
                 normal=[round(v, 4) for v in P.unit(n.asArray())], color=_sl_rgb(face, cache))
    else:
        edge = adsk.fusion.BRepEdge.cast(e)
        ev = edge.evaluator
        _, t0, t1 = ev.getParameterExtents()
        _, a = ev.getPointAtParameter(t0)
        _, b = ev.getPointAtParameter(t1)
        d.update(kind='edge', curve=_api_enum(adsk.core.Curve3DTypes, edge.geometry.curveType, 'CurveType'),
                 length_mm=round(edge.length * S.MM_PER_CM, 3), start_mm=_api_mm(a.asArray()),
                 end_mm=_api_mm(b.asArray()))
        v = _api_line_dir(edge)
        if v:
            d['direction'] = [round(x, 4) for x in P.unit(v)]
    return d


def describe(entities):
    """[{token, kind ('face'/'edge'), roles, box_mm, …}] de caras o aristas (objetos o entityToken). Caras: surface,
    area_mm2, point_mm (un punto de la cara), normal (hacia fuera en ese punto) y color. Aristas: curve, length_mm,
    start_mm, end_mm y, si es recta, direction."""
    design = _api_design()
    cache = {}
    return [_api_describe(_api_entity(design, e), cache) for e in _api_list(entities)]


def _api_summary(name, body, cfg, detail=False):
    face = cfg['face'] if cfg['bed'] == 'face' and cfg['face'] and cfg['face'].isValid else None
    roles = {}
    cache = {}
    for api, key in P.ROLES:
        ents = [e for e in cfg[key] if e.isValid]
        if not ents:
            continue
        if detail:
            roles[api] = [_api_describe(e, cache) for e in ents]
        else:
            n_faces = sum(1 for e in ents if adsk.fusion.BRepFace.cast(e))
            roles[api] = {'faces': n_faces, 'edges': len(ents) - n_faces}
    return {'body': name, 'token': body.entityToken, 'bed': cfg['bed'], 'bed_face': face.entityToken if face else None,
            'plate': cfg['plate'], 'roles': roles}


def marks(body=None, detail=False):
    """Lo marcado en cada sólido visible (o solo en 'body'): cama, si va en la placa y, por papel, cuántas caras y
    aristas; con detail, la descripción de cada una (describe)."""
    design = _api_design()
    if body is not None:
        name, b = _api_body(design, body)
        return [_api_summary(name, b, _api_cfg(design, name, b), detail)]
    bodies = _sl_bodies(design)
    cfgs = _sl_load(design, bodies)
    default = _load_settings()['sl_bed']
    return [_api_summary(name, b, cfgs.get(i) or _sl_empty(default), detail) for i, (name, b) in enumerate(bodies)]


def mark(entities, role):
    """Añade caras o aristas (objetos o entityToken, de uno o varios cuerpos) a un papel: 'seam_on', 'seam_off',
    'support_on' o 'support_off'. Una cara puede tener varios papeles. Devuelve marks() de los cuerpos tocados."""
    if role == 'bed':
        ents = _api_list(entities)
        if len(ents) != 1:
            raise ValueError('La cama es una sola cara.')
        return set_body(_api_entity(_api_design(), ents[0]).body, bed=ents[0])
    key = P.role_key(role)
    design = _api_writable()
    out = []
    for name, body, ents in _api_by_body(design, entities):
        cfg = _api_cfg(design, name, body)
        have = {_native_token(e) for e in cfg[key] if e.isValid}
        for e in ents:
            if _native_token(e) not in have:
                cfg[key].append(e)
                have.add(_native_token(e))
        _api_store(design, body, cfg)
        out.append(_api_summary(name, body, _api_cfg(design, name, body)))
    _api_refresh()
    return out


def unmark(entities, role=None):
    """Quita caras o aristas de un papel, o de todos (y de la cama) con role=None. Devuelve marks() de los cuerpos
    tocados."""
    keys = [P.role_key(role)] if role not in (None, 'bed') else []
    if role is None:
        keys = list(ROLE_KEYS)
    design = _api_writable()
    out = []
    for name, body, ents in _api_by_body(design, entities):
        gone = {_native_token(e) for e in ents}
        cfg = _api_cfg(design, name, body)
        for key in keys:
            cfg[key] = [e for e in cfg[key] if e.isValid and _native_token(e) not in gone]
        if role in (None, 'bed') and cfg['face'] and cfg['face'].isValid and _native_token(cfg['face']) in gone:
            cfg['face'] = None
            if cfg['bed'] == 'face':
                cfg['bed'] = _default_bed()
        _api_store(design, body, cfg)
        out.append(_api_summary(name, body, _api_cfg(design, name, body)))
    _api_refresh()
    return out


def clear_marks(body=None):
    """Quita los papeles de un cuerpo, o de todos los sólidos visibles. La cama y la placa se quedan."""
    design = _api_writable()
    bodies = [_api_body(design, body)] if body is not None else _sl_bodies(design)
    cfgs = _sl_load(design, bodies)
    for i, (name, b) in enumerate(bodies):
        if i in cfgs:
            cfg = cfgs[i]
            for key in ROLE_KEYS:
                cfg[key] = []
            _api_store(design, b, cfg)
    _api_refresh()
    return marks(body)


def set_body(body, bed=None, plate=None):
    """Cama del cuerpo ('z': plano XY, 'y': plano XZ, o una cara plana suya, objeto o entityToken) y si va en la
    placa (plate=True/False). Lo que se deja en None no cambia. Devuelve marks() del cuerpo."""
    design = _api_writable()
    name, b = _api_body(design, body)
    cfg = _api_cfg(design, name, b)
    if bed in ('z', 'y'):
        cfg['bed'], cfg['face'] = bed, None
    elif bed is not None:
        face = adsk.fusion.BRepFace.cast(_api_entity(design, bed))
        if not face or face.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
            raise ValueError("La cama tiene que ser 'z', 'y' o una cara plana.")
        [(_, fb, [f])] = _api_by_body(design, [face])
        if fb.entityToken != b.entityToken:
            raise ValueError('La cara de la cama tiene que ser de %s.' % name)
        cfg['bed'], cfg['face'] = 'face', f
    if plate is not None:
        cfg['plate'] = bool(plate)
    _api_store(design, b, cfg)
    _api_refresh()
    return [_api_summary(name, b, _api_cfg(design, name, b))]


def _api_bed_level(body, up):
    """Altura de la cama (lo más bajo del cuerpo según up), en cm."""
    key = (body.entityToken, 'normal')
    had = key in _meshes
    try:
        return A.lowest(_mesh(body, 'normal')[0], up)
    finally:
        if not had:
            _meshes.pop(key, None)


def _api_has_role(entity, role):
    return role is None or (role == 'none' and not _api_roles_of(entity)) or role in _api_roles_of(entity)


def faces_where(body, facing=None, tol_deg=5.0, planar=None, overhang=None, angle=None, color=None, box=None,
                min_area=None, role=None):
    """Caras del cuerpo que cumplen todo lo que se pide (lo que va en None no filtra):
    - facing: 'up', 'down' (según la cama del cuerpo) o un vector; solo caras planas con la normal hacia ahí, con
      tol_deg grados como mucho.
    - planar: True/False.
    - overhang: True para las que tienen voladizo (al menos 1 mm² con menos de 'angle' grados desde la horizontal,
      el del diálogo de Voladizos si no se da), False para las que no.
    - color: '#RRGGBB' del aspecto que se ve en la cara.
    - box: ((xmin, ymin, zmin), (xmax, ymax, zmax)) en mm, None sin límite: la cara entera dentro.
    - min_area: mm².
    - role: un papel ('seam_on'…, 'bed') o 'none' para las que no tienen ninguno."""
    design = _api_design()
    name, b = _api_body(design, body)
    cfg = _api_cfg(design, name, b)
    up = _api_up(cfg, b)
    d = P.direction(facing, up) if facing is not None else None
    angle = _load_settings()['angle'] if angle is None else angle
    bed = _api_bed_level(b, up) if overhang is not None else None
    cache, out = {}, []
    for face in b.faces:
        is_plane = face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType
        if planar is not None and is_plane != bool(planar):
            continue
        if min_area is not None and face.area * S.MM_PER_CM ** 2 < min_area:
            continue
        if box is not None:
            bb = face.boundingBox
            if not P.in_box(bb.minPoint.asArray(), bb.maxPoint.asArray(), box):
                continue
        if color is not None and not P.same_color(_sl_rgb(face, cache), color):
            continue
        if d is not None:
            if not is_plane:
                continue
            _, n = face.evaluator.getNormalAtPoint(face.pointOnFace)
            if not P.facing(n.asArray(), d, tol_deg):
                continue
        if not _api_has_role(face, role):
            continue
        if overhang is not None:
            area = _face_overhang(face, b, up, bed, angle)
            if (area >= API_MIN_OVERHANG) != bool(overhang):
                continue
        out.append(face)
    return out


def edges_where(body, along=None, tol_deg=5.0, curve=None, box=None, min_length=None, faces=None, role=None):
    """Aristas del cuerpo que cumplen todo lo que se pide (lo que va en None no filtra):
    - along: 'up' (vertical respecto a la cama del cuerpo) o un vector; solo aristas rectas en esa dirección, en
      cualquier sentido, con tol_deg grados como mucho.
    - curve: 'line', 'arc', 'circle', 'ellipse', 'ellipticalarc' o 'nurbscurve'.
    - box: ((xmin, ymin, zmin), (xmax, ymax, zmax)) en mm, None sin límite: la arista entera dentro.
    - min_length: mm.
    - faces: solo las aristas de estas caras (objetos o entityToken).
    - role: un papel ('seam_on'…) o 'none' para las que no tienen ninguno."""
    design = _api_design()
    name, b = _api_body(design, body)
    cfg = _api_cfg(design, name, b)
    d = P.direction(along, _api_up(cfg, b)) if along is not None else None
    if faces is not None:
        allowed = set()
        for f in _api_list(faces):
            face = adsk.fusion.BRepFace.cast(_api_entity(design, f))
            if face:
                allowed |= {_native_token(e) for e in face.edges}
    out = []
    for edge in b.edges:
        if faces is not None and _native_token(edge) not in allowed:
            continue
        if curve is not None and _api_enum(adsk.core.Curve3DTypes, edge.geometry.curveType, 'CurveType') != curve:
            continue
        if min_length is not None and edge.length * S.MM_PER_CM < min_length:
            continue
        if box is not None:
            bb = edge.boundingBox
            if not P.in_box(bb.minPoint.asArray(), bb.maxPoint.asArray(), box):
                continue
        if d is not None:
            v = _api_line_dir(edge)
            if not v or not P.parallel(v, d, tol_deg):
                continue
        if not _api_has_role(edge, role):
            continue
        out.append(edge)
    return out


def show(body=None):
    """Pinta lo marcado (de un cuerpo o de todos) con los colores del diálogo, fuera de cualquier comando, hasta
    hide() o hasta abrir el diálogo. Mientras se vea, mark y compañía lo repintan. Devuelve los avisos, si hay."""
    design = _api_design()
    _clear(API_GROUP_ID, design)
    _api_state['shown'] = body
    bodies = [_api_body(design, body)] if body is not None else _sl_bodies(design)
    cfgs = _sl_load(design, bodies)
    notes = []
    for i, (name, b) in enumerate(bodies):
        if i not in cfgs:
            continue
        job, html, layers, lines = _sl_collect(b, cfgs[i])
        if job is None:
            notes.append('%s: %s' % (name, html))
        _sl_paint(design, layers, lines, API_GROUP_ID)
    _app.activeViewport.refresh()
    return notes


def hide():
    """Quita lo que pintó show()."""
    _api_state['shown'] = False
    _clear(API_GROUP_ID)
    _app.activeViewport.refresh()


def analyze(body, angle=None, quality='normal', bridge_max=None):
    """Voladizos del cuerpo con su cama, como el diálogo de Voladizos: áreas en mm², la peor inclinación en grados
    y la luz de los puentes en mm. angle y bridge_max (mm), los del diálogo si no se dan."""
    design = _api_design()
    name, b = _api_body(design, body)
    cfg = _api_cfg(design, name, b)
    s = _load_settings()
    if quality not in [q[0] for q in QUALITIES]:
        raise ValueError('Calidad desconocida: %r. Valen: %s' % (quality, ', '.join(q[0] for q in QUALITIES)))
    st = {'bodies': 'pick', 'bed': cfg['bed'], 'own_bed': False, 'angle': s['angle'] if angle is None else angle,
          'gradient': True, 'quality': quality, 'bridge': True,
          'bridge_max': s['bridge_max'] if bridge_max is None else bridge_max}
    key = (b.entityToken, quality)
    had = key in _meshes
    _state.pop('result', None)
    try:
        html, _ = _analyse(design, st, [b], cfg['face'] if cfg['bed'] == 'face' else None)
    finally:
        if not had:
            _meshes.pop(key, None)
    r = _state.get('result')
    if not r:
        raise ValueError(html)
    mm = lambda v, k: None if v is None else round(v * k, 2)   # noqa: E731
    return {'body': name, 'bed': cfg['bed'], 'angle': st['angle'], 'total_mm2': mm(r['total'], 100),
            'overhang_mm2': mm(r['overhang'], 100), 'worst_deg': mm(r['worst'], 1), 'bridge_mm2': mm(r['bridge'], 100),
            'longest_bridge_mm': mm(r['span'], 10), 'too_long_bridge_mm': mm(r['long_span'], 10),
            'bed_mm2': mm(r['bed'], 100)}


def send(bodies=None, target=None, mesh=None, open_in=None, color=None):
    """Exporta y lanza slicer-paint sin preguntar nada. bodies: un cuerpo (su 3MF), una lista (una placa) o None
    (una placa con los marcados con set_body(..., plate=True)). target: ruta del 3MF; el STL, el JSON y el log van a
    su lado. mesh ('low', 'medium', 'high', 'ultra'), open_in ('orca', 'bambu', 'none') y color (AMS): los del
    diálogo si no se dan. Vuelve enseguida con {'queued', 'out', 'bodies', 'plate'}: la exportación
    va en un evento aparte y slicer-paint después; send_status() dice cómo va y cuándo acaba."""
    design = _api_design()
    if not target:
        raise ValueError('Falta target: la ruta del 3MF.')
    target = os.path.abspath(target)
    if not target.lower().endswith('.3mf'):
        target += '.3mf'
    if not os.path.isdir(os.path.dirname(target)):
        raise ValueError('No existe la carpeta %s.' % os.path.dirname(target))
    s = _load_settings()
    mesh = s['sl_mesh'] if mesh is None else mesh
    if mesh not in [q[0] for q in SL_MESH]:
        raise ValueError('Malla desconocida: %r. Valen: %s' % (mesh, ', '.join(q[0] for q in SL_MESH)))
    open_in = s['sl_open'] if open_in is None else open_in
    if open_in not in [k for k, _ in OPEN_IN]:
        raise ValueError('open_in desconocido: %r. Valen: %s' % (open_in, ', '.join(k for k, _ in OPEN_IN)))
    color = s['sl_color'] if color is None else bool(color)
    if bodies is None:
        listed = _sl_bodies(design)
        cfgs = _sl_load(design, listed)
        items = [(n, b, cfgs[i]) for i, (n, b) in enumerate(listed) if i in cfgs and cfgs[i]['plate']]
        if not items:
            raise ValueError('Ningún cuerpo va en la placa: set_body(cuerpo, plate=True) o pásalos en bodies.')
        plate = True
    else:
        plate = isinstance(bodies, (list, tuple))
        items = []
        for x in _api_list(bodies):
            name, b = _api_body(design, x)
            items.append((name, b, _api_cfg(design, name, b)))
    if _sl_state.get('done', {}).get('running'):
        raise RuntimeError('Hay otro envío en marcha: espera a que send_status() diga que ha acabado.')
    import threading
    names = [n for n, _, _ in items]
    out = S.plate_paths(target, names)[1] if plate else S.paths(target)[2]
    _api_state['pending'] = (items, target, plate, mesh, None if open_in == 'none' else open_in, color,
                             S.find_exe(s['slicer_paint']))
    _sl_state['done'] = {'running': True, 'stage': 'export', 'out': out}
    # disparado desde otro hilo: llamado directamente, el evento llega tarde
    threading.Timer(0.1, lambda: _app.fireCustomEvent(API_SEND_EVENT)).start()
    return {'queued': True, 'out': out, 'bodies': names, 'plate': plate}


class _ApiSendHandler(adsk.core.CustomEventHandler):
    """Hace el trabajo de send(): mallar las caras elegidas, exportar los STL y lanzar slicer-paint."""
    def notify(self, args):
        p = _api_state.pop('pending', None)
        if not p:
            return
        items, target, plate, mesh, open_in, color, exe = p
        try:
            jobs = _sl_jobs(items, color, plate)
            if isinstance(jobs, str):
                _sl_state['done'] = {'running': False, 'ok': False, 'message': jobs}
                return
            msg, info = _sl_write_run(items, jobs, target, plate, mesh, open_in, exe, quiet=True)
            if not info['running']:   # sin slicer-paint, o un error al exportar
                _sl_state['done'] = dict(info, ok=info['command'] is not None, message=msg)
        except Exception:
            _sl_state['done'] = {'running': False, 'ok': False, 'message': traceback.format_exc()}


def reset():
    """Como el botón Restablecer del diálogo: borra lo elegido en todos los cuerpos del diseño (cama, placa, costura y
    soportes) y vuelve las opciones del diálogo a sus valores por defecto. Devuelve cuántas marcas ha borrado."""
    gone = _sl_reset(_api_writable())
    _api_refresh()
    return gone


def send_status():
    """Cómo va el último envío: {'running': True, 'stage': 'export'} mientras Fusion exporta, {'running': True, …}
    mientras slicer-paint trabaja; al acabar, 'ok', 'out', 'message' (si no se lanzó slicer-paint) o 'code' y, si
    falla, el final del log en 'log_tail'."""
    r = _sl_state.get('done')
    if not r:
        return {'running': False, 'message': 'Nada enviado todavía.'}
    out = dict(r, running=bool(r.get('running')))
    if not out['running'] and 'ok' not in out:
        out['ok'] = r.get('code') == 0
        if not out['ok'] and r.get('log'):
            try:
                with open(r['log'], encoding='utf-8', errors='replace') as f:
                    out['log_tail'] = f.read()[-1500:]
            except (OSError, KeyError):
                pass
    return out
