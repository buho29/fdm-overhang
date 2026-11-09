"""Prueba con los slicers reales la costura en aristas elegidas en Fusion, en piezas de eje vertical.

  python spikes/verify_arista.py pieza.stl bambu orca_nightly orca_243 --edges a.json b.json

Lamina la pieza sin pintar y una vez por cada archivo de aristas. En cada capa que cruza la
arista compara el ángulo, respecto al eje de la pieza, del punto donde la cruza con el del
inicio de la pared exterior. Sirve para un prisma o para la hélice de un tornillo.

El slicer puede girar la pieza al cargarla (Orca 2.4.3 lo hace por línea de comandos), así que no
se mira el ángulo absoluto: lo que demuestra que respeta la pintura es que la diferencia sea la
misma en todas las capas y, con varias aristas, en todas ellas. La pieza sin pintar se compara
con la primera arista.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "spikes"))
from slicer_paint import cli, mesh_io, orient, selection  # noqa: E402
from slicer_paint.gcode import analyze  # noqa: E402
from verify_slicers import WORK, run_slicer, settings_args  # noqa: E402

# Margen a lo largo del contorno para dar una costura por buena (mm).
NEAR_MM = 1.0


def angle_of(xy: np.ndarray) -> np.ndarray:
    return np.degrees(np.arctan2(xy[..., 1], xy[..., 0]))


def wrap(degrees):
    return (degrees + 180) % 360 - 180


def crossing(edge: np.ndarray, z: float) -> np.ndarray | None:
    """Punto donde la arista cruza la altura z; el primero si la cruza varias veces."""
    for a, b in zip(edge[:-1], edge[1:]):
        if min(a[2], b[2]) <= z <= max(a[2], b[2]):
            t = 0.5 if a[2] == b[2] else (z - a[2]) / (b[2] - a[2])
            return a + t * (b - a)
    return None


def layer_seams(slicer: str, src: Path, outdir: Path) -> dict[float, np.ndarray] | None:
    """Inicio de la pared exterior más alejada del eje en cada capa, respecto al centro del G-code."""
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True)
    code, tail = run_slicer(slicer, [*settings_args(slicer), "--slice", "0",
                                     "--outputdir", str(outdir), str(src)])
    gcode = outdir / "plate_1.gcode"
    if not gcode.exists():
        print(f"{slicer} {src.name}: salida={code} {tail!r}")
        return None
    report = analyze(gcode.read_text(errors="replace"))
    wall = report.points("outer wall")
    starts = np.array(report.outer_wall_starts)
    starts[:, :2] -= (wall.min(axis=0) + wall.max(axis=0))[:2] / 2
    seams = {}
    for z in np.unique(starts[:, 2]):
        layer = starts[starts[:, 2] == z]
        seams[float(z)] = layer[np.argmax(np.linalg.norm(layer[:, :2], axis=1))]
    return seams


def compare(seams: dict[float, np.ndarray], edge: np.ndarray, axis: np.ndarray) -> str:
    """Giro más repetido entre arista y costura, y capas que se separan menos de NEAR_MM de él."""
    diffs, radii = [], []
    for z, seam in seams.items():
        # El G-code marca la altura de la parte de arriba de la capa.
        point = crossing(edge, z - 0.1)
        if point is None:
            continue
        diffs.append(wrap(angle_of(seam[:2]) - angle_of(point[:2] - axis)))
        radii.append(np.linalg.norm(point[:2] - axis))
    diffs, radii = np.array(diffs), np.array(radii)
    turn = np.median(diffs)
    along = np.abs(wrap(diffs - turn)) * np.pi / 180 * radii
    return (f"capas={len(diffs):4} giro={turn:6.1f}° a menos de {NEAR_MM:.0f} mm={np.mean(along < NEAR_MM):6.1%} "
            f"mediana={np.median(along):6.2f} mm p95={np.percentile(along, 95):6.2f} mm")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stl", type=Path)
    parser.add_argument("slicers", nargs="+")
    parser.add_argument("--edges", nargs="+", type=Path, required=True)
    parser.add_argument("--seam-radius", default=str(selection.DEFAULT_RADIUS))
    args = parser.parse_args()

    base = WORK / "arista"
    base.mkdir(parents=True, exist_ok=True)
    mesh = mesh_io.load_mesh(args.stl)
    chosen = orient.auto_orient(mesh)
    oriented = orient.apply_rotation(mesh, chosen.rotation)
    axis = (oriented.bounds[0] + oriented.bounds[1])[:2] / 2

    plain = base / f"{args.stl.stem}_sin_pintar.3mf"
    if cli.main([str(args.stl), "-o", str(plain)]) != 0:
        raise SystemExit(1)
    runs = []
    for path in args.edges:
        name = f"{path.stem}_r{args.seam_radius}"
        painted = base / f"{args.stl.stem}_{name}.3mf"
        if cli.main([str(args.stl), "-o", str(painted), "--seam", f"fusion:{path}",
                     "--seam-radius", args.seam_radius]) != 0:
            raise SystemExit(1)
        edge = orient.transform_points(selection.load_selection(path).edges[0], mesh, chosen.rotation)
        runs.append((name, painted, edge))

    for slicer in args.slicers:
        seams = layer_seams(slicer, plain, base / slicer / f"{args.stl.stem}_sin_pintar")
        if seams is not None:
            print(f"{slicer:13} {'sin pintar':20} {compare(seams, runs[0][2], axis)}")
        for name, painted, edge in runs:
            seams = layer_seams(slicer, painted, base / slicer / f"{args.stl.stem}_{name}")
            if seams is not None:
                print(f"{slicer:13} {name:20} {compare(seams, edge, axis)}")


if __name__ == "__main__":
    main()
