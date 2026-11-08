# Pruebas de overhang/slicer.py sin Fusion:  python -m unittest discover -s tests
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from overhang import slicer as S  # noqa: E402
from overhang import thickness as T  # noqa: E402


def square():
    """Cuadrado de lado 1 cm en z=0, mirando hacia arriba, con cuatro nodos y dos triángulos."""
    return [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0], [0, 1, 2, 0, 2, 3]


class BedTest(unittest.TestCase):
    def test_planes(self):
        self.assertEqual(S.bed_vector('z'), [0.0, 0.0, -1.0])
        self.assertEqual(S.bed_vector('y'), [0.0, -1.0, 0.0])

    def test_face_is_normalised(self):
        self.assertEqual(S.bed_vector('face', [0, 0, -2]), [0.0, 0.0, -1.0])


class GeometryTest(unittest.TestCase):
    def test_face_in_mm(self):
        c, idx = square()
        f = S.face(c, idx, 1.0)
        self.assertEqual(f['vertices'][2], [10.0, 10.0, 0.0])
        self.assertEqual(f['triangles'], [[0, 1, 2], [0, 2, 3]])
        self.assertEqual(f['area'], 100.0)

    def test_edge_in_mm(self):
        self.assertEqual(S.edge([(0, 0, 0), (0.1, 0.2, 0.3)]), [[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]])

    def test_patch_keeps_only_used_nodes_and_order(self):
        c, idx = square()
        p = S.patch(c, idx, [1])
        self.assertEqual(p['triangles'], [[0, 1, 2]])
        self.assertEqual(p['vertices'], [[0.0, 0.0, 0.0], [10.0, 10.0, 0.0], [0.0, 10.0, 0.0]])

    def test_empty_patch(self):
        c, idx = square()
        self.assertIsNone(S.patch(c, idx, []))


class TightTest(unittest.TestCase):
    def test_contact_overlap_and_below_limit(self):
        vals = [0.0, 0.0, 0.05, 0.2, T.NO_HIT, 0.0999]
        kinds = [T.CONTACT, T.OVERLAP, T.GAP, T.GAP, T.GAP, T.GAP]
        # 0,0999 en un límite de 0,1 no cuenta con el margen de la malla, como en la medida de Espacio
        self.assertEqual(S.tight_triangles(vals, kinds, 0.1, 0.001), [0, 1, 2])


class JobTest(unittest.TestCase):
    def test_only_what_is_given(self):
        sel = S.selection(edges=[[[0, 0, 0], [1, 0, 0]]])
        job = S.job('Pieza', [0, 0, -1], seam_enforce=sel, seam_block=None)
        self.assertEqual(job, {'version': 3, 'units': 'mm', 'body': 'Pieza', 'bed': [0, 0, -1],
                               'seam': {'enforce': {'edges': [[[0, 0, 0], [1, 0, 0]]]}}})
        self.assertEqual(S.counts(job)[('seam', 'enforce')], (1, 0, 0))

    def test_empty_selection_is_none(self):
        self.assertIsNone(S.selection([], [], []))

    def test_needs_something(self):
        with self.assertRaises(ValueError):
            S.job('Pieza')

    def test_unknown_role(self):
        with self.assertRaises(TypeError):
            S.job('Pieza', [0, 0, -1], seam_somewhere=None)


class FilesTest(unittest.TestCase):
    def test_paths(self):
        stl, job, out = S.paths(os.path.join('a', 'Pieza.3mf'))
        self.assertEqual((os.path.basename(stl), os.path.basename(job), os.path.basename(out)),
                         ('Pieza.stl', 'Pieza.json', 'Pieza.3mf'))

    def test_command(self):
        self.assertEqual(S.command('sp', 'a.stl', 'a.json', 'a.3mf', 'orca'),
                         ['sp', 'a.stl', '-o', 'a.3mf', '--fusion', 'a.json', '--open', 'orca'])
        self.assertNotIn('--open', S.command('sp', 'a.stl', 'a.json', 'a.3mf'))

    def test_looks_like_exe(self):
        with tempfile.TemporaryDirectory() as d:
            good, other = os.path.join(d, 'Slicer-Paint.exe'), os.path.join(d, 'python.exe')
            for path in (good, other):
                open(path, 'wb').close()
            self.assertTrue(S.looks_like_exe(good))
            self.assertFalse(S.looks_like_exe(other))
            self.assertFalse(S.looks_like_exe(os.path.join(d, 'otra', 'slicer-paint.exe')))   # no existe

    def test_stl_bounds_binary_and_match(self):
        tris = [((0, 0, 1), (1.0, 2.0, 3.0), (11.0, 2.0, 3.0), (1.0, 22.0, 33.0))]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'a.stl')
            with open(path, 'wb') as f:
                f.write(b'\0' * 80 + struct.pack('<I', len(tris)))
                for t in tris:
                    f.write(struct.pack('<12fH', *[v for p in t for v in p], 0))
            box = S.stl_bounds(path)
        self.assertEqual(box, ((1.0, 2.0, 3.0), (11.0, 22.0, 33.0)))
        self.assertTrue(S.bounds_match(box, ((0.1, 0.2, 0.3), (1.1, 2.2, 3.3))))
        self.assertFalse(S.bounds_match(box, ((1.0, 2.0, 3.0), (11.0, 22.0, 33.0))))   # en cm por error

    def test_move_stl(self):
        # giro de 90° alrededor de Z y traslación de (3, 2, 0) cm
        m = [0, -1, 0, 3, 1, 0, 0, 2, 0, 0, 1, 0, 0, 0, 0, 1]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'a.stl')
            with open(path, 'wb') as f:
                f.write(b'\0' * 80 + struct.pack('<I', 1))
                f.write(struct.pack('<12fH', 0, 0, 1, 0, 0, 0, 40, 0, 0, 0, 30, 20, 0))
            S.move_stl(path, m)
            with open(path, 'rb') as f:
                v = struct.unpack_from('<12f', f.read(), 84)
        self.assertEqual([round(x, 4) for x in v], [0, 0, 1, 30, 20, 0, 30, 60, 0, 0, 20, 20])

    def test_stl_bounds_text(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'a.stl')
            with open(path, 'w') as f:
                f.write('solid a\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 2 0\n'
                        'endloop\nendfacet\nendsolid a\n')
            self.assertEqual(S.stl_bounds(path), ((0.0, 0.0, 0.0), (1.0, 2.0, 0.0)))


if __name__ == '__main__':
    unittest.main()
