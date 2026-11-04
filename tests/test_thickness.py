# Pruebas de overhang/thickness.py sin Fusion:  python -m unittest discover -s tests
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


class NormalsTest(unittest.TestCase):
    def test_flat_square_points_up(self):
        c, _, idx = square()
        n = T.vertex_normals(c, idx)
        for i in range(0, len(n), 3):
            self.assertEqual([round(v, 6) for v in n[i:i + 3]], [0.0, 0.0, 1.0])


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
        self.assertEqual(len(oc), 9)                                # el contacto no se pinta
        self.assertEqual(col[:4], list(T.OVERLAP_COLOR))
        self.assertIsNone(st['min'])
        self.assertAlmostEqual(st['contact'], 0.5)
        self.assertAlmostEqual(st['overlap'], 0.5)
        oc, _, col, _ = T.colorize_gaps(c, n, idx, [0.5, 3.0], [T.GAP, T.GAP], 0.0, 4.0, 1.0, only_thin=True)
        self.assertEqual((len(oc), col[:4]), (9, list(T.THIN)))


if __name__ == '__main__':
    unittest.main()
