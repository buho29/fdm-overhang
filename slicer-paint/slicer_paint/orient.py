"""Orientación de la pieza para imprimirla."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

DEFAULT_OVERHANG_DEG = 45.0
# Tolerancia para considerar que un triángulo apoya en la cama (mm).
BED_EPS = 0.05
# Una cara cuenta como apoyo si su normal se separa menos de esto de -Z.
_CONTACT_COS = np.cos(np.radians(2.0))
_MAX_CANDIDATES = 64
_AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0),
         "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}


@dataclass
class OrientationScore:
    rotation: np.ndarray
    overhang_area: float
    contact_area: float
    height: float
    score: float


def overhang_mask(normals: np.ndarray, centers_z: np.ndarray, bed_z: float,
                  limit_deg: float) -> np.ndarray:
    """Caras que vuelan más de limit_deg respecto a la vertical, sin contar las de la cama.

    El ángulo se mide desde la vertical: 0° es una pared y 90° un techo plano.
    """
    return (normals[:, 2] < -np.sin(np.radians(limit_deg))) & (centers_z > bed_z + BED_EPS)


def rotation_to_down(direction: np.ndarray) -> np.ndarray:
    """Rotación 3×3 que lleva direction a -Z, de modo que esa cara quede en la cama."""
    direction = np.asarray(direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    return trimesh.geometry.align_vectors(direction, np.array([0.0, 0.0, -1.0]))[:3, :3]


def evaluate(mesh: trimesh.Trimesh, rotation: np.ndarray, limit_deg: float) -> OrientationScore:
    normals = mesh.face_normals @ rotation.T
    centers = mesh.triangles_center @ rotation.T
    z_values = mesh.vertices @ rotation.T
    z_min = z_values[:, 2].min()
    areas = mesh.area_faces
    overhang = areas[overhang_mask(normals, centers[:, 2], z_min, limit_deg)].sum()
    on_bed = (normals[:, 2] < -_CONTACT_COS) & (centers[:, 2] < z_min + BED_EPS)
    contact = areas[on_bed].sum()
    height = z_values[:, 2].max() - z_min
    # El voladizo manda: tu regla es imprimir sin soportes. Luego, buen apoyo y poca altura.
    score = overhang - 0.5 * contact + 0.01 * height * np.sqrt(mesh.area)
    return OrientationScore(rotation, float(overhang), float(contact), float(height), float(score))


def candidate_directions(mesh: trimesh.Trimesh) -> np.ndarray:
    """Normales de las mayores caras planas del casco convexo y los seis ejes."""
    hull = mesh.convex_hull
    order = np.argsort(hull.facets_area)[::-1][:_MAX_CANDIDATES]
    directions = [hull.facets_normal[order]] if len(order) else []
    directions.append(np.array(list(_AXES.values()), dtype=float))
    return np.concatenate(directions)


def auto_orient(mesh: trimesh.Trimesh, limit_deg: float = DEFAULT_OVERHANG_DEG) -> OrientationScore:
    """Elige la orientación con menos voladizo entre las candidatas."""
    scores = [evaluate(mesh, rotation_to_down(d), limit_deg) for d in candidate_directions(mesh)]
    return min(scores, key=lambda s: s.score)


def parse_orientation(spec: str, mesh: trimesh.Trimesh,
                      limit_deg: float = DEFAULT_OVERHANG_DEG) -> OrientationScore:
    """Interpreta --orient: auto, none, face:-z o face:x,y,z (la cara con esa normal a la cama)
    o rot:rx,ry,rz (grados)."""
    if spec == "auto":
        return auto_orient(mesh, limit_deg)
    if spec == "none":
        return evaluate(mesh, np.eye(3), limit_deg)
    kind, _, value = spec.partition(":")
    if kind == "face" and value in _AXES:
        return evaluate(mesh, rotation_to_down(np.array(_AXES[value], dtype=float)), limit_deg)
    if kind == "face":
        try:
            direction = np.array([float(v) for v in value.split(",")])
        except ValueError:
            direction = np.zeros(0)
        if direction.shape == (3,) and np.isfinite(direction).all() and np.linalg.norm(direction) > 1e-9:
            return evaluate(mesh, rotation_to_down(direction), limit_deg)
    if kind == "rot":
        angles = [np.radians(float(a)) for a in value.split(",")]
        if len(angles) == 3:
            matrix = trimesh.transformations.euler_matrix(*angles, axes="sxyz")[:3, :3]
            return evaluate(mesh, matrix, limit_deg)
    raise ValueError(f"Orientación no válida: {spec!r}. Usa auto, none, face:-z, face:0,0.7,-0.7 "
                     "o rot:90,0,0")


def apply_rotation(mesh: trimesh.Trimesh, rotation: np.ndarray) -> trimesh.Trimesh:
    """Devuelve una copia girada con Z mínima 0, conservando el orden de los triángulos."""
    vertices = mesh.vertices @ rotation.T
    vertices[:, 2] -= vertices[:, 2].min()
    return trimesh.Trimesh(vertices=vertices, faces=mesh.faces.copy(), process=False)


def transform_points(points: np.ndarray, mesh: trimesh.Trimesh, rotation: np.ndarray) -> np.ndarray:
    """Lleva puntos de la malla original a las coordenadas que le da apply_rotation."""
    moved = points @ rotation.T
    moved[:, 2] -= (mesh.vertices @ rotation.T)[:, 2].min()
    return moved
