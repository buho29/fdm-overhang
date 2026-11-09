# Lo que se manda a slicer-paint (en la carpeta slicer-paint/ de este repo): el archivo de pieza, versión 3, y la
# línea de comandos. Sin Fusion, para poder probarlo: las coordenadas llegan en cm (las de Fusion) y salen en mm.
import array
import math
import os
import shutil
import struct
import sys

from . import thickness as T

MM_PER_CM = 10.0
DIGITS = 5   # decimales en mm: 0,01 µm, de sobra para reconocer la malla
ROLES = (('seam', 'enforce'), ('seam', 'block'), ('support', 'enforce'), ('support', 'block'))
OPEN_IN = ('orca', 'bambu', None)
# La instalación de desarrollo: el .venv de slicer-paint/ junto al complemento, si se ejecuta desde el repo.
DEFAULT_EXE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'slicer-paint', '.venv',
                           'Scripts' if os.name == 'nt' else 'bin', 'slicer-paint.exe' if os.name == 'nt' else 'slicer-paint')


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


def safe_name(name, default='pieza'):
    """Nombre sin los caracteres que Windows no admite en un archivo."""
    return ''.join(ch for ch in name if ch not in '\\/:*?"<>|').strip() or default


def plate_paths(target_3mf, names):
    """(archivo de placa, 3mf, [(stl, json) de cada pieza]) junto al 3MF elegido: 'placa.json' y 'placa - Caja.stl'.
    Dos piezas con el mismo nombre, también si solo cambian las mayúsculas, no pisan sus archivos."""
    base = os.path.splitext(target_3mf)[0]
    used, parts = set(), []
    for name in names:
        stem, n = '%s - %s' % (base, safe_name(name)), 1
        while (stem if n == 1 else '%s (%d)' % (stem, n)).lower() in used:
            n += 1
        stem = stem if n == 1 else '%s (%d)' % (stem, n)
        used.add(stem.lower())
        parts.append((stem + '.stl', stem + '.json'))
    return base + '.json', base + '.3mf', parts


def plate(names, parts):
    """Archivo de placa versión 1. Los archivos de cada pieza van en su misma carpeta: rutas relativas."""
    return {'version': 1, 'units': 'mm',
            'parts': [{'stl': os.path.basename(stl), 'fusion': os.path.basename(js), 'name': name}
                      for name, (stl, js) in zip(names, parts)]}


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


def plate_command(exe, plate_path, out_3mf, open_in=None):
    """Línea de comandos de slicer-paint para una placa."""
    argv = [exe, '--plate', plate_path, '-o', out_3mf]
    if open_in:
        argv += ['--open', open_in]
    return argv


def role_value(keys):
    """Valor del atributo que marca una cara o arista con sus papeles, sin repetir y en orden."""
    return ','.join(sorted(set(keys)))


def role_keys(value):
    return [k for k in value.split(',') if k]


def stl_bounds(path):
    """(mínimo, máximo) de los vértices de un STL binario o de texto, en sus unidades."""
    with open(path, 'rb') as f:
        data = f.read()
    pts = []
    n = struct.unpack_from('<I', data, 80)[0] if len(data) >= 84 else -1
    if len(data) == 84 + 50 * n:
        if not n:
            raise ValueError('STL vacío: %s' % path)
        # solo los vértices, seguidos, en un array: min y max van en C, y una malla fina tiene cientos de miles de
        # triángulos
        v = array.array('f', b''.join(data[96 + 50 * t:132 + 50 * t] for t in range(n)))
        if sys.byteorder != 'little':
            v.byteswap()
        return tuple(min(v[i::3]) for i in range(3)), tuple(max(v[i::3]) for i in range(3))
    else:
        for line in data.decode('ascii', 'replace').splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0] == 'vertex':
                pts.append(tuple(float(x) for x in parts[1:]))
    if not pts:
        raise ValueError('STL vacío: %s' % path)
    return tuple(min(p[i] for p in pts) for i in range(3)), tuple(max(p[i] for p in pts) for i in range(3))


def write_stl(path, coords_cm, indices):
    """Escribe una malla en STL binario y en mm: nodos en cm (planos, x y z seguidos) e índices de tres en tres, con
    los triángulos hacia fuera. La normal de cada triángulo sale de sus vértices."""
    n = len(indices) // 3
    data = bytearray(84 + 50 * n)
    struct.pack_into('<I', data, 80, n)
    c = [v * MM_PER_CM for v in coords_cm]
    for t in range(n):
        i, j, k = (3 * v for v in indices[3 * t:3 * t + 3])
        p, q, r = c[i:i + 3], c[j:j + 3], c[k:k + 3]
        u = [q[0] - p[0], q[1] - p[1], q[2] - p[2]]
        w = [r[0] - p[0], r[1] - p[1], r[2] - p[2]]
        nx, ny, nz = u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]
        size = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        struct.pack_into('<12f', data, 84 + 50 * t, nx / size, ny / size, nz / size, *(p + q + r))
    with open(path, 'wb') as f:
        f.write(data)


def bounds_match(stl_box, body_box_cm, tol_mm=0.2):
    """Si la caja del STL (mm) es la del cuerpo (cm, en coordenadas del raíz): si no, las zonas no caerían sobre la
    malla. Lo que se busca es otro origen o cm en vez de mm; la tolerancia es porque la caja del cuerpo puede ser
    algo mayor que la de su malla en las caras curvas."""
    lo, hi = stl_box
    blo, bhi = [[v * MM_PER_CM for v in p] for p in body_box_cm]
    return all(abs(a - b) <= tol_mm for a, b in zip(list(lo) + list(hi), blo + bhi))
