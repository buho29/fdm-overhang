# Pruebas de overhang/pick.py sin Fusion:  python -m unittest discover -s tests
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from overhang import pick as P  # noqa: E402


class RolesTest(unittest.TestCase):
    def test_api_names_and_fields(self):
        self.assertEqual(P.role_key('seam_on'), 'sl_seam_on')
        self.assertEqual(P.role_key('support_off'), 'sl_sup_off')
        self.assertEqual(P.role_key('sl_sup_on'), 'sl_sup_on')

    def test_unknown_role(self):
        with self.assertRaises(ValueError):
            P.role_key('costura')

    def test_names_back(self):
        self.assertEqual(P.role_name('sl_seam_off'), 'seam_off')
        self.assertEqual(P.role_name('sl_face'), 'bed')
        self.assertEqual(P.role_name('otro'), 'otro')


class DirectionTest(unittest.TestCase):
    def test_up_and_down_follow_the_bed(self):
        self.assertEqual(P.direction('up', (0, 1, 0)), (0.0, 1.0, 0.0))
        self.assertEqual(P.direction('down', (0, 0, 2)), (0.0, 0.0, -1.0))

    def test_vector(self):
        self.assertEqual(P.direction((3, 0, 0), (0, 0, 1)), (1.0, 0.0, 0.0))

    def test_bad(self):
        with self.assertRaises(ValueError):
            P.direction('left', (0, 0, 1))
        with self.assertRaises(ValueError):
            P.direction((0, 0, 0), (0, 0, 1))

    def test_facing_has_a_sense(self):
        self.assertTrue(P.facing((0, 0, -1), (0, 0, -1), 5))
        self.assertTrue(P.facing((0.05, 0, -1), (0, 0, -1), 5))
        self.assertFalse(P.facing((0, 0, 1), (0, 0, -1), 5))

    def test_parallel_both_senses(self):
        self.assertTrue(P.parallel((0, 0, -1), (0, 0, 1), 1))
        self.assertFalse(P.parallel((1, 0, 1), (0, 0, 1), 10))


class BoxTest(unittest.TestCase):
    def test_inside_in_mm(self):
        self.assertTrue(P.in_box((0, 0, 0), (1, 1, 1), ((0, 0, 0), (10, 10, 10))))
        self.assertFalse(P.in_box((0, 0, 0), (1, 1, 1.1), ((0, 0, 0), (10, 10, 10))))

    def test_open_limits(self):
        self.assertTrue(P.in_box((0, 0, 5), (1, 1, 6), ((None, None, 40), None)))
        self.assertFalse(P.in_box((0, 0, 3), (1, 1, 6), ((None, None, 40), None)))
        self.assertTrue(P.in_box((0, 0, 0), (1, 1, 1), None))


class ColorTest(unittest.TestCase):
    def test_same_color(self):
        self.assertTrue(P.same_color('#ff0000', 'FF0000'))
        self.assertFalse(P.same_color('#FF0000', '#00FF00'))
        self.assertTrue(P.same_color(None, None))
        self.assertFalse(P.same_color(None, '#FF0000'))


if __name__ == '__main__':
    unittest.main()
