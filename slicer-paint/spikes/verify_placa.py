"""Comprueba con los slicers reales un 3MF de varias piezas generado con --plate.

  python spikes/verify_placa.py bambu orca_nightly orca_243

Genera con la línea de comandos una placa de tres piezas, para los dos destinos:
1. La probeta, con soportes forzados en el voladizo -X, bloqueados en el +X y costura forzada
   detrás del cilindro, con caras de un archivo de pieza.
2. El prisma hexagonal tumbado sobre una cara (cama del archivo de pieza) y costura prohibida
   en una zona.
3. Una caja sin archivo de pieza, que se orienta sola.

roundtrip: el slicer carga el 3MF y lo reexporta. Se comparan, pieza a pieza, el área pintada
por estado y su centro, y qué objetos conservan enable_support.
slice: lamina la placa y cuenta los soportes que caen sobre cada pieza; solo la probeta debe
tenerlos.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "spikes"))
from probeta import cylinder_back_mask, probeta, side_overhang_masks  # noqa: E402
from slicer_paint import cli  # noqa: E402
from slicer_paint.gcode import analyze  # noqa: E402
from slicer_paint.reader import read_painted  # noqa: E402
from slicer_paint.selector import decode, leaves, triangle_area  # noqa: E402
from verify_slicers import WORK, run_slicer, same_region, settings_args  # noqa: E402

OUT = WORK / "placa"


def _faces(mesh: trimesh.Trimesh, mask: np.ndarray) -> dict:
    return {"vertices": mesh.vertices.tolist(), "triangles": mesh.faces[mask].tolist(),
            "area": float(mesh.area_faces[mask].sum())}


def _prism() -> trimesh.Trimesh:
    prism = trimesh.creation.cylinder(radius=10 / np.cos(np.radians(30)), height=24, sections=6)
    prism.apply_transform(trimesh.transformations.rotation_matrix(np.radians(30), [0, 0, 1]))
    prism.apply_translation((0, 0, 12))
    return prism


def _patch(center, normal, size=10.0) -> dict:
    plane = trimesh.creation.box(extents=(size, size, 1e-3))
    top = plane.face_normals[:, 2] > 0.5
    vertices, triangles = trimesh.remesh.subdivide_to_size(plane.vertices, plane.faces[top], 2.0)
    vertices[:, 2] = 0
    turn = trimesh.geometry.align_vectors([0, 0, 1], normal)[:3, :3]
    return {"vertices": (vertices @ turn.T + center).tolist(), "triangles": triangles.tolist()}


def build_plate(folder: Path) -> Path:
    """Escribe los STL, los archivos de pieza y el archivo de placa."""
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    t = probeta()
    left, right = side_overhang_masks(t)
    t.export(folder / "Probeta.stl")
    (folder / "Probeta.json").write_text(json.dumps({
        "version": 3, "units": "mm", "body": "Probeta", "bed": [0, 0, -1],
        "support": {"enforce": {"faces": [_faces(t, left)]}, "block": {"faces": [_faces(t, right)]}},
        "seam": {"enforce": {"faces": [_faces(t, cylinder_back_mask(t))]}},
    }), encoding="utf-8")
    _prism().export(folder / "Prisma.stl")
    (folder / "Prisma.json").write_text(json.dumps({
        "version": 3, "units": "mm", "bed": [1, 0, 0],
        "seam": {"block": {"patches": [_patch(np.array([-10.0, 0, 12]), [-1, 0, 0])]}},
    }), encoding="utf-8")
    trimesh.creation.box(extents=(30, 20, 12)).export(folder / "Caja.stl")
    plate = folder / "placa.json"
    plate.write_text(json.dumps({"version": 1, "units": "mm", "parts": [
        {"stl": "Probeta.stl", "fusion": "Probeta.json", "name": "Probeta"},
        {"stl": "Prisma.stl", "fusion": "Prisma.json"},
        {"stl": "Caja.stl"},
    ]}), encoding="utf-8")
    return plate


def regions(mesh) -> dict[str, tuple[float, np.ndarray]]:
    """Área pintada y su centro, relativo al de la pieza, por tipo y estado."""
    totals: dict[str, list] = {}
    part_center = (mesh.vertices.min(axis=0) + mesh.vertices.max(axis=0)) / 2
    for kind, strings in mesh.paint.items():
        for index, text in strings.items():
            for leaf, state in leaves(mesh.vertices[mesh.faces[index]], decode(text)):
                if state == 0:
                    continue
                area = triangle_area(leaf)
                entry = totals.setdefault(f"{kind}={state}", [0.0, np.zeros(3)])
                entry[0] += area
                entry[1] += area * (leaf.mean(axis=0) - part_center)
    return {k: (a, c / a) for k, (a, c) in totals.items() if a > 0}


def support_flags(path: Path) -> dict[str, str | None]:
    """enable_support de cada objeto, por su nombre."""
    root = ET.fromstring(zipfile.ZipFile(path).read("Metadata/model_settings.config"))
    flags = {}
    for obj in root.findall("object"):
        meta = {m.get("key"): m.get("value") for m in obj.findall("metadata") if m.get("key")}
        flags[meta.get("name")] = meta.get("enable_support")
    return flags


# Por línea de comandos, Orca recoloca las piezas de un 3MF que no es un proyecto de Bambu si no
# se le dice lo contrario.
KEEP_PLACES = ["--arrange", "0"]


def roundtrip(slicer: str, src: Path, outdir: Path) -> None:
    dst = outdir / f"{src.stem}_rt.3mf"
    start = time.time()
    code, tail = run_slicer(slicer, [*KEEP_PLACES, "--export-3mf", dst.name, "--outputdir", str(outdir), str(src)])
    line = f"{slicer:13} roundtrip salida={code} {time.time() - start:.0f}s"
    if not dst.exists():
        print(line, "SIN ARCHIVO", repr(tail))
        return
    want, got = read_painted(src), read_painted(dst)
    print(line, f"objetos {len(want)} -> {len(got)}", "ajustes:", support_flags(src), "->", support_flags(dst))
    for number, a in enumerate(want, 1):
        # El slicer puede cambiar el orden de los objetos: se emparejan por su número de triángulos.
        b = next((m for m in got if len(m.faces) == len(a.faces)), None)
        if b is None:
            print(f"   pieza {number}: NO ESTÁ")
            continue
        ra, rb = regions(a), regions(b)
        ok = {k: k in rb and same_region(ra[k], rb[k]) for k in ra}
        center_a = (a.vertices.min(axis=0) + a.vertices.max(axis=0))[:2] / 2
        center_b = (b.vertices.min(axis=0) + b.vertices.max(axis=0))[:2] / 2
        print(f"   pieza {number}: {len(a.faces)} triángulos, conserva {ok} "
              f"de más {sorted(set(rb) - set(ra))} centro {np.round(center_a, 1)}->{np.round(center_b, 1)}")


def slice_plate(slicer: str, src: Path, outdir: Path, project: bool) -> None:
    code, tail = run_slicer(slicer, [*([] if project else settings_args(slicer)), *KEEP_PLACES, "--slice", "0",
                                     "--outputdir", str(outdir), str(src)])
    gcode = outdir / "plate_1.gcode"
    if not gcode.exists():
        print(f"{slicer:13} slice salida={code} SIN G-CODE {tail!r}")
        return
    report = analyze(gcode.read_text(errors="replace"))
    wall = report.points("outer wall")
    support = np.concatenate([report.points(k) for k in report.extrusions if "support" in k]
                             or [np.empty((0, 3))])
    meshes = read_painted(src)
    # Desplazamiento del conjunto, por si el slicer lo recoloca.
    placed = np.concatenate([m.vertices for m in meshes])
    offset = ((wall.min(axis=0) + wall.max(axis=0)) - (placed.min(axis=0) + placed.max(axis=0)))[:2] / 2
    counts = []
    for mesh in meshes:
        low, high = mesh.vertices.min(axis=0)[:2] + offset - 3, mesh.vertices.max(axis=0)[:2] + offset + 3
        inside = ((support[:, :2] >= low) & (support[:, :2] <= high)).all(axis=1)
        counts.append(int(inside.sum()))
    print(f"{slicer:13} slice salida={code} desplazamiento {np.round(offset, 2)} "
          f"puntos de soporte por pieza {counts} de {len(support)}")


def main() -> None:
    plate = build_plate(OUT / "entrada")
    for target in ("orca", "bambu"):
        src = OUT / f"placa_{target}.3mf"
        assert cli.main(["--plate", str(plate), "-o", str(src), "--target", target]) == 0
    for slicer in sys.argv[1:]:
        target = "bambu" if slicer == "bambu" else "orca"
        src = OUT / f"placa_{target}.3mf"
        for kind in ("roundtrip", "slice"):
            outdir = OUT / slicer / kind
            shutil.rmtree(outdir, ignore_errors=True)
            outdir.mkdir(parents=True)
            if kind == "roundtrip":
                roundtrip(slicer, src, outdir)
            else:
                slice_plate(slicer, src, outdir, target == "bambu")


if __name__ == "__main__":
    main()
