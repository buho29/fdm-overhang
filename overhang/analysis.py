# Voladizos sobre una malla de triángulos, como la vista de soportes de un laminador.
# Sin dependencias de Fusion: listas planas (x, y, z, x, y, z…) en cualquier unidad, para poder probarlo aparte.
import math

RED = (220, 30, 30, 255)          # techo plano
ORANGE = (255, 150, 0, 255)       # justo por debajo del límite
BED_COLOR = (60, 170, 60, 255)    # apoyado en la cama

MARGIN_DEG = 0.5   # gotas y chaflanes justo en el límite son correctos: no se marcan


def transform(coords, normals, m):
    """Aplica a puntos y normales una matriz 4x4 de 16 valores por filas (Matrix3D.asArray de Fusion).
    Las normales solo se giran: las transformaciones de las ocurrencias son rígidas."""
    pts, nrm = [], []
    for i in range(0, len(coords), 3):
        x, y, z = coords[i], coords[i + 1], coords[i + 2]
        pts += [m[0] * x + m[1] * y + m[2] * z + m[3],
                m[4] * x + m[5] * y + m[6] * z + m[7],
                m[8] * x + m[9] * y + m[10] * z + m[11]]
    for i in range(0, len(normals), 3):
        x, y, z = normals[i], normals[i + 1], normals[i + 2]
        nrm += [m[0] * x + m[1] * y + m[2] * z,
                m[4] * x + m[5] * y + m[6] * z,
                m[8] * x + m[9] * y + m[10] * z]
    return pts, nrm


def unit(v):
    ln = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if ln == 0:
        raise ValueError('vector nulo')
    return (v[0] / ln, v[1] / ln, v[2] / ln)


def lowest(coords, up):
    """Altura del punto más bajo según la dirección 'up' (unitaria)."""
    ux, uy, uz = up
    return min(coords[i] * ux + coords[i + 1] * uy + coords[i + 2] * uz for i in range(0, len(coords), 3))


def offset(coords, normals, d):
    """Desplaza cada vértice 'd' a lo largo de su normal (hacia fuera del sólido)."""
    out = []
    for i in range(0, len(coords), 3):
        nx, ny, nz = normals[i], normals[i + 1], normals[i + 2]
        ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        k = d / ln
        out += [coords[i] + nx * k, coords[i + 1] + ny * k, coords[i + 2] + nz * k]
    return out


def lift(tol_analysis, tol_display):
    """Cuánto separar la capa de la superficie para que no quede enterrada en la malla que pinta Fusion.
    Cada malla se aparta de la superficie real como mucho su tolerancia: en zonas convexas la de análisis
    queda por dentro (hasta tol_analysis) y en las cóncavas la de pantalla queda por fuera (hasta tol_display)."""
    return 1.1 * max(tol_analysis, tol_display) + 1e-3


def _mix(a, b, t):
    return tuple(int(round(a[k] + (b[k] - a[k]) * t)) for k in range(4))


def classify(coords, normals, indices, up, bed, angle_deg, gradient=True, tol=1e-3):
    """Triángulos que miran hacia abajo con menos de angle_deg desde la horizontal (voladizo) y los
    que apoyan en la cama (altura 'bed' según 'up'). Con normales vacías usa la del triángulo (sentido antihorario).

    Devuelve (coords, normals, colors, stats): solo los triángulos marcados, con vértices propios para que
    cada uno tenga su color (colors = RGBA 0-255 por vértice), y
    stats = {'total', 'overhang', 'bed': áreas; 'worst': inclinación mínima de los voladizos en grados o None}."""
    ux, uy, uz = up
    cos_lim = math.cos(math.radians(max(0.0, angle_deg - MARGIN_DEG)))
    out_c, out_n, out_col = [], [], []
    total = over = on_bed = 0.0
    worst = None
    c, n = coords, normals
    for t in range(0, len(indices) - 2, 3):
        a, b, d = 3 * indices[t], 3 * indices[t + 1], 3 * indices[t + 2]
        e1x, e1y, e1z = c[b] - c[a], c[b + 1] - c[a + 1], c[b + 2] - c[a + 2]
        e2x, e2y, e2z = c[d] - c[a], c[d + 1] - c[a + 1], c[d + 2] - c[a + 2]
        cx, cy, cz = e1y * e2z - e1z * e2y, e1z * e2x - e1x * e2z, e1x * e2y - e1y * e2x
        cl = math.sqrt(cx * cx + cy * cy + cz * cz)
        if cl == 0:
            continue
        area = 0.5 * cl
        total += area
        if n:
            # normal media de los vértices: es la de la superficie, más fiable que la del triángulo en curvas
            nx, ny, nz = n[a] + n[b] + n[d], n[a + 1] + n[b + 1] + n[d + 1], n[a + 2] + n[b + 2] + n[d + 2]
            nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        else:
            nx, ny, nz, nl = cx, cy, cz, cl
        down = -(nx * ux + ny * uy + nz * uz) / nl   # 1 = techo plano, 0 = pared vertical, < 0 = mira arriba
        if down <= 0:
            continue
        top = max(c[p] * ux + c[p + 1] * uy + c[p + 2] * uz for p in (a, b, d))
        if top <= bed + tol:
            col = BED_COLOR
            on_bed += area
        elif down > cos_lim:
            ang = math.degrees(math.acos(min(1.0, down)))   # inclinación desde la horizontal
            col = _mix(RED, ORANGE, ang / angle_deg) if gradient and angle_deg > 0 else RED
            over += area
            worst = ang if worst is None else min(worst, ang)
        else:
            continue
        for p in (a, b, d):
            out_c += c[p:p + 3]
            out_n += n[p:p + 3] if n else [cx / cl, cy / cl, cz / cl]
            out_col += col
    return out_c, out_n, out_col, {'total': total, 'overhang': over, 'bed': on_bed, 'worst': worst}
