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


def quads(*faces):
    """Malla en la que cada cuadrilátero tiene sus propios nodos, como las caras de Fusion."""
    coords, idx = [], []
    for face in faces:
        base = len(coords) // 3
        for p in face:
            coords += p
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return coords, idx


def ceiling(x0, x1, y0, y1, z):
    return [[x0, y0, z], [x0, y1, z], [x1, y1, z], [x1, y0, z]]   # mira hacia abajo


def wall_below(side, x0, x1, y0, y1, z, h=2.0):
    """Cara que baja desde un borde del techo. Solo cuenta su geometría, no hacia dónde mira."""
    a, b = {'x0': ((x0, y0), (x0, y1)), 'x1': ((x1, y0), (x1, y1)),
            'y0': ((x0, y0), (x1, y0)), 'y1': ((x0, y1), (x1, y1))}[side]
    return [[a[0], a[1], z], [a[0], a[1], z - h], [b[0], b[1], z - h], [b[0], b[1], z]]


def wall_above(side, x0, x1, y0, y1, z, h=2.0):
    return wall_below(side, x0, x1, y0, y1, z + h, h)


def ring(z):
    """Techo de 10 x 10 con un agujero de 2 x 2 en el centro, con los nodos compartidos."""
    coords = []
    for x, y in ((0, 0), (10, 0), (10, 10), (0, 10), (4, 4), (6, 4), (6, 6), (4, 6)):
        coords += [float(x), float(y), z]
    idx = []
    for a, b, d, e in ((0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)):
        idx += [a, b, d, a, d, e]
    return coords, idx


def join(first, second):
    base = len(first[0]) // 3
    return first[0] + second[0], first[1] + [i + base for i in second[1]]


class BridgeTest(unittest.TestCase):
    R = (3.0, 7.0, 0.0, 20.0, 5.0)   # techo de 4 x 20 a altura 5
    SIDES = ('x0', 'x1', 'y0', 'y1')

    def run_case(self, below, above, bridge_max=23.0):
        r = self.R
        c, idx = quads(ceiling(*r), *([wall_below(s, *r) for s in below] + [wall_above(s, *r) for s in above]))
        return A.classify(c, [], idx, UP, 0.0, 45, bridge_max=bridge_max)

    def test_window_between_two_walls(self):
        out, _, cols, st = self.run_case(('x0', 'x1'), ('y0', 'y1'))
        self.assertAlmostEqual(st['span'], 4.0)
        self.assertAlmostEqual(st['bridge'], 80.0)
        self.assertEqual(st['overhang'], 0.0)
        self.assertEqual(tuple(cols[:4]), A.BRIDGE_COLOR)
        self.assertEqual(len(out), 2 * 9)   # solo el techo: las paredes no se pintan

    def test_too_long_stays_red(self):
        _, _, cols, st = self.run_case(('x0', 'x1'), ('y0', 'y1'), bridge_max=3.0)
        self.assertAlmostEqual(st['long_span'], 4.0)
        self.assertIsNone(st['span'])
        self.assertEqual(st['bridge'], 0.0)
        self.assertAlmostEqual(st['overhang'], 80.0)
        self.assertEqual(tuple(cols[:4]), A.RED)

    def test_exact_maximum_is_a_bridge(self):
        self.assertAlmostEqual(self.run_case(('x0', 'x1'), ('y0', 'y1'), bridge_max=4.0)[3]['span'], 4.0)

    def test_disabled(self):
        st = self.run_case(('x0', 'x1'), ('y0', 'y1'), bridge_max=None)[3]
        self.assertEqual(st['bridge'], 0.0)
        self.assertAlmostEqual(st['overhang'], 80.0)
        self.assertIsNone(st['long_span'])

    def test_one_side_is_a_balcony(self):
        st = self.run_case(('x0',), ('x1', 'y0', 'y1'))[3]
        self.assertEqual(st['bridge'], 0.0)
        self.assertIsNone(st['long_span'])
        self.assertAlmostEqual(st['overhang'], 80.0)

    def test_two_adjacent_sides_are_not_a_bridge(self):
        self.assertEqual(self.run_case(('x0', 'y0'), ('x1', 'y1'))[3]['bridge'], 0.0)

    def test_closed_pocket_uses_shortest_direction(self):
        self.assertAlmostEqual(self.run_case(self.SIDES, ())[3]['span'], 4.0)

    def test_table_on_a_stem_is_not_a_bridge(self):
        # las caras de la columna son opuestas, pero entre cada una y el borde del tablero solo hay aire
        z = 5.0
        c, idx = join(ring(z), quads(*([wall_below(s, 4, 6, 4, 6, z) for s in self.SIDES]
                                       + [wall_above(s, 0, 10, 0, 10, z) for s in self.SIDES])))
        st = A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0)[3]
        self.assertEqual(st['bridge'], 0.0)
        self.assertAlmostEqual(st['overhang'], 96.0)

    def test_pillar_in_a_closed_ceiling(self):
        z = 5.0
        c, idx = join(ring(z), quads(*([wall_below(s, 0, 10, 0, 10, z) for s in self.SIDES]
                                       + [wall_below(s, 4, 6, 4, 6, z) for s in self.SIDES])))
        st = A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0)[3]
        self.assertAlmostEqual(st['bridge'], 96.0)
        self.assertAlmostEqual(st['span'], 10.0)   # las líneas que no pasan por la columna van de pared a pared

    def test_ceiling_on_the_bed_is_not_a_bridge(self):
        r = (3.0, 7.0, 0.0, 20.0, 0.0)
        c, idx = quads(ceiling(*r), wall_above('y0', *r))
        st = A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0)[3]
        self.assertAlmostEqual(st['bed'], 80.0)
        self.assertEqual(st['bridge'], 0.0)

    def test_wall_with_other_nodes_along_the_edge(self):
        # Fusion discretiza por separado las dos caras de una arista
        x0, x1, y0, y1, z = self.R
        faces = [ceiling(*self.R)]
        for ya, yb in ((y0, 8.0), (8.0, y1)):
            faces += [wall_below('x0', x0, x1, ya, yb, z), wall_below('x1', x0, x1, ya, yb, z)]
        c, idx = quads(*faces)
        self.assertAlmostEqual(A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0)[3]['span'], 4.0)

    def test_curved_wall_within_mesh_tolerance(self):
        # la cuerda de la pared queda a 0,05 de la del techo: hace falta edge_tol
        x0, x1, y0, y1, z = self.R
        c, idx = quads(ceiling(*self.R), wall_below('x0', x0 - 0.05, x1, y0, y1, z), wall_below('x1', *self.R))
        self.assertEqual(A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0)[3]['bridge'], 0.0)
        self.assertAlmostEqual(A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0, edge_tol=0.06)[3]['span'], 4.0)

    def test_other_up_direction(self):
        # el mismo techo con Y arriba: (x, y, z) -> (x, z, -y)
        faces = [ceiling(*self.R), wall_below('x0', *self.R), wall_below('x1', *self.R)]
        c, idx = quads(*[[[p[0], p[2], -p[1]] for p in f] for f in faces])
        st = A.classify(c, [], idx, (0.0, 1.0, 0.0), 0.0, 45, bridge_max=23.0)[3]
        self.assertAlmostEqual(st['span'], 4.0)

    def test_flat_facet_on_top_of_an_arch_is_not_a_bridge(self):
        # arco facetado: al lado de la faceta plana, las caras bajan 20° y son voladizo
        z = 5.0
        d = 2.0 * math.tan(math.radians(20))
        left = [[3, 0, z], [1, 0, z - d], [1, 20, z - d], [3, 20, z]]
        right = [[7, 0, z], [7, 20, z], [9, 20, z - d], [9, 0, z - d]]
        c, idx = quads(ceiling(*self.R), left, right)
        st = A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0)[3]
        self.assertEqual(st['bridge'], 0.0)
        self.assertAlmostEqual(st['worst'], 0.0)

    def test_teardrop_slopes_at_the_limit_hold_a_bridge(self):
        # gota con techo plano: las caras de al lado bajan a 45° y con límite de 45° no son voladizo
        z = 5.0
        left = [[3, 0, z], [1, 0, z - 2], [1, 20, z - 2], [3, 20, z]]
        right = [[7, 0, z], [7, 20, z], [9, 20, z - 2], [9, 0, z - 2]]
        c, idx = quads(ceiling(*self.R), left, right)
        self.assertAlmostEqual(A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0)[3]['span'], 4.0)

    def test_sliver_narrower_than_the_mesh_tolerance_is_not_a_bridge(self):
        # tira de 0,1 de ancho al lado de una pared: con edge_tol = 0,12 sus dos bordes parecen apoyados
        z = 5.0
        c, idx = quads(ceiling(3.0, 3.1, 0.0, 20.0, z), wall_below('x0', 3.0, 3.1, 0.0, 20.0, z))
        st = A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0, edge_tol=0.12)[3]
        self.assertEqual(st['bridge'], 0.0)
        self.assertIsNone(st['span'])

    def test_skew_window(self):
        # techo en rombo: las paredes no son perpendiculares a los bordes libres
        z = 5.0
        roof = [[0, 0, z], [6, 10, z], [10, 10, z], [4, 0, z]]
        jamb1 = [[0, 0, z], [0, 0, 3], [6, 10, 3], [6, 10, z]]
        jamb2 = [[4, 0, z], [4, 0, 3], [10, 10, 3], [10, 10, z]]
        c, idx = quads(roof, jamb1, jamb2)
        st = A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0)[3]
        self.assertGreater(st['bridge'], 0.0)
        self.assertAlmostEqual(st['span'], 4.0 * 10 / math.hypot(6, 10))   # perpendicular a las paredes

    def test_window_in_a_curved_wall(self):
        # el extremo libre del techo va en diagonal: las líneas de esa zona acaban en él
        z = 5.0
        roof = [[0, 0, z], [0, 20, z], [10, 16, z], [10, 4, z]]
        c, idx = quads(roof, wall_below('x0', 0, 10, 0, 20, z), wall_below('x1', 0, 10, 4, 16, z))
        st = A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0)[3]
        self.assertAlmostEqual(st['bridge'], 160.0)
        self.assertAlmostEqual(st['span'], 10.0)

    def test_wall_opposite_only_part_of_the_way_is_not_a_bridge(self):
        # el 40 % del techo llega a un borde libre de través: es un voladizo aunque casi todo lo demás apoye
        z = 5.0
        coords = []
        for x, y in ((0, 0), (0, 20), (10, 20), (10, 12), (10, 0)):
            coords += [float(x), float(y), z]
        idx = [0, 1, 2, 0, 2, 3, 0, 3, 4]
        c, i = join((coords, idx), quads(wall_below('x0', 0, 10, 0, 20, z), wall_below('x1', 0, 10, 0, 12, z)))
        self.assertEqual(A.classify(c, [], i, UP, 0.0, 45, bridge_max=23.0)[3]['bridge'], 0.0)

    def test_triangular_balcony_is_not_a_bridge(self):
        # pared por un lado y dos bordes libres en diagonal: ninguna línea llega a otra pared
        z = 5.0
        c, idx = quads([[0, 0, z], [0, 20, z], [10, 10, z], [10, 10, z]], wall_below('x0', 0, 10, 0, 20, z))
        self.assertEqual(A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0)[3]['bridge'], 0.0)

    def test_short_wall_opposite_a_long_one_is_not_a_bridge(self):
        # la pared de enfrente solo sostiene la cuarta parte: el resto queda en el aire
        z = 5.0
        roof = [[0, 0, z], [0, 20, z], [10, 12.5, z], [10, 7.5, z]]
        c, idx = quads(roof, wall_below('x0', 0, 10, 0, 20, z), wall_below('x1', 0, 10, 7.5, 12.5, z))
        self.assertEqual(A.classify(c, [], idx, UP, 0.0, 45, bridge_max=23.0)[3]['bridge'], 0.0)


class OffsetTest(unittest.TestCase):
    def test_moves_along_unit_normal(self):
        out = A.offset([1.0, 2.0, 3.0, 0.0, 0.0, 0.0], [0.0, 0.0, 2.0, 3.0, 4.0, 0.0], 0.5)
        for got, want in zip(out, [1.0, 2.0, 3.5, 0.3, 0.4, 0.0]):
            self.assertAlmostEqual(got, want)

    def test_flat_triangle_barely_moves_with_a_coarse_display(self):
        c = [0.0, 0.0, 5.0, 4.0, 0.0, 5.0, 0.0, 4.0, 5.0]
        out = A.lift_layer(c, [0.0, 0.0, -1.0] * 3, 0.05)
        for k in (2, 5, 8):
            self.assertAlmostEqual(out[k], 5.0 - A.lift(0.0, 0.0))

    def test_curved_triangle_moves_past_its_real_chord_gap(self):
        # cuerda de 90° en un círculo de radio 2: se aparta 2·(1 - cos 45°) en el centro, 0,586
        r2 = math.sqrt(0.5)
        c = [2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 2.0, 0.0, 1.0]
        n = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0]
        out = A.lift_layer(c, n, 0.001)
        moved = out[0] - c[0]
        self.assertGreater(moved, 2 * (1 - r2))
        self.assertLess(moved, 1.2 * 2 * (1 - r2))
        self.assertAlmostEqual(out[4] - c[4], moved)

    def test_long_diagonal_of_a_cylinder_does_not_count_along_the_axis(self):
        # triángulo largo en un cilindro de radio 1, con cuerdas de 30°: lo que se aparta no depende del largo
        a = math.radians(30)
        ca, sa = math.cos(a), math.sin(a)
        short = A.lift_layer([1.0, 0, 0, ca, sa, 0, 1.0, 0, 1.0], [1.0, 0, 0, ca, sa, 0, 1.0, 0, 0], 0.001)
        long_ = A.lift_layer([1.0, 0, 0, ca, sa, 100.0, 1.0, 0, 200.0], [1.0, 0, 0, ca, sa, 0, 1.0, 0, 0], 0.001)
        self.assertAlmostEqual(short[0], long_[0])
        self.assertLess(long_[0] - 1.0, 1.2 * (1 - math.cos(a / 2)) + 0.002)

    def test_limit_caps_the_lift_of_curved_triangles(self):
        n = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0]
        out = A.lift_layer([2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 2.0, 0.0, 1.0], n, 0.001, limit=0.1)
        self.assertAlmostEqual(out[0], 2.1)

    def test_curved_neighbours_move_the_same_so_no_cracks_open(self):
        # dos triángulos curvos de distinto tamaño y uno plano
        n1 = A.unit((1.0, 0.1, 0.0))
        n2 = A.unit((1.0, 0.4, 0.0))
        c = [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0,
             0.0, 0.0, 0.0, 0.0, 9.0, 0.0, 0.0, 0.0, 1.0,
             5.0, 0.0, 0.0, 5.0, 1.0, 0.0, 5.0, 0.0, 1.0]
        n = [1.0, 0.0, 0.0] + list(n1) + [1.0, 0.0, 0.0] + [1.0, 0.0, 0.0] + list(n2) + [1.0, 0.0, 0.0] + [1.0, 0.0, 0.0] * 3
        out = A.lift_layer(c, n, 0.001)
        self.assertAlmostEqual(out[0], out[9])
        self.assertGreater(out[0], 0.1)
        self.assertAlmostEqual(out[18] - 5.0, A.lift(0.0, 0.0))

    def test_curved_triangle_clears_the_display_mesh(self):
        # curva casi nada, pero la malla de Fusion puede quedar más afuera: manda su tolerancia
        n1 = A.unit((1.0, 0.01, 0.0))
        c = [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        n = [1.0, 0.0, 0.0] + list(n1) + [1.0, 0.0, 0.0]
        out = A.lift_layer(c, n, 0.05)
        self.assertGreater(out[0], 0.05)

    def test_lift_covers_coarser_mesh(self):
        self.assertGreater(A.lift(0.07, 0.009), 0.07)
        self.assertGreater(A.lift(0.002, 0.009), 0.009)
        self.assertGreater(A.lift(0.0, 0.0), 0.0)


if __name__ == '__main__':
    unittest.main()
