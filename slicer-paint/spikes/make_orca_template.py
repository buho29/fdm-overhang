"""Genera la plantilla de proyecto de Orca: la P1S 0,4 con 5 filamentos de PLA, de sus perfiles de sistema.

  python spikes/make_orca_template.py orca_243

Orca solo lee las placas de un 3MF que lleve sus ajustes de proyecto y su metadata OrcaSlicer.
Este script escribe una caja con slicer-paint, la carga en Orca por línea de comandos con los
perfiles de la P1S y la reexporta; de ese 3MF salen los ajustes (templates/orca_p1s_project_settings.config)
y la versión de Orca, que se guarda en el campo «orca_version» de los ajustes.
Con 5 filamentos, como la plantilla de Bambu, se distingue qué ajustes van por filamento.
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
from slicer_paint import project  # noqa: E402
from slicer_paint.writer import PlateObject, write_plate  # noqa: E402
from verify_slicers import WORK, run_slicer, settings_args  # noqa: E402

FILAMENTS = 5


def main() -> None:
    slicer = sys.argv[1] if len(sys.argv) > 1 else "orca_243"
    work = WORK / "plantilla_orca"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    box = trimesh.creation.box(extents=(20, 20, 10))
    src = work / "caja.3mf"
    # Pintada con los 5 filamentos, para que Orca los guarde todos.
    colour = np.arange(len(box.faces)) % FILAMENTS + 1
    write_plate(src, [PlateObject(box.vertices, box.faces, name="caja", color=colour)])
    args = settings_args(slicer)
    filament = args[args.index("--load-filaments") + 1]
    args[args.index("--load-filaments") + 1] = ";".join([filament] * FILAMENTS)
    code, tail = run_slicer(slicer, [*args, "--export-3mf", "plantilla.3mf", "--outputdir", str(work), str(src)])
    out = work / "plantilla.3mf"
    if not out.exists():
        raise SystemExit(f"{slicer} no escribió el 3MF (salida {code}): {tail!r}")
    with zipfile.ZipFile(out) as z:
        settings = json.loads(z.read(project.PROJECT_FILE))
        model = ET.fromstring(z.read("3D/3dmodel.model"))
    meta = {m.get("name"): m.text for m in model.iter() if m.tag.endswith("}metadata")}
    settings["orca_version"] = meta["OrcaSlicer"]
    # Por línea de comandos Orca guarda los 5 filamentos, pero un solo color y una tabla de purgas
    # de 4: se completan con el color del primero y su purga.
    count = len(settings["filament_settings_id"])
    settings["filament_colour"] = [settings["filament_colour"][0]] * count
    flush = next((v for v in settings["flush_volumes_matrix"] if v != "0"), "280")
    settings["flush_volumes_matrix"] = ["0" if i == j else flush for i in range(count) for j in range(count)]
    print(slicer, "salida", code, "Application", meta.get("Application"), "OrcaSlicer", meta["OrcaSlicer"],
          "filamentos", count, "impresora", settings.get("printer_settings_id"))
    project.ORCA_TEMPLATE.write_text(json.dumps(settings, indent=4, ensure_ascii=False), encoding="utf-8")
    print("Escrita", project.ORCA_TEMPLATE)


if __name__ == "__main__":
    main()
