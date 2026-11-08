# Mapa de espesor de pared sobre una malla de triángulos. Sin dependencias de Fusion: listas planas
# (x, y, z, x, y, z…) en cualquier unidad, para poder probarlo aparte.
#
# El espesor de cada triángulo es la distancia desde su centro hasta la pared de enfrente, siguiendo la normal
# hacia dentro (el rayo lo lanza Fusion contra la propia malla). No se usa PolygonMesh.wallThickness: mide por
# nodos y en las aristas curvas da valores casi nulos (0,03 mm en el canto de un tubo de 0,8).
import math

NO_HIT = 1e30   # el rayo no ha encontrado la pared de enfrente (malla abierta)
EPS = 1e-3      # margen relativo al comparar con el mínimo
SLIVER_SIDES = 4   # ver refine

# Escala de rojo (fino, el problema) a azul (grueso)
STOPS = [(0.0, (220, 30, 30)), (0.25, (240, 220, 0)), (0.5, (60, 200, 60)), (0.75, (0, 190, 230)),
         (1.0, (30, 60, 230))]
THIN = (220, 30, 30, 255)   # con "solo lo fino": todo lo que no llega al mínimo, en rojo
OVERLAP_COLOR = (200, 0, 200, 255)   # dos cuerpos ocupan el mismo sitio
CONTACT_COLOR = (255, 255, 255, 255)   # dos cuerpos se tocan: blanco, el único color vivo que no está en la escala

# Qué tiene delante cada triángulo al medir espacios
GAP, CONTACT, OVERLAP = 0, 1, 2


def _tri(coords, indices, t):
    """(a, b, d) posiciones en coords de los nodos del triángulo t, su producto vectorial y su área."""
    a, b, d = 3 * indices[t], 3 * indices[t + 1], 3 * indices[t + 2]
    c = coords
    ax, ay, az = c[a], c[a + 1], c[a + 2]
    e1x, e1y, e1z = c[b] - ax, c[b + 1] - ay, c[b + 2] - az
    e2x, e2y, e2z = c[d] - ax, c[d + 1] - ay, c[d + 2] - az
    cx, cy, cz = e1y * e2z - e1z * e2y, e1z * e2x - e1x * e2z, e1x * e2y - e1y * e2x
    return (a, b, d), (cx, cy, cz), 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)


def rays(coords, indices, outward=False):
    """Un rayo por triángulo: (origen = centro, dirección unitaria según la normal: hacia dentro para medir
    espesor, hacia fuera para medir espacio). Los triángulos degenerados dan None."""
    sign = 1.0 if outward else -1.0
    out = []
    c = coords
    for t in range(0, len(indices) - 2, 3):
        (a, b, d), cr, area = _tri(coords, indices, t)
        if area == 0:
            out.append(None)
            continue
        ln = 2 * area
        o = ((c[a] + c[b] + c[d]) / 3.0, (c[a + 1] + c[b + 1] + c[d + 1]) / 3.0, (c[a + 2] + c[b + 2] + c[d + 2]) / 3.0)
        out.append((o, (sign * cr[0] / ln, sign * cr[1] / ln, sign * cr[2] / ln)))
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
    # un color por nodo y no por vértice de triángulo: cada nodo se usa en unos seis
    colors = None if only_thin else [color(v, lo, hi) for v in node_values(indices, len(coords) // 3, tri_vals, hi)]
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
            out_col += THIN if only_thin else colors[p // 3]
    return out_c, out_n, out_col, {'min': vmin, 'at': at, 'thin': thin, 'total': total}


def _faces(coords, indices, angle_deg, digits):
    """Agrupa los triángulos en caras: (cara de cada triángulo, clave de posición de cada nodo, normal de cada
    triángulo sin normalizar). Dos triángulos con una arista común van en la misma cara si sus normales se
    separan menos de angle_deg; así una curva sigue siendo una sola cara y un canto vivo las separa."""
    keys = [(round(coords[i], digits), round(coords[i + 1], digits), round(coords[i + 2], digits))
            for i in range(0, len(coords), 3)]
    n_tri = len(indices) // 3
    crosses, units, by_edge = [], [], {}
    for t in range(n_tri):
        _, cr, area = _tri(coords, indices, 3 * t)
        ln = 2 * area
        crosses.append(cr)
        units.append((cr[0] / ln, cr[1] / ln, cr[2] / ln) if ln else None)
        if ln:
            a, b, d = (keys[k] for k in indices[3 * t:3 * t + 3])
            for u, v in ((a, b), (b, d), (d, a)):
                by_edge.setdefault((u, v) if u < v else (v, u), []).append(t)
    cos_lim = math.cos(math.radians(angle_deg))
    near = {}
    for tris in by_edge.values():
        for i, p in enumerate(tris):
            for q in tris[i + 1:]:
                n_p, n_q = units[p], units[q]
                if n_p[0] * n_q[0] + n_p[1] * n_q[1] + n_p[2] * n_q[2] > cos_lim:
                    near.setdefault(p, []).append(q)
                    near.setdefault(q, []).append(p)
    face = [None] * n_tri
    count = 0
    for start in range(n_tri):
        if face[start] is None and units[start]:
            face[start] = count
            stack = [start]
            while stack:
                for q in near.get(stack.pop(), ()):
                    if face[q] is None:
                        face[q] = count
                        stack.append(q)
            count += 1
    return face, keys, crosses


def refine(coords, indices, max_side, angle_deg=30.0, digits=5):
    """Prepara una malla importada (un STL) para medirla como la de un sólido: (coords, normales, índices).

    Se mide un rayo por triángulo, y los de un STL pueden ser enormes en las caras planas: uno que cae junto a un
    canto contaría entero como fino. Por eso se parten hasta que ningún lado pase de max_side. Las astillas de las
    curvas, largas y sin apenas área, pueden llegar a SLIVER_SIDES veces max_side: pesan poco en el área y partirlas
    igual multiplicaría los triángulos. Además, cada cara (ver _faces) tiene sus propios nodos, como en la malla de
    un sólido, para que el color no se mezcle entre caras. Los triángulos degenerados desaparecen."""
    face, keys, crosses = _faces(coords, indices, angle_deg, digits)
    out_c, acc, node_of = [], [], {}
    tris = []
    for t, f in enumerate(face):
        if f is None:
            continue
        ids = []
        for k in indices[3 * t:3 * t + 3]:
            key = (f, keys[k])
            node = node_of.get(key)
            if node is None:
                node = node_of[key] = len(out_c) // 3
                out_c += coords[3 * k:3 * k + 3]
                acc += [0.0, 0.0, 0.0]
            ids.append(node)
            cr = crosses[t]
            acc[3 * node] += cr[0]
            acc[3 * node + 1] += cr[1]
            acc[3 * node + 2] += cr[2]
        tris.append(tuple(ids))
    normals = []
    for i in range(0, len(acc), 3):
        ln = math.sqrt(acc[i] ** 2 + acc[i + 1] ** 2 + acc[i + 2] ** 2) or 1.0
        normals += [acc[i] / ln, acc[i + 1] / ln, acc[i + 2] / ln]

    def dist2(p, q):
        i, j = 3 * p, 3 * q
        return (out_c[i] - out_c[j]) ** 2 + (out_c[i + 1] - out_c[j + 1]) ** 2 + (out_c[i + 2] - out_c[j + 2]) ** 2

    middle = {}

    def mid(p, q):
        key = (p, q) if p < q else (q, p)
        node = middle.get(key)
        if node is None:
            node = middle[key] = len(out_c) // 3
            i, j = 3 * p, 3 * q
            out_c.extend(((out_c[i] + out_c[j]) / 2, (out_c[i + 1] + out_c[j + 1]) / 2, (out_c[i + 2] + out_c[j + 2]) / 2))
            nx, ny, nz = normals[i] + normals[j], normals[i + 1] + normals[j + 1], normals[i + 2] + normals[j + 2]
            ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            normals.extend((nx / ln, ny / ln, nz / ln))
        return node

    limit = max_side * max_side
    out_i = []
    while tris:
        a, b, d = tris.pop()
        ab, bd, da = dist2(a, b), dist2(b, d), dist2(d, a)
        longest = max(ab, bd, da)
        # área² de Herón con los cuadrados de los lados; una astilla es la que tiene menos área que un triángulo
        # rectángulo isósceles de hipotenusa max_side
        area2 = max(0.0, 2 * (ab * bd + bd * da + da * ab) - ab * ab - bd * bd - da * da) / 16
        sliver = area2 <= limit * limit / 16 and longest <= limit * SLIVER_SIDES * SLIVER_SIDES
        if longest <= limit or sliver:
            out_i += [a, b, d]
        elif longest == ab:   # por el lado más largo, para que no salgan astillas; se conserva el sentido de giro
            m = mid(a, b)
            tris += [(a, m, d), (m, b, d)]
        elif longest == bd:
            m = mid(b, d)
            tris += [(a, b, m), (a, m, d)]
        else:
            m = mid(d, a)
            tris += [(a, b, m), (m, b, d)]
    return out_c, normals, out_i


def convex_min(coords, indices, tri_vals, min_angle=30.0, digits=5):
    """Corrige los cantos de las paredes finas: el rayo que sale del canto de arriba de una aleta la recorre a
    lo alto, no a lo ancho. Cada triángulo toma el mínimo entre su valor y el de los triángulos con los que
    comparte una arista convexa de más de min_angle grados (el canto de una aleta de 0,4 pasa a 0,4; la base
    de un bloque de 4 mm sigue en 4, porque al otro lado de su arista hay una cara más gruesa).
    Las aristas cóncavas (pie de una aleta sobre la base) no cuentan."""
    n_tri = len(indices) // 3
    cos_lim = math.cos(math.radians(min_angle))
    cos_half = math.cos(math.radians(min_angle / 2))
    cen, nrm = [], []
    for t in range(n_tri):
        (a, b, d), cr, area = _tri(coords, indices, 3 * t)
        ln = 2 * area or 1.0
        cen.append(tuple((coords[a + i] + coords[b + i] + coords[d + i]) / 3.0 for i in range(3)))
        nrm.append((cr[0] / ln, cr[1] / ln, cr[2] / ln))
    # Vecinos por nodo y no por arista: Fusion discretiza por separado las dos caras de una arista y no siempre
    # coinciden todos los nodos, pero sí algunos.
    keys = [(round(coords[i], digits), round(coords[i + 1], digits), round(coords[i + 2], digits))
            for i in range(0, len(coords), 3)]
    at_node = {}
    for t in range(n_tri):
        for k in indices[3 * t:3 * t + 3]:
            at_node.setdefault(keys[k], []).append(t)
    out = list(tri_vals)
    done = set()
    for tris in at_node.values():
        # casi todos los nodos están dentro de una cara: si todos sus triángulos están a menos de min_angle/2 del
        # primero, ninguna pareja llega a min_angle y no hace falta mirarlas
        fx, fy, fz = nrm[tris[0]]
        if all(fx * nrm[t][0] + fy * nrm[t][1] + fz * nrm[t][2] > cos_half for t in tris):
            continue
        tris = sorted(set(tris))
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


def ray_box(o, d, bmin, bmax):
    """El rayo (semirrecta) toca la caja? Sirve para no preguntar a Fusion por los cuerpos que quedan lejos."""
    t0, t1 = 0.0, float('inf')
    for i in range(3):
        if abs(d[i]) < 1e-12:
            if o[i] < bmin[i] or o[i] > bmax[i]:
                return False
            continue
        a, b = (bmin[i] - o[i]) / d[i], (bmax[i] - o[i]) / d[i]
        if a > b:
            a, b = b, a
        t0, t1 = max(t0, a), min(t1, b)
        if t0 > t1:
            return False
    return True


def classify_other(hits, back, closed=True):
    """Qué es otro cuerpo para un triángulo, a partir de las distancias a sus choques medidas desde un punto
    'back' por detrás de la cara (dentro de su propio cuerpo). Devuelve (tipo, distancia desde la cara o None):
    - un número impar de choques: ese punto está dentro del otro cuerpo, se solapan (OVERLAP);
    - el primer choque a 'back' o menos de la cara: se tocan (CONTACT);
    - si no, el espacio hasta él (GAP), o None si no hay nada delante.
    Se empieza por detrás porque desde la propia cara no se distingue tocar de solapar."""
    uniq = []
    for h in sorted(hits):
        if not uniq or h - uniq[-1] > 1e-6:   # un rayo que pasa por una arista choca con dos triángulos
            uniq.append(h)
    if closed and len(uniq) % 2:
        return OVERLAP, 0.0
    if not uniq:
        return GAP, None
    d = uniq[0] - back
    return (CONTACT, 0.0) if d <= back else (GAP, d)


def retry_origins(coords, indices, t):
    """Dos puntos del triángulo t, a medio camino entre su centro y dos de sus vértices, para repetir un rayo."""
    (a, b, d), _, _ = _tri(coords, indices, 3 * t)
    c = coords
    center = [(c[a + i] + c[b + i] + c[d + i]) / 3.0 for i in range(3)]
    return [tuple((center[i] + c[v + i]) / 2.0 for i in range(3)) for v in (a, b)]


def settle_overlap(retries):
    """Decide un solape dudoso con el resultado de classify_other en los dos rayos repetidos. El rayo de Fusion
    puede perder un choque si roza una arista de la malla (con 2 choques reales devuelve 1, medido en una holgura
    de 0,15), y un número impar parecería un solape. Es de verdad si lo repite alguno de los dos (2 de 3); si no,
    vale lo que ha medido el primero."""
    for kind, dist in retries:
        if kind == OVERLAP:
            return OVERLAP, 0.0
    return retries[0]


def combine(own, others):
    """Resultado de un triángulo: (tipo, espacio o NO_HIT, cuerpo de enfrente o -1 si es el suyo).
    own es la distancia a su propio cuerpo o None; others, (tipo, distancia o None, cuerpo) de los demás.
    Solaparse manda sobre tocarse y tocarse sobre cualquier espacio."""
    for want in (OVERLAP, CONTACT):
        for kind, _, j in others:
            if kind == want:
                return want, 0.0, j
    best, who = (own, -1) if own is not None else (NO_HIT, -1)
    for _, d, j in others:
        if d is not None and d < best:
            best, who = d, j
    return GAP, best, who


def below_limit(w, limit, margin=0.0):
    """Si el espacio w no llega a limit: tiene que bajar más que 'margin', el error de la malla."""
    return w < limit - max(EPS * limit, margin)


def colorize_gaps(coords, normals, indices, vals, kinds, lo, hi, limit, only_thin=False, margin=0.0):
    """Colorea la malla según el espacio que tiene delante cada triángulo. No se pinta lo que no tiene nada
    delante ni lo que supera hi: el mapa es para ver lo estrecho, y lo lejano solo tapa. Lo que toca a otro cuerpo
    va siempre en CONTACT_COLOR y lo que se solapa, en OVERLAP_COLOR. Solo cuenta como por debajo
    de limit lo que baja más que 'margin', el error de la malla (0,0999 en una holgura de 0,1 entre curvas).
    Devuelve (coords, normals, colors, stats), con stats = {'min': espacio más estrecho o None,
    'tri': triángulo donde está, 'thin': área por debajo de limit, 'contact', 'overlap': áreas}."""
    measured = [w if k == GAP and w < NO_HIT else None for w, k in zip(vals, kinds)]
    acc, cnt = [0.0] * (len(coords) // 3), [0] * (len(coords) // 3)
    for t, w in enumerate(measured):
        if w is not None and w <= hi:
            for k in indices[3 * t:3 * t + 3]:
                acc[k] += w
                cnt[k] += 1
    out_c, out_n, out_col = [], [], []
    vmin, where, thin, contact, overlap = None, None, 0.0, 0.0, 0.0
    c = coords
    for t, w in enumerate(measured):
        (a, b, d), _, area = _tri(coords, indices, 3 * t)
        if kinds[t] == CONTACT:
            contact += area
            cols = (CONTACT_COLOR,) * 3
        elif kinds[t] == OVERLAP:
            overlap += area
            cols = (OVERLAP_COLOR,) * 3
        elif w is None:
            continue
        else:
            if vmin is None or w < vmin:
                vmin, where = w, t
            below = below_limit(w, limit, margin)
            if below:
                thin += area
            elif only_thin or w > hi:
                continue
            cols = (THIN,) * 3 if only_thin else tuple(color(acc[p // 3] / cnt[p // 3], lo, hi) for p in (a, b, d))
        for p, col in zip((a, b, d), cols):
            out_c += c[p:p + 3]
            out_n += normals[p:p + 3]
            out_col += col
    return out_c, out_n, out_col, {'min': vmin, 'tri': where, 'thin': thin, 'contact': contact, 'overlap': overlap}
