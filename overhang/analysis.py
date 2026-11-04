# Voladizos sobre una malla de triángulos, como la vista de soportes de un laminador.
# Sin dependencias de Fusion: listas planas (x, y, z, x, y, z…) en cualquier unidad, para poder probarlo aparte.
import math

RED = (220, 30, 30, 255)          # techo plano
ORANGE = (255, 150, 0, 255)       # justo por debajo del límite
BED_COLOR = (60, 170, 60, 255)    # apoyado en la cama
BRIDGE_COLOR = (40, 110, 230, 255)   # puente que no pasa del máximo

MARGIN_DEG = 0.5   # gotas y chaflanes justo en el límite son correctos: no se marcan
BRIDGE_LINES = 15      # líneas con las que se recorre un techo plano en cada dirección
BRIDGE_DIR_STEP = 5.0  # grados: dos direcciones más parecidas que esto se prueban una sola vez


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


def _span_along(edges, dx, dy):
    """Luz de un techo plano tendido en la dirección (dx, dy): el tramo más largo entre dos bordes, o None si
    alguna línea acaba en un borde sin apoyo. edges = [(ax, ay, bx, by, apoyado)] en el plano del techo."""
    proj = [(dx * ay - dy * ax, dx * ax + dy * ay, dx * by - dy * bx, dx * bx + dy * by, ok)
            for ax, ay, bx, by, ok in edges]
    lo = min(min(e[0], e[2]) for e in proj)
    hi = max(max(e[0], e[2]) for e in proj)
    span = None
    for i in range(BRIDGE_LINES):
        s = lo + (hi - lo) * (i + 0.5) / BRIDGE_LINES
        hits = []
        for s1, t1, s2, t2, ok in proj:
            if (s1 <= s) != (s2 <= s):
                hits.append((t1 + (t2 - t1) * (s - s1) / (s2 - s1), ok))
        hits.sort(key=lambda h: h[0])
        if len(hits) % 2:
            return None
        for k in range(0, len(hits), 2):
            if not (hits[k][1] and hits[k + 1][1]):
                return None
            span = max(span or 0.0, hits[k + 1][0] - hits[k][0])
    return span


def _best_span(edges):
    """La luz más corta entre las direcciones posibles, como elige un laminador, o None si no hay ninguna.
    Se prueba perpendicular a los bordes apoyados y paralelo a los libres (para los techos en rombo)."""
    if sum(1 for e in edges if e[4]) < 2:
        return None
    count = int(round(180.0 / BRIDGE_DIR_STEP))
    dirs = {}
    for ax, ay, bx, by, ok in edges:
        ang = (math.atan2(by - ay, bx - ax) + (math.pi / 2 if ok else 0.0)) % math.pi
        dirs.setdefault(int(round(math.degrees(ang) / BRIDGE_DIR_STEP)) % count, ang)
    spans = [_span_along(edges, math.cos(a), math.sin(a)) for a in dirs.values()]
    spans = [s for s in spans if s is not None]
    return min(spans) if spans else None


def find_bridges(coords, indices, up, bed, tol=1e-3, edge_tol=None, cos_lim=1.0):
    """Techos planos tendidos entre paredes: {posición del triángulo en indices: luz}.

    Un techo es un conjunto de triángulos horizontales unidos que miran hacia abajo. Un borde suyo está apoyado
    si la cara de al lado baja desde él y no es a su vez un voladizo (cos_lim: coseno del ángulo límite); si no,
    está libre. Así la faceta plana en lo alto de un arco no cuenta: lo que tiene al lado baja casi en horizontal.
    Es un puente si en alguna dirección todas las líneas que lo cruzan van de un borde apoyado a otro.

    Las caras de una arista no comparten todos los nodos: la cara vecina se busca por la distancia entre el
    centro del borde y los bordes de las paredes. En curvas, las dos cuerdas se separan hasta la tolerancia de
    la malla: edge_tol. Ante la duda el techo no es un puente y se queda como voladizo."""
    ux, uy, uz = up
    e1 = unit((-uy, ux, 0.0) if abs(uz) < 0.9 else (uz, 0.0, -ux))
    e2 = (uy * e1[2] - uz * e1[1], uz * e1[0] - ux * e1[2], ux * e1[1] - uy * e1[0])
    c = coords
    xs, ys, hs = [], [], []
    for i in range(0, len(c), 3):
        px, py, pz = c[i], c[i + 1], c[i + 2]
        xs.append(px * e1[0] + py * e1[1] + pz * e1[2])
        ys.append(px * e2[0] + py * e2[1] + pz * e2[2])
        hs.append(px * ux + py * uy + pz * uz)

    def key(i):
        return round(xs[i] / tol), round(ys[i] / tol), round(hs[i] / tol)

    # triángulos de techo y qué triángulos usan cada arista
    by_edge, tri_edges, levels = {}, {}, set()
    for t in range(0, len(indices) - 2, 3):
        a, b, d = indices[t], indices[t + 1], indices[t + 2]
        if max(hs[a], hs[b], hs[d]) - min(hs[a], hs[b], hs[d]) > tol or hs[a] <= bed + tol:
            continue
        # en la base (e1, e2, up) un techo gira en sentido horario visto desde arriba
        if (xs[b] - xs[a]) * (ys[d] - ys[a]) - (ys[b] - ys[a]) * (xs[d] - xs[a]) >= 0:
            continue
        keys = []
        for p, q in ((a, b), (b, d), (d, a)):
            k = (min(key(p), key(q)), max(key(p), key(q)))
            by_edge.setdefault(k, []).append(t)
            keys.append((k, p, q))
        tri_edges[t] = keys
        levels.add(round(hs[a] / tol))
    if not tri_edges:
        return {}

    def overhanging(a, b, d):
        e1x, e1y, e1h = xs[b] - xs[a], ys[b] - ys[a], hs[b] - hs[a]
        e2x, e2y, e2h = xs[d] - xs[a], ys[d] - ys[a], hs[d] - hs[a]
        nx, ny, nh = e1y * e2h - e1h * e2y, e1h * e2x - e1x * e2h, e1x * e2y - e1y * e2x
        return -nh > cos_lim * math.sqrt(nx * nx + ny * ny + nh * nh)

    # bordes horizontales de las paredes que bajan desde la altura de algún techo
    walls = {}
    for t in range(0, len(indices) - 2, 3):
        a, b, d = indices[t], indices[t + 1], indices[t + 2]
        for p, q, r in ((a, b, d), (b, d, a), (d, a, b)):
            if abs(hs[p] - hs[q]) <= tol and hs[r] < hs[p] - tol:
                k = round(hs[p] / tol)
                if (k in levels or k - 1 in levels or k + 1 in levels) and not overhanging(a, b, d):
                    walls.setdefault(k, []).append((xs[p], ys[p], xs[q], ys[q]))

    near = max(tol, edge_tol or 0.0)

    def anchored(p, q):
        mx, my = (xs[p] + xs[q]) / 2, (ys[p] + ys[q]) / 2
        k = round(hs[p] / tol)
        for level in (k, k - 1, k + 1):
            for ax, ay, bx, by in walls.get(level, ()):
                dx, dy = bx - ax, by - ay
                ln = dx * dx + dy * dy
                f = max(0.0, min(1.0, ((mx - ax) * dx + (my - ay) * dy) / ln)) if ln else 0.0
                ex, ey = ax + dx * f - mx, ay + dy * f - my
                if ex * ex + ey * ey <= near * near:
                    return True
        return False

    spans, seen = {}, set()
    for start in tri_edges:
        if start in seen:
            continue
        seen.add(start)
        region, stack, edges = [], [start], []
        while stack:
            t = stack.pop()
            region.append(t)
            for k, p, q in tri_edges[t]:
                users = by_edge[k]
                if len(users) == 1:
                    edges.append((xs[p], ys[p], xs[q], ys[q], anchored(p, q)))
                for other in users:
                    if other not in seen:
                        seen.add(other)
                        stack.append(other)
        span = _best_span(edges)
        # más estrecho que edge_tol: sus dos bordes pueden estar tocando la misma pared, no se puede saber
        if span is not None and span > near:
            for t in region:
                spans[t] = span
    return spans


def classify(coords, normals, indices, up, bed, angle_deg, gradient=True, tol=1e-3, bridge_max=None, edge_tol=None):
    """Triángulos que miran hacia abajo con menos de angle_deg desde la horizontal (voladizo) y los
    que apoyan en la cama (altura 'bed' según 'up'). Con normales vacías usa la del triángulo (sentido antihorario).
    Con bridge_max, los techos tendidos entre paredes (find_bridges) con esa luz o menos se pintan como puente.

    Devuelve (coords, normals, colors, stats): solo los triángulos marcados, con vértices propios para que
    cada uno tenga su color (colors = RGBA 0-255 por vértice), y
    stats = {'total', 'overhang', 'bed', 'bridge': áreas; 'worst': inclinación mínima de los voladizos en grados
    o None; 'span': la luz más larga de los puentes o None; 'long_span': la de los que pasan del máximo o None}."""
    ux, uy, uz = up
    cos_lim = math.cos(math.radians(max(0.0, angle_deg - MARGIN_DEG)))
    spans = find_bridges(coords, indices, up, bed, tol, edge_tol, cos_lim) if bridge_max is not None else {}
    bridge = 0.0
    longest = too_long = None
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
            span = spans.get(t)
            if span is not None and span <= bridge_max + tol:
                col = BRIDGE_COLOR
                bridge += area
                longest = max(longest or 0.0, span)
            else:
                ang = math.degrees(math.acos(min(1.0, down)))   # inclinación desde la horizontal
                col = _mix(RED, ORANGE, ang / angle_deg) if gradient and angle_deg > 0 else RED
                over += area
                worst = ang if worst is None else min(worst, ang)
                if span is not None:
                    too_long = max(too_long or 0.0, span)
        else:
            continue
        for p in (a, b, d):
            out_c += c[p:p + 3]
            out_n += n[p:p + 3] if n else [cx / cl, cy / cl, cz / cl]
            out_col += col
    return out_c, out_n, out_col, {'total': total, 'overhang': over, 'bed': on_bed, 'worst': worst,
                                   'bridge': bridge, 'span': longest, 'long_span': too_long}
