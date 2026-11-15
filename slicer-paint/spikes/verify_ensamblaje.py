"""Comprueba con los laminadores reales que leen la vista de ensamblaje del 3MF de una placa.

  python spikes/verify_ensamblaje.py bambu orca_nightly orca_243

Genera con la línea de comandos una caja y su tapa encima, que se imprime boca abajo. El
laminador carga el 3MF y lo reexporta (--export-3mf). En lo reexportado se calcula dónde queda
cada pieza en la vista de ensamblaje (assemble_item · componente · vértices) y se compara con
su STL, desplazado como el conjunto. Si el laminador no hubiera leído el bloque <assemble>, no
lo volvería a escribir.

Resultado (2026-11-15): Bambu Studio 02.08.02.60, Orca 2.4.3 y la nightly leen el bloque y
conservan el ensamblaje. Al cargar, los tres centran cada malla en el centro de su caja y no
corrigen la transformación de ensamblaje: por eso el writer escribe las mallas ya centradas.
Antes de eso, cada pieza salía movida justo lo que su centro.
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
from slicer_paint.steps import STEPS_FILE  # noqa: E402
from verify_slicers import WORK, run_slicer  # noqa: E402

OUT = WORK / "ensamblaje"
CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
PROD = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"


def parts() -> dict[str, tuple[trimesh.Trimesh, list[int]]]:
    caja = trimesh.creation.box(extents=(40, 30, 20))
    caja.apply_translation((50, -20, 10))
    tapa = trimesh.creation.box(extents=(30, 20, 4))
    tapa.apply_translation((55, -20, 22))
    top = tapa.vertices[:, 2] > 23
    tapa.vertices[top, 0] = 55 + (tapa.vertices[top, 0] - 55) / 2
    return {"Caja": (caja, [0, 0, -1]), "Tapa": (tapa, [0, 0, 1])}


def build(folder: Path) -> Path:
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    for name, (mesh, bed) in parts().items():
        mesh.export(folder / f"{name}.stl")
        (folder / f"{name}.json").write_text(json.dumps({"version": 3, "units": "mm", "bed": bed}),
                                             encoding="utf-8")
    plate = folder / "placa.json"
    plate.write_text(json.dumps({"version": 1, "parts": [
        {"stl": f"{n}.stl", "fusion": f"{n}.json", "name": n} for n in parts()]}), encoding="utf-8")
    return plate


def matrix(text: str | None) -> np.ndarray:
    out = np.eye(4)
    if text:
        out[:3, :4] = np.array([float(v) for v in text.split()]).reshape(4, 3).T
    return out


def assembled(path: Path) -> dict[str, np.ndarray]:
    """Vértices de cada objeto, por su nombre, en la vista de ensamblaje del 3MF."""
    z = zipfile.ZipFile(path)
    config = ET.fromstring(z.read("Metadata/model_settings.config"))
    names = {o.get("id"): {m.get("key"): m.get("value") for m in o.findall("metadata")}.get("name")
             for o in config.findall("object")}
    main = ET.fromstring(z.read("3D/3dmodel.model"))
    wrappers = {o.get("id"): o for o in main.iter(f"{CORE}object")}
    out = {}
    for item in config.iter("assemble_item"):
        wrapper = wrappers[item.get("object_id")]
        placed = []
        for comp in wrapper.iter(f"{CORE}component"):
            model = ET.fromstring(z.read(comp.get(f"{PROD}path").lstrip("/")))
            obj = next(o for o in model.iter(f"{CORE}object") if o.get("id") == comp.get("objectid"))
            local = np.array([[float(v.get(k)) for k in "xyz"] for v in obj.iter(f"{CORE}vertex")])
            m = matrix(item.get("transform")) @ matrix(comp.get("transform"))
            placed.append(local @ m[:3, :3].T + m[:3, 3])
        out[names[item.get("object_id")]] = np.vstack(placed)
    return out


def compare(path: Path) -> str:
    got = assembled(path)
    if not got:
        return "SIN <assemble>"
    meshes = {n: m for n, (m, _) in parts().items()}
    low = np.min([m.vertices.min(axis=0) for m in meshes.values()], axis=0)
    high = np.max([m.vertices.max(axis=0) for m in meshes.values()], axis=0)
    text = []
    for name, mesh in meshes.items():
        if name not in got:
            text.append(f"{name}: falta")
            continue
        # El laminador puede reordenar o juntar vértices: se compara la caja y la distancia.
        offset = got[name].min(axis=0) - mesh.vertices.min(axis=0)
        expected = mesh.vertices + offset
        far = max(np.min(np.linalg.norm(expected[:, None] - got[name][None], axis=2), axis=1).max(),
                  np.min(np.linalg.norm(got[name][:, None] - expected[None], axis=2), axis=1).max())
        text.append(f"{name}: desplazada {np.round(offset, 3).tolist()} forma ±{far:.4f} mm")
    centre = np.array([128 - (low[0] + high[0]) / 2, 128 - (low[1] + high[1]) / 2, -low[2]])
    return "; ".join(text) + f" (esperado {np.round(centre, 3).tolist()})"


def main() -> None:
    plate = build(OUT / "entrada")
    for target in ("orca", "bambu"):
        src = OUT / f"ensamblaje_{target}.3mf"
        assert cli.main(["--plate", str(plate), "-o", str(src), "--target", target, "--fresh"]) == 0
        print(f"{target:13} escrito:", compare(src))
    for slicer in sys.argv[1:]:
        target = "bambu" if slicer == "bambu" else "orca"
        src = OUT / f"ensamblaje_{target}.3mf"
        rt = OUT / slicer
        shutil.rmtree(rt, ignore_errors=True)
        rt.mkdir(parents=True)
        code, tail = run_slicer(slicer, ["--export-3mf", "rt.3mf", "--outputdir", str(rt), str(src)])
        dst = rt / "rt.3mf"
        print(f"{slicer:13} roundtrip salida={code}", compare(dst) if dst.exists() else f"SIN ARCHIVO {tail!r}")
        if dst.exists():
            names = zipfile.ZipFile(dst).namelist()
            kept = (json.loads(zipfile.ZipFile(dst).read(STEPS_FILE))["items"]
                    if STEPS_FILE in names else None)
            print(f"{slicer:13} guía de montaje:",
                  [i["name"] for i in kept] if kept is not None else "no la lleva")


if __name__ == "__main__":
    main()
