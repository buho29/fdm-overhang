"""Archivo de placa: varias piezas, cada una con su STL y su archivo de pieza, en un solo 3MF.

El formato está descrito en docs/formato-fusion.md, sección «Placa».
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

PLATE_VERSION = 1
# Cama de la Bambu Lab P1S y la esquina delantera izquierda que no se puede usar
# (bed_exclude_area de la plantilla P1S), en mm.
P1S_BED_SIZE = (256.0, 256.0)
P1S_EXCLUDED = ((0.0, 0.0), (18.0, 28.0))
PART_GAP_MM = 5.0
_PLATE_KEYS = {"version", "units", "parts"}
_PART_KEYS = {"stl", "fusion", "name"}


@dataclass
class PlatePart:
    stl: Path
    fusion: Path | None
    name: str


def _path(value, base: Path, where: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where} tiene que ser una ruta")
    return base / value


def load_plate(path: str | Path) -> list[PlatePart]:
    """Piezas del archivo de placa, con las rutas resueltas desde su carpeta."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} no es un JSON válido: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != PLATE_VERSION:
        raise ValueError(f"{path} no es un archivo de placa de la versión {PLATE_VERSION}")
    unknown = set(data) - _PLATE_KEYS
    if unknown:
        raise ValueError(f"{path}: claves desconocidas {sorted(unknown)}")
    if data.get("units", "mm") != "mm":
        raise ValueError(f"{path}: las unidades tienen que ser mm")
    raw_parts = data.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ValueError(f"{path}: parts tiene que ser una lista con al menos una pieza")
    base = path.parent
    parts = []
    for number, raw in enumerate(raw_parts, 1):
        where = f"{path}: pieza {number}"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} tiene que ser un objeto con stl, fusion y name")
        unknown = set(raw) - _PART_KEYS
        if unknown:
            raise ValueError(f"{where}: claves desconocidas {sorted(unknown)}")
        if "stl" not in raw:
            raise ValueError(f"{where}: falta stl")
        stl = _path(raw["stl"], base, f"{where}: stl")
        fusion = _path(raw["fusion"], base, f"{where}: fusion") if raw.get("fusion") is not None else None
        name = raw.get("name", stl.stem)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{where}: name tiene que ser un texto")
        parts.append(PlatePart(stl, fusion, name))
    return parts


def arrange(sizes: list[tuple[float, float]], bed_size: tuple[float, float] = P1S_BED_SIZE,
            gap: float = PART_GAP_MM,
            excluded: tuple[tuple[float, float], tuple[float, float]] | None = P1S_EXCLUDED,
            ) -> tuple[list[tuple[float, float]], bool]:
    """Coloca en filas piezas de ancho × fondo dados y devuelve el centro de cada una (en el orden
    recibido) y si caben.

    Las piezas van de más a menos fondo, llenando filas de izquierda a derecha y empezando por
    detrás. Se prueban varios anchos de fila y se queda el conjunto más cuadrado que cabe: el de
    menor lado mayor y, si empatan, el de menos área. Cada fila se centra en X y el conjunto se
    centra en la cama, así que una sola pieza queda en el centro. Si no caben, se colocan en filas
    tan anchas como la cama y se devuelve False.
    """
    width, depth = bed_size
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0]))
    widths = [sizes[i][0] for i in order]
    # Anchos de fila posibles: lo que ocupan seguidas varias piezas de la lista ordenada.
    limits = {width}
    for first in range(len(order)):
        run = -gap
        for w in widths[first:]:
            run += gap + w
            if run > width:
                break
            limits.add(run)
    best, best_score = None, None
    for limit in sorted(limits):
        if limit < max(widths, default=0.0):
            continue
        centers = _shelves(sizes, order, limit, bed_size, gap)
        if not _fits(sizes, centers, bed_size, excluded):
            continue
        low = [min(c[k] - sizes[i][k] / 2 for i, c in enumerate(centers)) for k in (0, 1)]
        high = [max(c[k] + sizes[i][k] / 2 for i, c in enumerate(centers)) for k in (0, 1)]
        span = (high[0] - low[0], high[1] - low[1])
        score = (round(max(span), 6), round(span[0] * span[1], 6))
        if best_score is None or score < best_score:
            best, best_score = centers, score
    if best is not None:
        return best, True
    centers = _shelves(sizes, order, width, bed_size, gap)
    return centers, _fits(sizes, centers, bed_size, excluded)


def _shelves(sizes, order, limit, bed_size, gap) -> list[tuple[float, float]]:
    """Centros con las piezas en filas de como mucho limit de ancho, en el orden dado."""
    width, depth = bed_size
    rows: list[list[int]] = []
    row_width = 0.0
    for index in order:
        w = sizes[index][0]
        if rows and row_width + gap + w <= limit + 1e-9:
            rows[-1].append(index)
            row_width += gap + w
        else:
            rows.append([index])
            row_width = w
    row_depths = [max(sizes[i][1] for i in row) for row in rows]
    total_depth = sum(row_depths) + gap * (len(rows) - 1)
    centers: list[tuple[float, float]] = [(0.0, 0.0)] * len(sizes)
    top = (depth + total_depth) / 2
    for row, row_depth in zip(rows, row_depths):
        row_widths = [sizes[i][0] for i in row]
        x = (width - sum(row_widths) - gap * (len(row) - 1)) / 2
        y = top - row_depth / 2
        for i, w in zip(row, row_widths):
            centers[i] = (x + w / 2, y)
            x += w + gap
        top -= row_depth + gap
    return centers


def _fits(sizes, centers, bed_size, excluded) -> bool:
    eps = 1e-6
    for (w, d), (cx, cy) in zip(sizes, centers):
        low = np.array([cx - w / 2, cy - d / 2])
        high = np.array([cx + w / 2, cy + d / 2])
        if (low < -eps).any() or (high > np.array(bed_size) + eps).any():
            return False
        if excluded is not None:
            (ex0, ey0), (ex1, ey1) = excluded
            if low[0] < ex1 - eps and high[0] > ex0 + eps and low[1] < ey1 - eps and high[1] > ey0 + eps:
                return False
    return True
