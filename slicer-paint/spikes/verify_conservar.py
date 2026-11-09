"""Comprueba con Orca y Bambu que se conservan las opciones de impresión al reescribir un 3MF.

  python spikes/verify_conservar.py orca bambu

Genera una caja, la guarda con el laminador (--export-3mf), cambia ajustes de proyecto, del
objeto y de la placa como haría el usuario, la reescribe con slicer-paint y comprueba que el
laminador sigue leyendo esos ajustes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import trimesh

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "spikes"))
from verify_slicers import SLICERS as ALL_SLICERS  # noqa: E402

W = ROOT / "out" / "verify_conservar"
SLICERS = {"orca": ALL_SLICERS["orca_nightly"], "bambu": ALL_SLICERS["bambu"]}
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")


def slicer_paint(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "slicer_paint.cli", *args], cwd=ROOT, env=ENV,
                          capture_output=True, text=True, encoding="utf-8")


def roundtrip(slicer: str, src: Path, dst: Path) -> None:
    """Carga el 3MF en el laminador y lo vuelve a guardar."""
    if dst.exists():
        dst.unlink()
    r = subprocess.run([SLICERS[slicer], "--export-3mf", dst.name, "--outputdir", str(W), str(src)],
                       capture_output=True, timeout=280)
    assert dst.exists(), (slicer, r.returncode, (r.stdout + r.stderr)[-400:])


def edit(path: Path) -> None:
    """Cambia ajustes de proyecto, del primer objeto y de la placa."""
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "Metadata/project_settings.config":
                cfg = json.loads(data)
                cfg["wall_loops"] = "5"
                cfg["layer_height"] = "0.12"
                data = json.dumps(cfg, indent=4).encode()
            if item.filename == "Metadata/model_settings.config":
                text = data.decode()
                text = re.sub(r'(<object id="\d+"[^>]*>\s*<metadata key="name" value="[^"]*"/>)',
                              r'\1\n    <metadata key="sparse_infill_density" value="35%"/>', text, count=1)
                text = re.sub(r'\n\s*<metadata key="plater_name" value="[^"]*"/>', "", text)
                text = text.replace('<metadata key="plater_id" value="1"/>',
                                    '<metadata key="plater_id" value="1"/>\n    '
                                    '<metadata key="plater_name" value="mi placa"/>', 1)
                data = text.encode()
            zout.writestr(item, data)
    tmp.replace(path)


def show(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        cfg = json.loads(z.read("Metadata/project_settings.config"))
        settings = z.read("Metadata/model_settings.config").decode()
        model = z.read("3D/3dmodel.model").decode()
    meta = re.findall(r'<metadata name="(Application|OrcaSlicer)">([^<]*)', model)
    infill = re.findall(r'sparse_infill_density" value="([^"]*)', settings)
    plate = re.findall(r'plater_name" value="([^"]*)', settings)
    return (f"wall_loops={cfg['wall_loops']} layer_height={cfg['layer_height']} "
            f"relleno del objeto={infill} placa={plate} {meta}")


def main() -> None:
    W.mkdir(parents=True, exist_ok=True)
    stl = W / "caja.stl"
    trimesh.creation.box((20, 30, 10)).export(stl)
    for slicer in sys.argv[1:]:
        print("==", slicer)
        first = W / f"{slicer}_first.3mf"
        assert slicer_paint(str(stl), "-o", str(first), "--target", slicer, "--fresh").returncode == 0
        saved = W / f"{slicer}_saved.3mf"
        roundtrip(slicer, first, saved)
        edit(saved)
        print("guardado y cambiado:   ", show(saved))
        control = W / f"{slicer}_control.3mf"
        roundtrip(slicer, saved, control)
        print("el laminador lo lee:   ", show(control))
        rewritten = W / f"{slicer}_rewritten.3mf"
        shutil.copy(saved, rewritten)
        r = slicer_paint(str(stl), "-o", str(rewritten), "--target", slicer)
        print("slicer-paint:", r.returncode, r.stdout.strip().splitlines()[0], r.stderr.strip())
        print("reescrito:             ", show(rewritten))
        again = W / f"{slicer}_again.3mf"
        roundtrip(slicer, rewritten, again)
        print("el laminador lo relee: ", show(again))


if __name__ == "__main__":
    main()
