"""Prueba con los slicers reales que la costura sale de las caras prohibidas con --seam-block fusion:.

  python spikes/verify_caras.py pieza.stl bambu orca_nightly orca_243 --block a.json b.json

Lamina la pieza sin pintar y una vez por cada archivo de caras. En cada capa que corta las caras
prohibidas toma el inicio de la pared exterior más alejado del eje y mira si cae en ellas, en
el borde con otra cara o fuera. La pieza sin pintar se clasifica con cada archivo, para comparar.

El slicer puede girar la pieza al cargarla, así que antes se busca el giro que mejor encaja la
pared exterior del G-code con la malla. Pensado para piezas con un solo contorno exterior por capa.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "spikes"))
from slicer_paint import cli, mesh_io, orient, paint, selection  # noqa: E402
from slicer_paint.gcode import analyze  # noqa: E402
from verify_slicers import WORK, run_slicer, settings_args  # noqa: E402

# Diferencia de distancia por debajo de la cual un inicio está en el borde entre dos caras (mm).
BORDER_MM = 0.1
# El G-code marca la parte de arriba de la capa; la sección está a media capa.
HALF_LAYER = 0.1


def rotate(xy: np.ndarray, degrees: float) -> np.ndarray:
    a = np.radians(degrees)
    return xy @ np.array([[np.cos(a), np.sin(a)], [-np.sin(a), np.cos(a)]])


def placed_starts(slicer: str, src: Path, outdir: Path, mesh: trimesh.Trimesh) -> np.ndarray | None:
    """Inicio de la pared exterior más alejada del eje en cada capa, en coordenadas de la malla."""
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
    center = (wall.min(axis=0) + wall.max(axis=0))[:2] / 2
    axis = (mesh.bounds[0] + mesh.bounds[1])[:2] / 2
    sample = wall[np.random.default_rng(0).choice(len(wall), min(len(wall), 1500), replace=False)]

    def misfit(degrees: float) -> float:
        points = np.c_[rotate(sample[:, :2] - center, degrees) + axis, sample[:, 2] - HALF_LAYER]
        return float(np.median(trimesh.proximity.closest_point(mesh, points)[1]))

    turn = min(np.arange(0, 360, 2.0), key=misfit)
    turn = min(np.arange(turn - 2, turn + 2, 0.25), key=misfit)
    starts = np.array(report.outer_wall_starts)
    chosen = []
    for z in np.unique(starts[:, 2]):
        layer = starts[starts[:, 2] == z]
        point = layer[np.argmax(np.linalg.norm(layer[:, :2] - center, axis=1))]
        chosen.append(np.r_[rotate(point[:2] - center, turn) + axis, z - HALF_LAYER])
    return np.array(chosen)


def classify(starts: np.ndarray, mesh: trimesh.Trimesh, blocked: np.ndarray) -> str:
    z_low, z_high = mesh.triangles[blocked][:, :, 2].min(), mesh.triangles[blocked][:, :, 2].max()
    starts = starts[(starts[:, 2] >= z_low) & (starts[:, 2] <= z_high)]
    inside = trimesh.Trimesh(mesh.vertices, mesh.faces[blocked], process=False)
    outside = trimesh.Trimesh(mesh.vertices, mesh.faces[~blocked], process=False)
    d_in = trimesh.proximity.closest_point(inside, starts)[1]
    d_out = trimesh.proximity.closest_point(outside, starts)[1]
    on_blocked = d_in < d_out - BORDER_MM
    on_free = d_out < d_in - BORDER_MM
    return (f"capas={len(starts):4} en caras prohibidas={on_blocked.mean():6.1%} "
            f"en el borde={(~on_blocked & ~on_free).mean():6.1%} fuera={on_free.mean():6.1%}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stl", type=Path)
    parser.add_argument("slicers", nargs="+")
    parser.add_argument("--block", nargs="+", type=Path, required=True)
    args = parser.parse_args()

    base = WORK / "caras"
    base.mkdir(parents=True, exist_ok=True)
    mesh = mesh_io.load_mesh(args.stl)
    chosen = orient.auto_orient(mesh)
    oriented = orient.apply_rotation(mesh, chosen.rotation)

    plain = base / f"{args.stl.stem}_sin_pintar.3mf"
    if cli.main([str(args.stl), "-o", str(plain)]) != 0:
        raise SystemExit(1)
    runs = []
    for path in args.block:
        painted = base / f"{args.stl.stem}_{path.stem}.3mf"
        if cli.main([str(args.stl), "-o", str(painted), "--seam-block", f"fusion:{path}"]) != 0:
            raise SystemExit(1)
        faces = selection.load_selection(path).moved(
            lambda points: orient.transform_points(points, mesh, chosen.rotation)).faces
        blocked = np.any([paint.face_mask(oriented, face) for face in faces], axis=0)
        runs.append((path.stem, painted, blocked))

    for slicer in args.slicers:
        starts = placed_starts(slicer, plain, base / slicer / "sin_pintar", oriented)
        for name, _, blocked in runs if starts is not None else []:
            print(f"{slicer:13} {'sin pintar':10} {name:22} {classify(starts, oriented, blocked)}")
        for name, painted, blocked in runs:
            starts = placed_starts(slicer, painted, base / slicer / name, oriented)
            if starts is not None:
                print(f"{slicer:13} {'prohibidas':10} {name:22} {classify(starts, oriented, blocked)}")


if __name__ == "__main__":
    main()
