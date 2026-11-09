"""Lectura de lo elegido en Fusion: la selección de fusion/export_selection.py y el archivo de pieza.

Una selección (versión 2) tiene aristas y caras, y su papel lo decide la opción que la usa:
--seam, --seam-block, --support-enforce o --support-block. El archivo de pieza (versión 3) lo
lleva todo junto: la cara de cama y una selección para cada papel. Los dos formatos están
descritos en docs/formato-fusion.md.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

DEFAULT_RADIUS = 0.5
JOB_VERSION = 3
_SELECTION_KEYS = {"edges", "faces", "patches"}
_JOB_KEYS = {"version", "units", "body", "bed", "seam", "support"}
_ROLES = ("enforce", "block")


@dataclass
class Face:
    """Malla de una cara de Fusion y su área exacta, en mm."""
    vertices: np.ndarray
    triangles: np.ndarray
    area: float


@dataclass
class Patch:
    """Trozo de superficie que no es una cara entera, como lo estrecho de una medida de espacio.

    Los triángulos van orientados hacia fuera del cuerpo, como los da Fusion.
    """
    vertices: np.ndarray
    triangles: np.ndarray


@dataclass
class Selection:
    edges: list[np.ndarray] = field(default_factory=list)
    faces: list[Face] = field(default_factory=list)
    patches: list[Patch] = field(default_factory=list)

    def moved(self, transform) -> "Selection":
        """La misma selección con transform aplicado a todos los puntos."""
        return Selection([transform(e) for e in self.edges],
                         [Face(transform(f.vertices), f.triangles, f.area) for f in self.faces],
                         [Patch(transform(p.vertices), p.triangles) for p in self.patches])

    def is_empty(self) -> bool:
        return not (self.edges or self.faces or self.patches)


@dataclass
class Job:
    """Archivo de pieza: cara de cama y una selección por papel, en las coordenadas del STL."""
    body: str | None = None
    # Normal hacia fuera de la cara que va sobre la cama.
    bed: np.ndarray | None = None
    seam: dict[str, Selection] = field(default_factory=dict)
    support: dict[str, Selection] = field(default_factory=dict)


def _mesh(raw: dict, where: str) -> tuple[np.ndarray, np.ndarray]:
    try:
        vertices = np.array(raw["vertices"], dtype=float)
        triangles = np.array(raw["triangles"], dtype=int)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{where} mal formada: {exc}") from exc
    if (vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2
            or triangles.shape[1] != 3 or len(triangles) == 0
            or triangles.min() < 0 or triangles.max() >= len(vertices)):
        raise ValueError(f"{where} mal formada")
    return vertices, triangles


def parse_selection(data, path: str | Path, where: str = "") -> Selection:
    """Selección a partir de un diccionario con edges, faces y patches; puede quedar vacía."""
    prefix = f"{path}{where}"
    if not isinstance(data, dict):
        raise ValueError(f"{prefix}: se esperaba un objeto con edges, faces o patches")
    unknown = set(data) - _SELECTION_KEYS - {"version", "units", "body"}
    if unknown:
        raise ValueError(f"{prefix}: claves desconocidas {sorted(unknown)}")
    selection = Selection()
    for points in data.get("edges", []):
        polyline = np.array(points, dtype=float)
        if polyline.ndim != 2 or polyline.shape[1] != 3 or len(polyline) < 2:
            raise ValueError(f"{prefix}: una arista necesita al menos dos puntos x,y,z")
        selection.edges.append(polyline)
    for raw in data.get("faces", []):
        vertices, triangles = _mesh(raw, f"{prefix}: cara")
        try:
            area = float(raw["area"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{prefix}: cara mal formada: {exc}") from exc
        selection.faces.append(Face(vertices, triangles, area))
    for raw in data.get("patches", []):
        selection.patches.append(Patch(*_mesh(raw, f"{prefix}: zona")))
    return selection


def _read_json(path: str | Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} no es un JSON válido: {exc}") from exc


def load_selection(path: str | Path) -> Selection:
    data = _read_json(path)
    if isinstance(data, dict) and data.get("version") == JOB_VERSION:
        raise ValueError(f"{path} es un archivo de pieza: se usa con --fusion, no con fusion:")
    selection = parse_selection(data, path)
    if selection.is_empty():
        raise ValueError(f"{path} no tiene ninguna arista, cara ni zona")
    return selection


def load_job(path: str | Path) -> Job:
    data = _read_json(path)
    if not isinstance(data, dict) or data.get("version") != JOB_VERSION:
        raise ValueError(f"{path} no es un archivo de pieza de la versión {JOB_VERSION}")
    unknown = set(data) - _JOB_KEYS
    if unknown:
        raise ValueError(f"{path}: claves desconocidas {sorted(unknown)}")
    if data.get("units", "mm") != "mm":
        raise ValueError(f"{path}: las unidades tienen que ser mm")
    job = Job(body=data.get("body"))
    if data.get("bed") is not None:
        bed = np.array(data["bed"], dtype=float)
        if bed.shape != (3,) or not np.isfinite(bed).all() or np.linalg.norm(bed) < 1e-9:
            raise ValueError(f"{path}: bed tiene que ser una dirección x,y,z")
        job.bed = bed / np.linalg.norm(bed)
    for kind in ("seam", "support"):
        roles = data.get(kind, {})
        if not isinstance(roles, dict) or set(roles) - set(_ROLES):
            raise ValueError(f"{path}: {kind} solo admite enforce y block")
        for role in _ROLES:
            if role in roles:
                chosen = parse_selection(roles[role], path, f" ({kind}.{role})")
                if not chosen.is_empty():
                    getattr(job, kind)[role] = chosen
    if job.bed is None and not job.seam and not job.support:
        raise ValueError(f"{path} no tiene cama, costura ni soportes")
    return job
