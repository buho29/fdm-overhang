"""Prueba con una malla real: la tapa de la demo, con la costura pintada en la cara -Y.

Los slicers tienden a poner la costura atrás, así que pintar +Y no demuestra nada: se pinta
la cara contraria. Se compara con el laminado sin pintar y solo se cuentan las capas que
tienen pared pintada, porque en las demás la pintura no puede actuar.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "spikes"))
from slicer_paint import mesh_io, orient, paint  # noqa: E402
from slicer_paint.gcode import analyze  # noqa: E402
from slicer_paint.writer import ENFORCE, NONE, write_3mf  # noqa: E402
from verify_slicers import DEMO, WORK, run_slicer, settings_args  # noqa: E402


def starts_of(slicer: str, src: Path, part_center: np.ndarray, outdir: Path) -> np.ndarray | None:
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
    wall_center = (wall.min(axis=0) + wall.max(axis=0)) / 2
    points = np.array(report.outer_wall_starts)
    # El slicer puede recolocar la pieza: se pasa a sus coordenadas por el centro en XY.
    points[:, :2] += part_center[:2] - wall_center[:2]
    return points


def main() -> None:
    base = WORK / "tapa"
    base.mkdir(parents=True, exist_ok=True)
    mesh = mesh_io.load_mesh(DEMO, "object_16")
    chosen = orient.auto_orient(mesh)
    oriented = orient.apply_rotation(mesh, chosen.rotation)

    seam = np.full(len(oriented.faces), NONE)
    front = paint.wall_mask(oriented) & (oriented.face_normals[:, 1] < -0.85)
    seam[front] = ENFORCE
    painted_path, plain_path = base / "tapa_frente.3mf", base / "tapa_sin_pintar.3mf"
    write_3mf(painted_path, oriented.vertices, oriented.faces, None, seam, name="tapa")
    write_3mf(plain_path, oriented.vertices, oriented.faces, name="tapa")

    region = trimesh.Trimesh(oriented.vertices, oriented.faces[front], process=False)
    z_low, z_high = region.bounds[0][2], region.bounds[1][2]
    part_center = (oriented.bounds[0] + oriented.bounds[1]) / 2
    print(f"Triángulos pintados: {front.sum()}, altura pintada: {z_low:.2f} a {z_high:.2f} mm "
          f"de {oriented.extents[2]:.2f}")
    for slicer in sys.argv[1:]:
        for name, src in (("pintada", painted_path), ("sin_pintar", plain_path)):
            points = starts_of(slicer, src, part_center, base / slicer / name)
            if points is None:
                continue
            _, distance, _ = trimesh.proximity.closest_point(region, points)
            inside = (points[:, 2] >= z_low) & (points[:, 2] <= z_high + 0.2)
            per_layer = [bool((distance[points[:, 2] == z] < 0.5).any())
                         for z in np.unique(points[inside, 2])]
            print(f"{slicer:13} {name:11} inicios={len(points):3} en capas pintadas={inside.sum():3} "
                  f"cerca de la pintura={(distance[inside] < 0.5).mean():.0%} "
                  f"capas con costura ahí={np.mean(per_layer):.0%}")


if __name__ == "__main__":
    main()
