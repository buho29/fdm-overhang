"""Carga y limpieza de mallas."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from .reader import read_painted


def clean(vertices: np.ndarray, faces: np.ndarray) -> trimesh.Trimesh:
    """Une vértices y quita caras degeneradas o repetidas.

    Se hace antes de pintar: si el slicer las quitara al cargar, los triángulos
    pintados se desplazarían respecto a la malla.
    """
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    if not mesh.is_winding_consistent:
        mesh.fix_normals()
    return mesh


def load_mesh(path: str | Path, part: str | None = None) -> trimesh.Trimesh:
    """Carga un STL u otra malla, o una pieza de un 3MF por el nombre de su archivo interno."""
    path = Path(path)
    if path.suffix.lower() == ".3mf":
        meshes = read_painted(path)
        if part is not None:
            meshes = [m for m in meshes if part in m.source]
        if not meshes:
            raise ValueError(f"No hay ninguna pieza {part!r} en {path}")
        if len(meshes) > 1 and part is None:
            names = sorted({m.source for m in meshes})
            raise ValueError(f"{path} tiene varias piezas; elige una con --part: {names}")
        return clean(meshes[0].vertices, meshes[0].faces)
    loaded = trimesh.load_mesh(path, process=False)
    return clean(loaded.vertices, loaded.faces)
