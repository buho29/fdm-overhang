# Pruebas de overhang/analysis.py sin Fusion:  python -m unittest discover -s tests
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from overhang import analysis as A  # noqa: E402

UP = (0.0, 0.0, 1.0)


def cube(z0=0.0):
    """Cubo de lado 1 con la base a altura z0, triángulos en sentido antihorario visto desde fuera."""
    v = [(x, y, z0 + z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    idx = []
    for a, b, c, d in quads:
        idx += [a, b, c, a, c, d]
    return [k for p in v for k in p], idx


def tilted(deg, z=5.0):
    """Un triángulo suelto que mira hacia abajo a 'deg' desde la horizontal."""
    t = math.radians(deg)
    coords = [0, 0, z, 0, 1, z, math.cos(t), 0, z - math.sin(t)]
    n = (-math.sin(t), 0.0, -math.cos(t))   # normal hacia abajo y fuera
    return coords, list(n) * 3, [0, 1, 2]


class ClassifyTest(unittest.TestCase):
    def test_cube_on_bed(self):
        c, idx = cube()
        _, _, _, st = A.classify(c, [], idx, UP, A.lowest(c, UP), 45)
        self.assertAlmostEqual(st['total'], 6.0)
        self.assertAlmostEqual(st['bed'], 1.0)
        self.assertEqual(st['overhang'], 0.0)

    def test_floating_cube_has_flat_ceiling(self):
        c, idx = cube(z0=2.0)
        out, _, cols, st = A.classify(c, [], idx, UP, 0.0, 45)
        self.assertAlmostEqual(st['overhang'], 1.0)
        self.assertAlmostEqual(st['worst'], 0.0)
        self.assertEqual(len(out), 2 * 9)                 # los dos triángulos de la base
        self.assertEqual(tuple(cols[:4]), A.RED)          # techo plano: rojo puro

    def test_limit_angle(self):
        for deg, limit, marked in ((30, 45, True), (45, 45, False), (44, 45, True), (60, 45, False), (30, 30, False)):
            c, n, idx = tilted(deg)
            _, _, _, st = A.classify(c, n, idx, UP, 0.0, limit)
            self.assertEqual(st['overhang'] > 0, marked, (deg, limit))

    def test_gradient(self):
        c, n, idx = tilted(30)
        _, _, cols, _ = A.classify(c, n, idx, UP, 0.0, 45, gradient=True)
        self.assertNotEqual(tuple(cols[:4]), A.RED)
        _, _, cols, _ = A.classify(c, n, idx, UP, 0.0, 45, gradient=False)
        self.assertEqual(tuple(cols[:4]), A.RED)

    def test_other_up_direction(self):
        c, idx = cube(z0=2.0)
        up = (0.0, 1.0, 0.0)   # Y arriba: la cara y=0 apoya en la cama y la de z=2 es una pared
        _, _, _, st = A.classify(c, [], idx, up, A.lowest(c, up), 45)
        self.assertAlmostEqual(st['bed'], 1.0)
        self.assertEqual(st['overhang'], 0.0)

    def test_transform(self):
        m = [1, 0, 0, 10,
             0, 0, -1, 0,
             0, 1, 0, 3,
             0, 0, 0, 1]   # giro de 90° alrededor de X y traslación (10, 0, 3)
        pts, nrm = A.transform([1, 2, 3], [0, 0, 1], m)
        self.assertEqual(pts, [11, -3, 5])
        self.assertEqual(nrm, [0, -1, 0])


class OffsetTest(unittest.TestCase):
    def test_moves_along_unit_normal(self):
        out = A.offset([1.0, 2.0, 3.0, 0.0, 0.0, 0.0], [0.0, 0.0, 2.0, 3.0, 4.0, 0.0], 0.5)
        for got, want in zip(out, [1.0, 2.0, 3.5, 0.3, 0.4, 0.0]):
            self.assertAlmostEqual(got, want)

    def test_lift_covers_coarser_mesh(self):
        self.assertGreater(A.lift(0.07, 0.009), 0.07)
        self.assertGreater(A.lift(0.002, 0.009), 0.009)
        self.assertGreater(A.lift(0.0, 0.0), 0.0)


if __name__ == '__main__':
    unittest.main()
