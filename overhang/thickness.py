# Mapa de espesor de pared sobre una malla de triángulos. Sin dependencias de Fusion: listas planas
# (x, y, z, x, y, z…) en cualquier unidad, para poder probarlo aparte.
#
# El espesor de cada triángulo es la distancia desde su centro hasta la pared de enfrente, siguiendo la normal
# hacia dentro (el rayo lo lanza Fusion contra la propia malla). No se usa PolygonMesh.wallThickness: mide por
# nodos y en las aristas curvas da valores casi nulos (0,03 mm en el canto de un tubo de 0,8).
import math

NO_HIT = 1e30   # el rayo no ha encontrado la pared de enfrente (malla abierta)
EPS = 1e-3      # margen relativo al comparar con el mínimo

# Escala de rojo (fino, el problema) a azul (grueso)
STOPS = [(0.0, (220, 30, 30)), (0.25, (240, 220, 0)), (0.5, (60, 200, 60)), (0.75, (0, 190, 230)),
         (1.0, (30, 60, 230))]
THIN = (220, 30, 30, 255)   # con "solo lo fino": todo lo que no llega al mínimo, en rojo


def _tri(coords, indices, t):
    """(a, b, d) posiciones en coords de los nodos del triángulo t, su producto vectorial y su área."""
    a, b, d = (3 * k for k in indices[t:t + 3])
    c = coords
    e1 = (c[b] - c[a], c[b + 1] - c[a + 1], c[b + 2] - c[a + 2])
    e2 = (c[d] - c[a], c[d + 1] - c[a + 1], c[d + 2] - c[a + 2])
    cr = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
    return (a, b, d), cr, 0.5 * math.sqrt(cr[0] * cr[0] + cr[1] * cr[1] + cr[2] * cr[2])


def rays(coords, indices):
    """Un rayo por triángulo: (origen = centro, dirección = normal hacia dentro, unitaria). Los triángulos
    degenerados dan None."""
    out = []
    c = coords
    for t in range(0, len(indices) - 2, 3):
        (a, b, d), cr, area = _tri(coords, indices, t)
        if area == 0:
            out.append(None)
            continue
        ln = 2 * area
        o = ((c[a] + c[b] + c[d]) / 3.0, (c[a + 1] + c[b + 1] + c[d + 1]) / 3.0, (c[a + 2] + c[b + 2] + c[d + 2]) / 3.0)
        out.append((o, (-cr[0] / ln, -cr[1] / ln, -cr[2] / ln)))
    return out


def node_values(indices, n_nodes, tri_vals, hi):
    """Valor de cada nodo: media de los triángulos que lo usan (para que el color pase suave dentro de cada
    cara; Fusion repite los nodos en cada cara, así que no se mezclan caras distintas). Los triángulos sin
    pared enfrente cuentan como 'hi'."""
    acc, cnt = [0.0] * n_nodes, [0] * n_nodes
    for t, w in enumerate(tri_vals):
        w = hi if w >= NO_HIT else w
        for k in indices[3 * t:3 * t + 3]:
            acc[k] += w
            cnt[k] += 1
    return [acc[i] / cnt[i] if cnt[i] else hi for i in range(n_nodes)]


def color(value, lo, hi):
    """Color RGBA de la escala para un espesor; por debajo de lo y por encima de hi se queda en el extremo."""
    t = 0.0 if hi <= lo else min(1.0, max(0.0, (value - lo) / (hi - lo)))
    for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
        if t <= t1:
            k = (t - t0) / (t1 - t0)
            return tuple(int(round(c0[i] + (c1[i] - c0[i]) * k)) for i in range(3)) + (255,)
    return STOPS[-1][1] + (255,)


def colorize(coords, normals, indices, tri_vals, lo, hi, limit, only_thin=False):
    """Colorea la malla según el espesor de cada triángulo (tri_vals, en las unidades de coords).

    Con only_thin solo salen, en rojo, los triángulos por debajo de 'limit'.
    Devuelve (coords, normals, colors, stats): triángulos con vértices propios y
    stats = {'min': espesor mínimo o None, 'at': centro del triángulo más fino o None,
             'thin': área por debajo de limit, 'total': área total}."""
    nodes = node_values(indices, len(coords) // 3, tri_vals, hi)
    out_c, out_n, out_col = [], [], []
    vmin, at, thin, total = None, None, 0.0, 0.0
    c = coords
    for t, w in enumerate(tri_vals):
        (a, b, d), _, area = _tri(coords, indices, 3 * t)
        total += area
        if w < NO_HIT and (vmin is None or w < vmin):
            vmin = w
            at = tuple((c[a + i] + c[b + i] + c[d + i]) / 3.0 for i in range(3))
        if w < limit - EPS * limit:   # una pared de 0,8 justa no cuenta como fina con un mínimo de 0,8
            thin += area
        elif only_thin:
            continue
        for p in (a, b, d):
            out_c += c[p:p + 3]
            out_n += normals[p:p + 3]
            out_col += THIN if only_thin else color(nodes[p // 3], lo, hi)
    return out_c, out_n, out_col, {'min': vmin, 'at': at, 'thin': thin, 'total': total}


def vertex_normals(coords, indices):
    """Normal de cada nodo como suma de las de sus triángulos (para mallas que no traen normales por nodo)."""
    acc = [0.0] * len(coords)
    for t in range(0, len(indices) - 2, 3):
        pts, cr, _ = _tri(coords, indices, t)
        for p in pts:
            acc[p] += cr[0]
            acc[p + 1] += cr[1]
            acc[p + 2] += cr[2]
    out = []
    for i in range(0, len(acc), 3):
        ln = math.sqrt(acc[i] ** 2 + acc[i + 1] ** 2 + acc[i + 2] ** 2) or 1.0
        out += [acc[i] / ln, acc[i + 1] / ln, acc[i + 2] / ln]
    return out


def convex_min(coords, indices, tri_vals, min_angle=30.0, digits=5):
    """Corrige los cantos de las paredes finas: el rayo que sale del canto de arriba de una aleta la recorre a
    lo alto, no a lo ancho. Cada triángulo toma el mínimo entre su valor y el de los triángulos con los que
    comparte una arista convexa de más de min_angle grados (el canto de una aleta de 0,4 pasa a 0,4; la base
    de un bloque de 4 mm sigue en 4, porque al otro lado de su arista hay una cara más gruesa).
    Las aristas cóncavas (pie de una aleta sobre la base) no cuentan."""
    n_tri = len(indices) // 3
    cos_lim = math.cos(math.radians(min_angle))
    cen, nrm = [], []
    for t in range(n_tri):
        (a, b, d), cr, area = _tri(coords, indices, 3 * t)
        ln = 2 * area or 1.0
        cen.append(tuple((coords[a + i] + coords[b + i] + coords[d + i]) / 3.0 for i in range(3)))
        nrm.append((cr[0] / ln, cr[1] / ln, cr[2] / ln))
    # Vecinos por nodo y no por arista: Fusion discretiza por separado las dos caras de una arista y no siempre
    # coinciden todos los nodos, pero sí algunos.
    at_node = {}
    for t in range(n_tri):
        for k in indices[3 * t:3 * t + 3]:
            key = (round(coords[3 * k], digits), round(coords[3 * k + 1], digits), round(coords[3 * k + 2], digits))
            at_node.setdefault(key, set()).add(t)
    out = list(tri_vals)
    done = set()
    for tris in at_node.values():
        tris = sorted(tris)
        for i, p in enumerate(tris):
            for q in tris[i + 1:]:
                if (p, q) in done:
                    continue
                done.add((p, q))
                n_p, n_q = nrm[p], nrm[q]
                if n_p[0] * n_q[0] + n_p[1] * n_q[1] + n_p[2] * n_q[2] > cos_lim:
                    continue   # casi en el mismo plano
                d = (cen[q][0] - cen[p][0], cen[q][1] - cen[p][1], cen[q][2] - cen[p][2])
                # convexa vista desde los dos lados: cada centro queda detrás del plano del otro
                if (n_p[0] * d[0] + n_p[1] * d[1] + n_p[2] * d[2] >= 0
                        or n_q[0] * d[0] + n_q[1] * d[1] + n_q[2] * d[2] <= 0):
                    continue
                w = min(tri_vals[p], tri_vals[q])
                out[p], out[q] = min(out[p], w), min(out[q], w)
    return out
