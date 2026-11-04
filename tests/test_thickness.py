# Pruebas de overhang/thickness.py sin Fusion:  python -m unittest discover -s tests
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from overhang import thickness as T  # noqa: E402


def square():
    """Cuadrado de lado 1 en z=0, mirando hacia arriba, con dos triángulos que repiten los nodos de la diagonal."""
    coords = [0, 0, 0, 1, 0, 0, 1, 1, 0,
              0, 0, 0, 1, 1, 0, 0, 1, 0]
    return coords, [0, 0, 1] * 6, list(range(6))


class RaysTest(unittest.TestCase):
    def test_center_and_inward_normal(self):
        c, _, idx = square()
        r = T.rays(c, idx)
        self.assertEqual(len(r), 2)
        o, d = r[0]
        for got, want in zip(o, (2 / 3, 1 / 3, 0)):
            self.assertAlmostEqual(got, want)
        self.assertEqual(tuple(round(v, 9) for v in d), (0, 0, -1))   # hacia dentro: contra la normal

    def test_degenerate(self):
        self.assertEqual(T.rays([0, 0, 0, 1, 0, 0, 2, 0, 0], [0, 1, 2]), [None])


class ColorTest(unittest.TestCase):
    def test_thin_is_red(self):
        self.assertEqual(T.color(0.0, 0.0, 4.0), T.THIN)
        self.assertEqual(T.color(4.0, 0.0, 4.0), (30, 60, 230, 255))

    def test_ends_and_clamp(self):
        self.assertEqual(T.color(0.0, 0.0, 4.0), T.STOPS[0][1] + (255,))
        self.assertEqual(T.color(4.0, 0.0, 4.0), T.STOPS[-1][1] + (255,))
        self.assertEqual(T.color(-1.0, 0.0, 4.0), T.color(0.0, 0.0, 4.0))
        self.assertEqual(T.color(9.0, 0.0, 4.0), T.color(4.0, 0.0, 4.0))
        self.assertEqual(T.color(2.0, 0.0, 4.0), T.STOPS[2][1] + (255,))


class ColorizeTest(unittest.TestCase):
    def test_min_area_and_no_hit(self):
        c, n, idx = square()
        oc, _, col, st = T.colorize(c, n, idx, [0.5, T.NO_HIT], 0.0, 4.0, 1.0)
        self.assertEqual(st['min'], 0.5)
        for got, want in zip(st['at'], (2 / 3, 1 / 3, 0)):
            self.assertAlmostEqual(got, want)
        self.assertAlmostEqual(st['total'], 1.0)
        self.assertAlmostEqual(st['thin'], 0.5)
        self.assertEqual(len(oc), 18)
        self.assertEqual(col[-4:], list(T.color(4.0, 0.0, 4.0)))   # sin pared enfrente: color del máximo

    def test_only_thin(self):
        c, n, idx = square()
        oc, _, col, st = T.colorize(c, n, idx, [0.5, 3.0], 0.0, 4.0, 1.0, only_thin=True)
        self.assertEqual(len(oc), 9)                # solo el primer triángulo
        self.assertEqual(col[:4], list(T.THIN))
        self.assertAlmostEqual(st['thin'], 0.5)

    def test_node_values_average(self):
        self.assertEqual(T.node_values([0, 1, 2, 0, 2, 3], 4, [1.0, 3.0], 4.0), [2.0, 1.0, 2.0, 3.0])


def welded_box(sx=4.0, sy=4.0, sz=4.0):
    """Caja con los nodos compartidos entre caras, como un STL importado, en sentido antihorario visto desde fuera."""
    c = []
    for z in (0.0, sz):
        for y in (0.0, sy):
            for x in (0.0, sx):
                c += [x, y, z]
    idx = []
    for a, b, d, e in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)):
        idx += [a, b, d, a, d, e]
    return c, idx


def total_area(c, idx):
    return sum(T._tri(c, idx, t)[2] for t in range(0, len(idx), 3))


class RefineTest(unittest.TestCase):
    def test_no_side_longer_than_the_maximum(self):
        c, _, idx = square()
        out, n, oi = T.refine(c, idx, 0.3)
        self.assertGreater(len(oi) // 3, 2)
        for t in range(0, len(oi), 3):
            for p, q in ((oi[t], oi[t + 1]), (oi[t + 1], oi[t + 2]), (oi[t + 2], oi[t])):
                d = sum((out[3 * p + k] - out[3 * q + k]) ** 2 for k in range(3)) ** 0.5
                self.assertLessEqual(d, 0.3 + 1e-9)

    def test_keeps_the_area_and_the_direction(self):
        c, _, idx = square()
        out, n, oi = T.refine(c, idx, 0.3)
        self.assertAlmostEqual(total_area(out, oi), total_area(c, idx))
        for t in range(0, len(oi), 3):
            self.assertGreater(T._tri(out, oi, t)[1][2], 0.0)
        for i in range(0, len(n), 3):
            self.assertEqual([round(v, 6) for v in n[i:i + 3]], [0.0, 0.0, 1.0])

    def test_long_slivers_are_split_less(self):
        # 40 de largo y 0,01 de ancho, con un máximo de 2: basta con 8 de largo, no hacen falta 2
        c = [0.0, 0.0, 0.0, 40.0, 0.0, 0.0, 40.0, 0.01, 0.0, 0.0, 0.01, 0.0]
        out, _, oi = T.refine(c, [0, 1, 2, 0, 2, 3], 2.0)
        longest = max(max(abs(out[3 * oi[t + i]] - out[3 * oi[t + j]]) for i, j in ((0, 1), (1, 2), (2, 0)))
                      for t in range(0, len(oi), 3))
        self.assertLessEqual(longest, 8.0 + 1e-9)
        self.assertGreater(longest, 2.0)
        self.assertAlmostEqual(total_area(out, oi), 0.4)

    def test_small_triangles_stay_as_they_are(self):
        c, _, idx = square()
        out, _, oi = T.refine(c, idx, 100.0)
        self.assertEqual(len(oi), len(idx))
        self.assertEqual(len(out) // 3, 4)   # square() repite nodos en la diagonal

    def test_sharp_edges_split_the_nodes_between_faces(self):
        c, idx = welded_box()
        out, n, oi = T.refine(c, idx, 100.0)
        self.assertEqual(len(out) // 3, 6 * 4)   # cuatro nodos propios por cara, y no ocho en total
        self.assertEqual(len(oi) // 3, 12)
        for i in range(0, len(n), 3):
            self.assertEqual(sorted(abs(round(v, 6)) for v in n[i:i + 3]), [0.0, 0.0, 1.0])

    def test_gentle_curve_stays_a_single_face_with_smooth_normals(self):
        # dos facetas plegadas 20° comparten nodo y normal en el pliegue
        s, co = math.sin(math.radians(20)), math.cos(math.radians(20))
        c = [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 1 + co, 0, s, 1 + co, 1, s]
        idx = [3, 0, 1, 3, 1, 2, 2, 1, 4, 2, 4, 5]
        out, n, oi = T.refine([float(v) for v in c], idx, 100.0)
        self.assertEqual(len(out) // 3, 6)
        fold = out.index(1.0, 3)   # el nodo (1, 0, 0)
        self.assertEqual(fold % 3, 0)
        nz = n[fold + 2]
        self.assertTrue(0.9 < nz < 1.0)
        self.assertLess(n[fold], 0.0)

    def test_separate_nodes_at_the_same_place_are_joined(self):
        c, _, idx = square()
        apart = [v for k in idx for v in c[3 * k:3 * k + 3]]
        out, _, oi = T.refine(apart, list(range(len(idx))), 100.0)
        self.assertEqual(len(out) // 3, 4)

    def test_degenerate_triangles_disappear(self):
        c = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        out, _, oi = T.refine(c, [0, 1, 2, 0, 1, 3], 100.0)
        self.assertEqual(len(oi), 3)

    def test_big_face_does_not_inherit_a_thin_edge(self):
        # el problema del STL: el valor fino de los cantos se extendía a toda la cara plana
        def share_of_top_marked(coords, indices):
            cross = [T._tri(coords, indices, t)[1] for t in range(0, len(indices), 3)]
            thick = [40.0 if abs(cr[2]) > 0 else 1.0 for cr in cross]   # los laterales son el canto fino
            fixed = T.convex_min(coords, indices, thick)
            top = [i for i, cr in enumerate(cross) if cr[2] > 0]
            return sum(1 for i in top if fixed[i] == 1.0) / len(top)

        c, idx = welded_box(40.0, 40.0, 1.0)
        self.assertEqual(share_of_top_marked(c, idx), 1.0)   # sin partir, la cara entera
        out, _, oi = T.refine(c, idx, 2.0)
        self.assertLess(share_of_top_marked(out, oi), 0.3)   # partida, solo la orilla

def fin_corner():
    """Dos triángulos que forman una arista convexa de 90°: la cara de arriba (z=1, mira a +z) y la lateral
    (x=1, mira a +x), como el canto de una aleta."""
    coords = [0, 0, 1, 1, 0, 1, 1, 1, 1,     # arriba
              1, 0, 1, 1, 0, 0, 1, 1, 0]     # lateral, comparte la arista (1,0,1)-(1,1,1)
    coords[15:18] = [1, 1, 1]
    return coords, [0, 1, 2, 3, 4, 5]


class ConvexMinTest(unittest.TestCase):
    def test_convex_edge_takes_min(self):
        c, idx = fin_corner()
        self.assertEqual(T.convex_min(c, idx, [16.0, 0.4]), [0.4, 0.4])

    def test_concave_edge_is_left(self):
        c, idx = fin_corner()
        # mismas caras con las normales al revés: la arista pasa a ser cóncava
        rev = [idx[0], idx[2], idx[1], idx[3], idx[5], idx[4]]
        self.assertEqual(T.convex_min(c, rev, [16.0, 0.4]), [16.0, 0.4])

    def test_coplanar_is_left(self):
        c, _, idx = square()
        self.assertEqual(T.convex_min(c, idx, [3.0, 1.0]), [3.0, 1.0])


class GapTest(unittest.TestCase):
    def test_outward_ray(self):
        c, _, idx = square()
        self.assertEqual(tuple(round(v, 9) for v in T.rays(c, idx, outward=True)[0][1]), (0, 0, 1))

    def test_ray_box(self):
        box = ((1, -1, -1), (2, 1, 1))
        self.assertTrue(T.ray_box((0, 0, 0), (1, 0, 0), *box))
        self.assertFalse(T.ray_box((0, 0, 0), (-1, 0, 0), *box))    # la caja queda detrás
        self.assertFalse(T.ray_box((0, 5, 0), (1, 0, 0), *box))     # paralelo, por fuera
        self.assertTrue(T.ray_box((1.5, 0, 0), (0, 0, 1), *box))    # sale de dentro

    def test_classify_other(self):
        back = 0.001
        self.assertEqual(T.classify_other([], back), (T.GAP, None))
        kind, d = T.classify_other([0.031, 0.5], back)              # espacio de 0,03 hasta el otro cuerpo
        self.assertEqual(kind, T.GAP)
        self.assertAlmostEqual(d, 0.03)
        self.assertEqual(T.classify_other([0.001, 0.4], back), (T.CONTACT, 0.0))   # caras que se tocan
        self.assertEqual(T.classify_other([0.2], back), (T.OVERLAP, 0.0))          # el punto está dentro
        # un choque repetido en una arista no cambia la cuenta
        self.assertEqual(T.classify_other([0.031, 0.031, 0.5], back)[0], T.GAP)
        # una malla abierta no permite saber si está dentro
        self.assertEqual(T.classify_other([0.2], back, closed=False)[0], T.GAP)

    def test_combine(self):
        self.assertEqual(T.combine(None, []), (T.GAP, T.NO_HIT, -1))
        self.assertEqual(T.combine(5.0, [(T.GAP, 2.0, 3), (T.GAP, None, 4)]), (T.GAP, 2.0, 3))
        self.assertEqual(T.combine(1.0, [(T.GAP, 2.0, 3)]), (T.GAP, 1.0, -1))
        self.assertEqual(T.combine(1.0, [(T.CONTACT, 0.0, 2), (T.OVERLAP, 0.0, 3)]), (T.OVERLAP, 0.0, 3))
        self.assertEqual(T.combine(1.0, [(T.CONTACT, 0.0, 2)]), (T.CONTACT, 0.0, 2))

    def test_beyond_scale_not_painted(self):
        c, n, idx = square()
        oc, _, _, st = T.colorize_gaps(c, n, idx, [0.5, 9.0], [T.GAP, T.GAP], 0.0, 2.0, 0.1)
        self.assertEqual(len(oc), 9)                                # el de 9 no se pinta
        self.assertEqual(st['min'], 0.5)

    def test_gap_margin(self):
        c, n, idx = square()
        _, _, _, st = T.colorize_gaps(c, n, idx, [0.0995, 0.08], [T.GAP, T.GAP], 0.0, 2.0, 0.1, margin=0.001)
        self.assertAlmostEqual(st['thin'], 0.5)                     # solo el de 0,08

    def test_colorize_gaps(self):
        c, n, idx = square()
        oc, _, col, st = T.colorize_gaps(c, n, idx, [0.5, T.NO_HIT], [T.GAP, T.GAP], 0.0, 4.0, 1.0)
        self.assertEqual(len(oc), 9)                                # sin nada delante no se pinta
        self.assertEqual((st['min'], st['tri']), (0.5, 0))
        self.assertAlmostEqual(st['thin'], 0.5)
        oc, _, col, st = T.colorize_gaps(c, n, idx, [0.0, 0.0], [T.CONTACT, T.OVERLAP], 0.0, 4.0, 1.0)
        self.assertEqual(len(oc), 18)                               # el contacto también se pinta
        self.assertEqual(col[:4], list(T.CONTACT_COLOR))
        self.assertEqual(col[12:16], list(T.OVERLAP_COLOR))
        self.assertIsNone(st['min'])                                # y no cuenta como espacio
        self.assertAlmostEqual(st['contact'], 0.5)
        self.assertAlmostEqual(st['overlap'], 0.5)
        oc, _, col, _ = T.colorize_gaps(c, n, idx, [0.5, 3.0], [T.GAP, T.GAP], 0.0, 4.0, 1.0, only_thin=True)
        self.assertEqual((len(oc), col[:4]), (9, list(T.THIN)))

    def test_retry_origins_stay_inside_the_triangle(self):
        c, _, idx = square()
        for t in (0, 1):
            ids = idx[3 * t:3 * t + 3]
            x = [c[3 * k] for k in ids]
            y = [c[3 * k + 1] for k in ids]
            points = T.retry_origins(c, idx, t)
            self.assertEqual(len(points), 2)
            self.assertNotEqual(points[0], points[1])
            for px, py, pz in points:
                self.assertTrue(min(x) < px < max(x) and min(y) < py < max(y))
                self.assertEqual(pz, 0.0)

    def test_missed_hit_is_not_an_overlap(self):
        # el caso real: holgura de 0,15; Fusion pierde el primer choque (1 de 2) porque el rayo roza una arista
        back = 0.001
        first = T.classify_other([1.907], back)
        self.assertEqual(first, (T.OVERLAP, 0.0))
        retries = [T.classify_other(h, back) for h in ([1.537, 1.907], [1.538, 1.908])]
        kind, dist = T.settle_overlap(retries)
        self.assertEqual(kind, T.GAP)
        self.assertAlmostEqual(dist, 1.536)

    def test_real_overlap_survives_the_retry(self):
        back = 0.001
        self.assertEqual(T.settle_overlap([(T.OVERLAP, 0.0), (T.OVERLAP, 0.0)]), (T.OVERLAP, 0.0))
        # en el borde del solape, un punto puede quedar fuera: 2 de 3 siguen contando
        self.assertEqual(T.settle_overlap([T.classify_other([], back), (T.OVERLAP, 0.0)]), (T.OVERLAP, 0.0))

    def test_contact_is_painted_in_any_paint_mode(self):
        c, n, idx = square()
        for only_thin in (False, True):
            oc, _, col, st = T.colorize_gaps(c, n, idx, [0.0, 3.0], [T.CONTACT, T.GAP], 0.0, 4.0, 1.0, only_thin=only_thin)
            self.assertEqual(col[:4], list(T.CONTACT_COLOR))
            self.assertEqual(len(oc), 9 if only_thin else 18)       # con "solo lo fino", el de 3 mm no sale
            self.assertAlmostEqual(st['thin'], 0.0)                 # tocarse no es estar por debajo del mínimo

    def test_contact_does_not_tint_the_scale_next_to_it(self):
        # los nodos compartidos con un triángulo en contacto no promedian su 0: el vecino lleva su color
        c, n, idx = square()
        _, _, col, _ = T.colorize_gaps(c, n, idx, [0.0, 2.0], [T.CONTACT, T.GAP], 0.0, 4.0, 1.0)
        self.assertEqual(col[12:], list(T.color(2.0, 0.0, 4.0)) * 3)


if __name__ == '__main__':
    unittest.main()
