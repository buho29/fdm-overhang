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

    def test_plate_paths_do_not_collide(self):
        plate_path, out, parts = S.plate_paths(os.path.join('d', 'placa.3mf'), ['Caja', 'caja', 'Tapa: 2', 'Caja'])
        self.assertEqual((os.path.basename(plate_path), os.path.basename(out)), ('placa.json', 'placa.3mf'))
        self.assertEqual([os.path.basename(stl) for stl, _ in parts],
                         ['placa - Caja.stl', 'placa - caja (2).stl', 'placa - Tapa 2.stl', 'placa - Caja (3).stl'])
        self.assertEqual(os.path.basename(parts[0][1]), 'placa - Caja.json')

    def test_plate_file_and_command(self):
        _, _, parts = S.plate_paths(os.path.join('d', 'placa.3mf'), ['Caja'])
        self.assertEqual(S.plate(['Caja'], parts),
                         {'version': 1, 'units': 'mm',
                          'parts': [{'stl': 'placa - Caja.stl', 'fusion': 'placa - Caja.json', 'name': 'Caja'}]})
        self.assertEqual(S.plate_command('sp', 'p.json', 'p.3mf', 'bambu'),
                         ['sp', '--plate', 'p.json', '-o', 'p.3mf', '--open', 'bambu'])

    def test_roles_attribute(self):
        self.assertEqual(S.role_value(['sl_sup_off', 'sl_seam_off', 'sl_sup_off']), 'sl_seam_off,sl_sup_off')
        self.assertEqual(S.role_keys('sl_seam_off,sl_sup_off'), ['sl_seam_off', 'sl_sup_off'])
        self.assertEqual(S.role_keys(''), [])

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

    def test_write_stl(self):
        c, idx = square()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'a.stl')
            S.write_stl(path, c, idx)
            with open(path, 'rb') as f:
                data = f.read()
            self.assertEqual(len(data), 84 + 50 * 2)
            self.assertEqual(struct.unpack_from('<I', data, 80)[0], 2)
            self.assertEqual(struct.unpack_from('<12f', data, 84), (0, 0, 1, 0, 0, 0, 10, 0, 0, 10, 10, 0))
            self.assertEqual(S.stl_bounds(path), ((0.0, 0.0, 0.0), (10.0, 10.0, 0.0)))

    def test_stl_bounds_text(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'a.stl')
            with open(path, 'w') as f:
                f.write('solid a\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 2 0\n'
                        'endloop\nendfacet\nendsolid a\n')
            self.assertEqual(S.stl_bounds(path), ((0.0, 0.0, 0.0), (1.0, 2.0, 0.0)))

    def test_appearance_rgb_picks_the_main_colour(self):
        # Valores leídos de la biblioteca de aspectos de Fusion.
        steel = [('metal_f0', (160, 160, 160)), ('surface_albedo', (255, 255, 255))]
        abs_white = [('opaque_albedo', (246, 246, 243)), ('opaque_luminance_modifier', (255, 255, 255)),
                     ('surface_albedo', (255, 255, 255))]
        carbon = [('layered_bottom_f0', None), ('layered_diffuse', (25, 25, 25)), ('surface_albedo', (255, 255, 255))]
        walnut = [('surface_albedo', (255, 255, 255)), ('wood_early_color', (86, 58, 26))]
        self.assertEqual(S.appearance_rgb(steel), '#A0A0A0')   # el mismo que pone Fusion en su 3MF
        self.assertEqual(S.appearance_rgb(abs_white), '#F6F6F3')
        self.assertEqual(S.appearance_rgb(carbon), '#191919')
        self.assertEqual(S.appearance_rgb(walnut), '#563A1A')
        self.assertEqual(S.appearance_rgb([('otra', None), ('rara', (1, 2, 3))]), '#010203')
        self.assertEqual(S.appearance_rgb([('surface_albedo', (255, 255, 255))]), '#FFFFFF')
        self.assertIsNone(S.appearance_rgb([('opaque_albedo', None)]))

    def test_palette_numbers_colours_in_order(self):
        pal = S.palette([('#0000FF', ['#FF0000', '#00FF00', '#FF0000']), ('#00FF00', [None])])
        self.assertEqual(pal, {'#0000FF': 1, '#FF0000': 2, '#00FF00': 3, None: 4})
        with self.assertRaises(ValueError):
            S.palette([('#%06X' % i, []) for i in range(S.MAX_FILAMENT + 1)])

    def test_color_section_and_job(self):
        pal = {'#0000FF': 1, '#FF0000': 2, None: 3}
        face = {'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'triangles': [[0, 1, 2]], 'area': 0.5}
        color = S.color_section('#FF0000', [('#0000FF', [face]), (None, [face]), ('#00FF00', [])], pal)
        self.assertEqual(color, {'body': {'filament': 2, 'rgb': '#FF0000'},
                                 'paint': [{'filament': 1, 'rgb': '#0000FF', 'faces': [face]},
                                           {'filament': 3, 'faces': [face]}]})
        self.assertEqual(S.color_section('#0000FF', [], pal), {'body': {'filament': 1, 'rgb': '#0000FF'}})
        self.assertEqual(S.job('Caja', color=color)['color'], color)
        self.assertNotIn('color', S.job('Caja', [0, 0, -1]))


if __name__ == '__main__':
    unittest.main()
