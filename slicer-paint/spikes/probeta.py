"""Probeta: una T con voladizos de 60° a ambos lados y un cilindro para la costura."""
from __future__ import annotations

import numpy as np
import trimesh
from shapely.geometry import Polygon

STEM_HALF = 10.0
STEM_HEIGHT = 20.0
ARM_RISE = 15.0
ARM_TOP = 5.0
OVERHANG_DEG = 60.0
DEPTH = 20.0
CYLINDER_X = 75.0


def probeta() -> trimesh.Trimesh:
    """Devuelve la malla con Z mínima 0: la T centrada en X=0 y el cilindro aparte."""
    run = ARM_RISE * np.tan(np.radians(OVERHANG_DEG))
    h = STEM_HEIGHT
    profile = Polygon([
        (-STEM_HALF, 0), (STEM_HALF, 0), (STEM_HALF, h),
        (STEM_HALF + run, h + ARM_RISE), (STEM_HALF + run, h + ARM_RISE + ARM_TOP),
        (-STEM_HALF - run, h + ARM_RISE + ARM_TOP), (-STEM_HALF - run, h + ARM_RISE),
        (-STEM_HALF, h),
    ])
    t = trimesh.creation.extrude_polygon(profile, DEPTH)
    # El perfil se dibuja en XY y se extruye en Z: se gira para que sea XZ extruido en Y.
    t.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    t.apply_translation([0, DEPTH / 2, 0])

    cyl = trimesh.creation.cylinder(radius=8.0, height=30.0, sections=48)
    cyl.apply_translation([CYLINDER_X, 0, 15.0])
    mesh = trimesh.util.concatenate([t, cyl])
    mesh.fix_normals()
    return mesh


def side_overhang_masks(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """Triángulos de los voladizos inclinados del lado -X y del lado +X."""
    normals, centers = mesh.face_normals, mesh.triangles_center
    down = (normals[:, 2] < -0.1) & (centers[:, 2] > 1.0) & (centers[:, 0] < CYLINDER_X - 20)
    return down & (centers[:, 0] < 0), down & (centers[:, 0] > 0)


def cylinder_back_mask(mesh: trimesh.Trimesh) -> np.ndarray:
    """Caras laterales del cilindro orientadas a +Y, en un sector estrecho."""
    normals, centers = mesh.face_normals, mesh.triangles_center
    on_cyl = centers[:, 0] > CYLINDER_X - 20
    side = np.abs(normals[:, 2]) < 0.1
    return on_cyl & side & (normals[:, 1] > 0.95)
