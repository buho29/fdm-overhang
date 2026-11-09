"""Análisis del G-code laminado para comprobar dónde quedan soportes y costuras."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_FEATURE = re.compile(r";\s*FEATURE:\s*(.+)", re.I)
_TYPE = re.compile(r";\s*TYPE:\s*(.+)", re.I)
_WORD = re.compile(r"([XYZEF])(-?\d*\.?\d+)")


@dataclass
class GcodeReport:
    # Tipo de línea -> puntos (x, y, z) de las extrusiones.
    extrusions: dict[str, list[tuple[float, float, float]]] = field(default_factory=dict)
    # Inicio de cada tramo de pared exterior.
    outer_wall_starts: list[tuple[float, float, float]] = field(default_factory=list)

    def points(self, kind: str) -> np.ndarray:
        return np.array(self.extrusions.get(kind, []), dtype=float).reshape(-1, 3)


def read_gcode_from_3mf(path: str | Path, plate: int = 1) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read(f"Metadata/plate_{plate}.gcode").decode(errors="replace")


def analyze(gcode: str) -> GcodeReport:
    report = GcodeReport()
    x = y = z = 0.0
    feature = ""
    wall_start_pending = False
    for line in gcode.splitlines():
        if line.startswith(";"):
            match = _FEATURE.match(line) or _TYPE.match(line)
            if match:
                feature = match.group(1).strip().lower()
                wall_start_pending = feature in ("outer wall", "external perimeter")
            continue
        if not line.startswith(("G0", "G1", "G2", "G3")):
            continue
        words = dict(_WORD.findall(line.split(";")[0]))
        extruding = float(words.get("E", 0)) > 0 and ("X" in words or "Y" in words)
        if extruding and wall_start_pending:
            report.outer_wall_starts.append((x, y, z))
            wall_start_pending = False
        x, y, z = (float(words.get("X", x)), float(words.get("Y", y)), float(words.get("Z", z)))
        if extruding:
            report.extrusions.setdefault(feature, []).append((x, y, z))
    return report


def seam_angles(report: GcodeReport, center: tuple[float, float], radius: float) -> np.ndarray:
    """Ángulo en grados (0 = +X, 90 = +Y) de las costuras de un cilindro vertical."""
    if not report.outer_wall_starts:
        return np.empty(0)
    s = np.array(report.outer_wall_starts)
    dx, dy = s[:, 0] - center[0], s[:, 1] - center[1]
    near = np.hypot(dx, dy) < radius * 1.2
    return np.degrees(np.arctan2(dy[near], dx[near]))
