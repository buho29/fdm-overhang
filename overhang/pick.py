# Ayudas puras de la API sin diálogo de "Enviar al laminador" (funciones públicas al final de FDMOverhang.py): los
# nombres de los papeles y los filtros geométricos para elegir caras y aristas. Sin Fusion, para poder probarlas.
import math

# Nombre en la API -> campo del diálogo (el mismo valor que se guarda en el atributo de la cara o arista).
ROLES = (('seam_on', 'sl_seam_on'), ('seam_off', 'sl_seam_off'),
         ('support_on', 'sl_sup_on'), ('support_off', 'sl_sup_off'))
BED_ROLE = ('bed', 'sl_face')   # la cara que va sobre la cama: no es un papel que se pinte, va en la cama del cuerpo
MM_PER_CM = 10.0


def role_key(name):
    """Campo del diálogo de un papel de la API ('seam_on'…). También acepta el propio campo. ValueError si no existe."""
    for api, key in ROLES:
        if name in (api, key):
            return key
    raise ValueError('Papel desconocido: %r. Valen: %s' % (name, ', '.join(api for api, _ in ROLES)))


def role_name(key):
    """Nombre en la API de un campo guardado en un atributo, o el propio campo si no es ninguno."""
    for api, k in ROLES + (BED_ROLE,):
        if key == k:
            return api
    return key


def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    if n == 0:
        raise ValueError('Vector nulo')
    return tuple(x / n for x in v)


def direction(d, up):
    """Vector unitario de una dirección: 'up' y 'down' son los de la cama del cuerpo (up), o un vector (x, y, z)."""
    if d == 'up':
        return unit(up)
    if d == 'down':
        return unit([-x for x in up])
    if isinstance(d, str):
        raise ValueError("Dirección desconocida: %r. Vale 'up', 'down' o un vector (x, y, z)" % d)
    return unit(d)


def angle(a, b):
    """Ángulo en grados entre dos vectores."""
    a, b = unit(a), unit(b)
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))))


def facing(n, d, tol_deg):
    """Si la normal n apunta hacia d con tol_deg grados como mucho."""
    return angle(n, d) <= tol_deg


def parallel(v, d, tol_deg):
    """Si la recta de dirección v va a lo largo de d, en cualquier sentido, con tol_deg grados como mucho."""
    a = angle(v, d)
    return min(a, 180.0 - a) <= tol_deg


def in_box(lo_cm, hi_cm, box_mm, tol_mm=1e-3):
    """Si la caja (lo_cm, hi_cm), en cm, cabe entera en box_mm = ((xmin, ymin, zmin), (xmax, ymax, zmax)) en mm.
    None en un límite (o en todo un extremo) es sin límite."""
    if box_mm is None:
        return True
    bmin, bmax = box_mm
    for i in range(3):
        lo, hi = lo_cm[i] * MM_PER_CM, hi_cm[i] * MM_PER_CM
        if bmin is not None and bmin[i] is not None and lo < bmin[i] - tol_mm:
            return False
        if bmax is not None and bmax[i] is not None and hi > bmax[i] + tol_mm:
            return False
    return True


def same_color(a, b):
    """Si dos colores '#RRGGBB' son el mismo, sin mirar mayúsculas ni el '#'."""
    if a is None or b is None:
        return a is b
    return a.lstrip('#').upper() == b.lstrip('#').upper()
