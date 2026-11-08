# Lo que se manda a slicer-paint (https://github.com/buho29/slicer-paint): el archivo de pieza, versión 3, y la
# línea de comandos. Sin Fusion, para poder probarlo: las coordenadas llegan en cm (las de Fusion) y salen en mm.
import math
import os
import shutil
import struct

from . import thickness as T

MM_PER_CM = 10.0
DIGITS = 5   # decimales en mm: 0,01 µm, de sobra para reconocer la malla
ROLES = (('seam', 'enforce'), ('seam', 'block'), ('support', 'enforce'), ('support', 'block'))
OPEN_IN = ('orca', 'bambu', None)
DEFAULT_EXE = r'C:\slicer-paint\.venv\Scripts\slicer-paint.exe'


def mm_point(p):
    return [round(v * MM_PER_CM, DIGITS) for v in p]


def bed_vector(bed, face_normal=None):
    """Normal hacia fuera de la cara que va sobre la cama: 'z' es el plano XY, 'y' el XZ y 'face' una cara plana
    elegida, con face_normal su normal hacia fuera."""
    if bed == 'z':
        return [0.0, 0.0, -1.0]
    if bed == 'y':
        return [0.0, -1.0, 0.0]
    n = math.sqrt(sum(v * v for v in face_normal)) or 1.0
    return [round(v / n, 9) for v in face_normal]


def edge(points_cm):
    """Polilínea de una arista, de puntos en cm."""
    return [mm_point(p) for p in points_cm]


def face(coords_cm, indices, area_cm2):
    """Malla de una cara entera: nodos en cm (planos, x y z seguidos), índices de tres en tres y su área exacta."""
    return {'vertices': [mm_point(coords_cm[i:i + 3]) for i in range(0, len(coords_cm), 3)],
            'triangles': [list(indices[i:i + 3]) for i in range(0, len(indices), 3)],
            'area': round(area_cm2 * MM_PER_CM ** 2, 4)}


def patch(coords_cm, indices, tris):
    """Zona con los triángulos 'tris' de una malla, en el mismo sentido (hacia fuera), sin los nodos que no usan.
    None si no hay ninguno."""
    nodes, verts, out = {}, [], []
    for t in tris:
        tri = []
        for k in indices[3 * t:3 * t + 3]:
            if k not in nodes:
                nodes[k] = len(verts)
                verts.append(mm_point(coords_cm[3 * k:3 * k + 3]))
            tri.append(nodes[k])
        out.append(tri)
    return {'vertices': verts, 'triangles': out} if out else None


def tight_triangles(vals, kinds, limit, margin=0.0):
    """Triángulos con poca holgura delante: en contacto, en interferencia o con menos espacio que limit, con el
    mismo criterio que la medida de Espacio (T.below_limit)."""
    return [t for t, (w, k) in enumerate(zip(vals, kinds))
            if k in (T.CONTACT, T.OVERLAP) or (k == T.GAP and w < T.NO_HIT and T.below_limit(w, limit, margin))]


def selection(edges=(), faces=(), patches=()):
    """Selección del formato, sin las listas vacías. None si no hay nada."""
    out = {k: list(v) for k, v in (('edges', edges), ('faces', faces), ('patches', patches)) if v}
    return out or None


def job(body, bed=None, **roles):
    """Archivo de pieza versión 3. roles: seam_enforce, seam_block, support_enforce, support_block, cada uno una
    selección (selection) o None. Da ValueError si no hay ni cama ni ninguna selección, como slicer-paint."""
    out = {'version': 3, 'units': 'mm', 'body': body}
    if bed is not None:
        out['bed'] = list(bed)
    for kind, role in ROLES:
        chosen = roles.pop('%s_%s' % (kind, role), None)
        if chosen:
            out.setdefault(kind, {})[role] = chosen
    if roles:
        raise TypeError('Papel desconocido: %s' % ', '.join(sorted(roles)))
    if 'bed' not in out and 'seam' not in out and 'support' not in out:
        raise ValueError('Sin cama ni nada elegido')
    return out


def counts(job_dict):
    """{(tipo, papel): (aristas, caras, zonas)} de lo que lleva el archivo de pieza."""
    out = {}
    for kind, role in ROLES:
        chosen = job_dict.get(kind, {}).get(role, {})
        out[(kind, role)] = tuple(len(chosen.get(k, ())) for k in ('edges', 'faces', 'patches'))
    return out


def paths(target_3mf):
    """(stl, json, 3mf) junto al 3MF elegido, con su mismo nombre."""
    base = os.path.splitext(target_3mf)[0]
    return base + '.stl', base + '.json', base + '.3mf'


def find_exe(configured=''):
    """Ruta de slicer-paint: la de settings.json, la del PATH o la de la instalación de desarrollo. None si no está."""
    for cand in (configured, shutil.which('slicer-paint') or '', DEFAULT_EXE):
        if cand and os.path.isfile(cand):
            return cand
    return None


def looks_like_exe(path):
    """Si el archivo que elige el usuario puede ser slicer-paint: existe y se llama slicer-paint (.exe en Windows).
    Para no recordar por error otro programa."""
    name = os.path.basename(path).lower()
    return os.path.isfile(path) and name in ('slicer-paint', 'slicer-paint.exe')


def command(exe, stl, job_path, out_3mf, open_in=None):
    """Línea de comandos de slicer-paint."""
    argv = [exe, stl, '-o', out_3mf, '--fusion', job_path]
    if open_in:
        argv += ['--open', open_in]
    return argv


def stl_bounds(path):
    """(mínimo, máximo) de los vértices de un STL binario o de texto, en sus unidades."""
    with open(path, 'rb') as f:
        data = f.read()
    pts = []
    n = struct.unpack_from('<I', data, 80)[0] if len(data) >= 84 else -1
    if len(data) == 84 + 50 * n:
        for t in range(n):
            v = struct.unpack_from('<12f', data, 84 + 50 * t)
            pts += [v[3:6], v[6:9], v[9:12]]
    else:
        for line in data.decode('ascii', 'replace').splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0] == 'vertex':
                pts.append(tuple(float(x) for x in parts[1:]))
    if not pts:
        raise ValueError('STL vacío: %s' % path)
    return tuple(min(p[i] for p in pts) for i in range(3)), tuple(max(p[i] for p in pts) for i in range(3))


def move_stl(path, m):
    """Lleva un STL binario en mm al raíz con la matriz m de la ocurrencia (16 valores por filas, como
    Matrix3D.asArray, con la traslación en cm). Fusion exporta el cuerpo de una ocurrencia en las coordenadas de su
    componente, y lo demás se manda en las del raíz."""
    with open(path, 'rb') as f:
        data = bytearray(f.read())
    n = struct.unpack_from('<I', data, 80)[0]
    if len(data) != 84 + 50 * n:
        raise ValueError('No es un STL binario: %s' % path)
    r = [m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]]
    t = [m[3] * MM_PER_CM, m[7] * MM_PER_CM, m[11] * MM_PER_CM]

    def rot(x, y, z):
        return r[0] * x + r[1] * y + r[2] * z, r[3] * x + r[4] * y + r[5] * z, r[6] * x + r[7] * y + r[8] * z

    for k in range(n):
        at = 84 + 50 * k
        v = struct.unpack_from('<12f', data, at)
        out = list(rot(*v[0:3]))
        for p in range(3, 12, 3):
            x, y, z = rot(*v[p:p + 3])
            out += [x + t[0], y + t[1], z + t[2]]
        struct.pack_into('<12f', data, at, *out)
    with open(path, 'wb') as f:
        f.write(data)


def bounds_match(stl_box, body_box_cm, tol_mm=0.2):
    """Si la caja del STL (mm) es la del cuerpo (cm, en coordenadas del raíz): si no, las zonas no caerían sobre la
    malla. Lo que se busca es otro origen o cm en vez de mm; la tolerancia es porque la caja del cuerpo puede ser
    algo mayor que la de su malla en las caras curvas."""
    lo, hi = stl_box
    blo, bhi = [[v * MM_PER_CM for v in p] for p in body_box_cm]
    return all(abs(a - b) <= tol_mm for a, b in zip(list(lo) + list(hi), blo + bhi))
