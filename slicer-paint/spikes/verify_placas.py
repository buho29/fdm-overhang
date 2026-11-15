"""Comprueba con los slicers reales un 3MF con una placa por color de cuerpo.

  python spikes/verify_placas.py bambu orca_nightly orca_243

Genera con la línea de comandos tres cajas: dos del filamento 1 y una del 2, que van a dos placas.
slice: lamina todas las placas (--slice 0) y mira qué cajas hay en el G-code de cada una, por
el tamaño de su pared exterior.
roundtrip: el slicer carga el 3MF y lo reexporta; se compara en qué placa queda cada objeto.
Después reescribe con la línea de comandos el 3MF que guardó el laminador y repite.

Resultado (2026-11-14): Bambu Studio 02.08.02.60 respeta las dos placas, también al reescribir
lo que guardó. Orca (nightly y 2.4.3) pone todo en la placa 1 si el 3MF no lleva sus ajustes de
proyecto; con la plantilla de Orca (make_orca_template.py) y su metadata respeta las dos, también
al reescribir lo que guardó.
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "spikes"))
from slicer_paint import cli  # noqa: E402
from slicer_paint.gcode import analyze  # noqa: E402
from verify_slicers import WORK, run_slicer, settings_args  # noqa: E402

OUT = WORK / "placas"
BOXES = {"A": (30, 1, "#AA8CE6"), "B": (20, 2, "#EBEBEB"), "C": (25, 1, "#AA8CE6")}


def build(folder: Path) -> Path:
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    for name, (size, filament, rgb) in BOXES.items():
        trimesh.creation.box(extents=(size, size, 10)).export(folder / f"{name}.stl")
        (folder / f"{name}.json").write_text(json.dumps({
            "version": 3, "units": "mm", "bed": [0, 0, -1],
            "color": {"body": {"filament": filament, "rgb": rgb}}}), encoding="utf-8")
    plate = folder / "placa.json"
    plate.write_text(json.dumps({"version": 1, "parts": [
        {"stl": f"{n}.stl", "fusion": f"{n}.json", "name": n} for n in BOXES]}), encoding="utf-8")
    return plate


def plates_of(path: Path) -> dict[str, str]:
    """Placa de cada objeto, por su nombre."""
    root = ET.fromstring(zipfile.ZipFile(path).read("Metadata/model_settings.config"))
    names = {}
    for obj in root.findall("object"):
        meta = {m.get("key"): m.get("value") for m in obj.findall("metadata") if m.get("key")}
        names[obj.get("id")] = meta.get("name")
    out = {}
    for plate in root.findall("plate"):
        meta = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
        for inst in plate.findall("model_instance"):
            ids = {m.get("key"): m.get("value") for m in inst.findall("metadata")}
            out[names.get(ids["object_id"])] = meta["plater_id"]
    return out


def which_boxes(gcode: Path) -> list[str]:
    """Cajas del G-code por el ancho de cada isla de pared exterior en la primera capa."""
    wall = analyze(gcode.read_text(errors="replace")).points("outer wall")
    if not len(wall):
        return []
    first = wall[wall[:, 2] <= wall[:, 2].min() + 0.05][:, :2]
    # La pared de una caja son sus 4 esquinas seguidas.
    found = []
    for start in range(0, len(first) - 3, 4):
        corners = first[start:start + 4]
        side = (corners.max(axis=0) - corners.min(axis=0)).mean()
        found += [n for n, (size, _, _) in BOXES.items() if abs(side - size) < 1.0]
    return sorted(found)


def main() -> None:
    plate = build(OUT / "entrada")
    for target in ("orca", "bambu"):
        src = OUT / f"placas_{target}.3mf"
        assert cli.main(["--plate", str(plate), "-o", str(src), "--target", target, "--fresh"]) == 0
        print(target, "escrito:", plates_of(src))
    for slicer in sys.argv[1:]:
        target = "bambu" if slicer == "bambu" else "orca"
        src = OUT / f"placas_{target}.3mf"
        outdir = OUT / slicer
        shutil.rmtree(outdir, ignore_errors=True)
        outdir.mkdir(parents=True)
        code, tail = run_slicer(slicer, [*([] if target == "bambu" else settings_args(slicer)), "--slice", "0",
                                         "--outputdir", str(outdir), str(src)])
        gcodes = sorted(outdir.glob("plate_*.gcode"))
        print(f"{slicer:13} slice salida={code} " + ", ".join(f"{g.stem}: {which_boxes(g)}" for g in gcodes)
              + ("" if gcodes else f" SIN G-CODE {tail!r}"))
        rt = outdir / "rt"
        rt.mkdir()
        code, tail = run_slicer(slicer, ["--export-3mf", "rt.3mf", "--outputdir", str(rt), str(src)])
        dst = rt / "rt.3mf"
        print(f"{slicer:13} roundtrip salida={code}", plates_of(dst) if dst.exists() else f"SIN ARCHIVO {tail!r}")
        if not dst.exists():
            continue
        # Reescribir el 3MF que guardó el propio laminador: lleva su proyecto y su metadata.
        saved = outdir / "guardado.3mf"
        shutil.copy(dst, saved)
        assert cli.main(["--plate", str(plate), "-o", str(saved), "--target", target]) == 0
        again = outdir / "again"
        again.mkdir()
        code, tail = run_slicer(slicer, ["--slice", "0", "--outputdir", str(again), str(saved)])
        gcodes = sorted(again.glob("plate_*.gcode"))
        print(f"{slicer:13} guardado y reescrito: {plates_of(saved)} slice salida={code} "
              + ", ".join(f"{g.stem}: {which_boxes(g)}" for g in gcodes) + ("" if gcodes else f" {tail[-120:]!r}"))
        code, tail = run_slicer(slicer, ["--export-3mf", "rt2.3mf", "--outputdir", str(again), str(saved)])
        dst = again / "rt2.3mf"
        print(f"{slicer:13} guardado, roundtrip salida={code}",
              plates_of(dst) if dst.exists() else f"SIN ARCHIVO {tail!r}")


if __name__ == "__main__":
    main()
