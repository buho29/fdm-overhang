"""Lectura de la pintura de un 3MF, para verificar lo que conserva un slicer."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np


@dataclass
class PaintedMesh:
    source: str
    vertices: np.ndarray
    faces: np.ndarray
    # Tipo de pintura -> {índice de triángulo -> cadena}.
    paint: dict[str, dict[int, str]] = field(default_factory=dict)

    def centroids(self, indices: list[int]) -> np.ndarray:
        return self.vertices[self.faces[indices]].mean(axis=1)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_transform(text: str | None) -> np.ndarray:
    """Convierte la matriz 3x4 de 3MF en una 4x4 de vector columna."""
    m = np.eye(4)
    if text:
        v = [float(x) for x in text.split()]
        m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = v[0:3], v[3:6], v[6:9], v[9:12]
    return m


def _read_meshes(data: bytes, source: str) -> dict[str, PaintedMesh]:
    """Lee las mallas de un .model con iterparse, sin cargar el árbol entero."""
    meshes: dict[str, PaintedMesh] = {}
    obj_id = None
    verts: list[tuple[float, float, float]] = []
    tris: list[tuple[int, int, int]] = []
    paint: dict[str, dict[int, str]] = {}
    for event, el in ET.iterparse(io.BytesIO(data), events=("start", "end")):
        name = _local(el.tag)
        if event == "start":
            if name == "object":
                obj_id, verts, tris, paint = el.get("id"), [], [], {}
            continue
        if name == "vertex":
            verts.append((float(el.get("x")), float(el.get("y")), float(el.get("z"))))
        elif name == "triangle":
            for key, value in el.attrib.items():
                if key.startswith("paint_") and value:
                    paint.setdefault(key, {})[len(tris)] = value
            tris.append((int(el.get("v1")), int(el.get("v2")), int(el.get("v3"))))
        elif name == "object" and tris:
            meshes[obj_id] = PaintedMesh(source, np.array(verts), np.array(tris), paint)
        if name in ("vertex", "triangle"):
            el.clear()
    return meshes


def read_painted(path: str | Path) -> list[PaintedMesh]:
    """Devuelve las mallas del 3MF con los vértices en coordenadas de la cama."""
    result: list[PaintedMesh] = []
    with zipfile.ZipFile(path) as z:
        external = {n: _read_meshes(z.read(n), n) for n in z.namelist()
                    if n.startswith("3D/Objects/") and n.endswith(".model")}
        main = z.read("3D/3dmodel.model")
        local_meshes = _read_meshes(main, "3D/3dmodel.model")
        root = ET.fromstring(main)
        components: dict[str, list[tuple[str | None, str, np.ndarray]]] = {}
        for obj in root.iter():
            if _local(obj.tag) != "object":
                continue
            for comp in obj.iter():
                if _local(comp.tag) == "component":
                    comp_path = next((v for k, v in comp.attrib.items()
                                      if _local(k) == "path"), None)
                    components.setdefault(obj.get("id"), []).append(
                        (comp_path, comp.get("objectid"), _parse_transform(comp.get("transform"))))
        for item in root.iter():
            if _local(item.tag) != "item":
                continue
            item_m = _parse_transform(item.get("transform"))
            oid = item.get("objectid")
            for comp_path, comp_id, comp_m in components.get(oid) or [(None, oid, np.eye(4))]:
                src = external.get(comp_path.lstrip("/"), {}) if comp_path else local_meshes
                mesh = src.get(comp_id)
                if mesh is None:
                    continue
                m = item_m @ comp_m
                world = (m[:3, :3] @ mesh.vertices.T).T + m[:3, 3]
                result.append(PaintedMesh(mesh.source, world, mesh.faces, mesh.paint))
    return result
