"""Comprueba con los slicers reales que leen y aplican la pintura de un 3MF generado.

  python spikes/verify_slicers.py roundtrip bambu orca_nightly orca_243
  python spikes/verify_slicers.py slice bambu orca_nightly
  python spikes/verify_slicers.py roundtrip_proyecto bambu
  python spikes/verify_slicers.py slice_proyecto bambu

Las variantes _proyecto usan el destino Bambu: el archivo lleva ajustes de proyecto y Application.

roundtrip: el slicer carga cada 3MF y lo reexporta; se compara el área pintada por estado y su
centro. No se comparan las cadenas: el slicer puede normalizarlas, y si una está mal formada
deja el triángulo sin pintar sin avisar, lo que aquí se ve como área perdida.
slice: lamina la probeta con distintas pinturas y mide soportes y costura en el G-code.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "spikes"))
from probeta import CYLINDER_X, cylinder_back_mask, probeta, side_overhang_masks  # noqa: E402
from slicer_paint import paint  # noqa: E402
from slicer_paint.gcode import analyze, seam_angles  # noqa: E402
from slicer_paint.mesh_io import load_mesh  # noqa: E402
from slicer_paint.project import load_project_settings  # noqa: E402
from slicer_paint.reader import read_painted  # noqa: E402
from slicer_paint.selector import decode, leaves, triangle_area  # noqa: E402
from slicer_paint.writer import BLOCK, ENFORCE, NONE, write_3mf  # noqa: E402

WORK = ROOT / "out" / "verify"
DEMO = Path(r"C:\wormgear\demo\3d files\WormGear.3mf")
SLICERS = {
    "bambu": r"C:\Program Files\Bambu Studio\bambu-studio.exe",
    "orca_nightly": r"C:\Users\pp\Desktop\OrcaSlicer_nightly_portable\OrcaSlicer\orca-slicer.exe",
    "orca_243": r"C:\Program Files\WindowsApps\OrcaSlicer.OrcaSlicer_2.4.3.0_x64__3qd7h69xpne0g\orca-slicer.exe",
}
PROFILE_ROOTS = {
    "bambu": Path(r"C:\Program Files\Bambu Studio\resources\profiles\BBL"),
    "orca_nightly": Path(os.environ["APPDATA"]) / "OrcaSlicer" / "system" / "BBL",
    "orca_243": Path(os.environ["APPDATA"]) / "OrcaSlicer" / "system" / "BBL",
}
# Mitad y > 0 del voladizo -X, cuyos dos triángulos largos cruzan el borde de la caja.
SUPPORT_HALF_BOX = (np.array([-60.0, 0.0, -1.0]), np.array([0.0, 50.0, 60.0]))
# Centro de la pared +Y del tronco de la T, lejos de las esquinas.
SEAM_BOX = "box:-3,9,2,3,11,18"
MANUAL = {"enable_support": "1", "support_type": "normal(manual)"}
# Ajustes de proyecto de los archivos generados; None es el destino Orca.
PROJECT: bytes | None = None
MACHINE = "Bambu Lab P1S 0.4 nozzle"
PROCESS = "0.20mm Standard @BBL X1C"
FILAMENT = "Bambu PLA Basic @BBL X1C"


def run_slicer(slicer: str, args: list[str]) -> tuple[object, str]:
    try:
        run = subprocess.run([SLICERS[slicer], *args], capture_output=True, timeout=280)
        return run.returncode, (run.stdout + run.stderr).decode(errors="replace").strip()[-300:]
    except subprocess.TimeoutExpired:
        return "TIMEOUT", ""
    except OSError as exc:
        return f"OSError {exc}", ""


def flatten_profile(name: str, root: Path) -> dict:
    """Resuelve la herencia de un perfil de sistema; --load-settings la necesita resuelta."""
    matches = sorted(root.rglob(f"{name}.json"))
    if not matches:
        raise FileNotFoundError(f"{name} en {root}")
    data = json.loads(matches[0].read_text(encoding="utf8"))
    parent = data.pop("inherits", None)
    base = flatten_profile(parent, root) if parent else {}
    base.update(data)
    return base


def settings_args(slicer: str) -> list[str]:
    if PROJECT is not None:
        return []
    outdir = WORK / "perfiles" / slicer
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for kind, name in (("machine", MACHINE), ("process", PROCESS), ("filament", FILAMENT)):
        paths[kind] = outdir / f"{kind}.json"
        paths[kind].write_text(json.dumps(flatten_profile(name, PROFILE_ROOTS[slicer]), indent=1),
                               encoding="utf8")
    return ["--load-settings", f"{paths['machine']};{paths['process']}",
            "--load-filaments", str(paths["filament"])]


def painted_regions(path: Path) -> dict[str, tuple[float, np.ndarray]]:
    """Área pintada y su centro, relativo al de la pieza, por tipo y estado."""
    totals: dict[str, list] = {}
    for mesh in read_painted(path):
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


def same_region(a: tuple[float, np.ndarray], b: tuple[float, np.ndarray]) -> bool:
    return abs(a[0] - b[0]) <= 0.005 * a[0] and bool(np.linalg.norm(a[1] - b[1]) < 0.05)


def write_case(path: Path, mesh, support, seam, settings) -> Path:
    write_3mf(path, mesh.vertices, mesh.faces, support, seam, name="probeta",
              object_settings=settings, project_settings=PROJECT)
    return path


def tapa_case(path: Path) -> Path:
    """La tapa de la demo, malla real de CAD, con cajas que cortan triángulos."""
    mesh = load_mesh(DEMO, "object_16")
    low, high = mesh.bounds
    middle = (low + high) / 2
    span = high - low
    support = paint.paint_supports(
        mesh,
        enforce_boxes=[(low - 1, np.array([middle[0], high[1] + 1, high[2] + 1]))],
        block_boxes=[(np.array([middle[0], low[1] - 1, low[2] - 1]), high + 1)])
    seam_box = f"{low[0] - 1},{middle[1]},{low[2] + span[2] * 0.2},{high[0] + 1},{high[1] + 1},{high[2] - span[2] * 0.2}"
    seam = paint.paint_seam(mesh, f"box:{seam_box}")
    return write_case(path, mesh, support, seam, {})


def roundtrip(slicer: str) -> None:
    mesh = probeta()
    left, right = side_overhang_masks(mesh)
    support = np.full(len(mesh.faces), NONE)
    support[left], support[right] = ENFORCE, BLOCK
    seam = np.full(len(mesh.faces), NONE)
    seam[cylinder_back_mask(mesh)] = ENFORCE
    outdir = WORK / "roundtrip" / f"{slicer}{'_proyecto' if PROJECT else ''}"
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True)
    sources = {
        "entera": write_case(outdir / "entera.3mf", mesh, support, seam,
                             {"enable_support": "1", "support_type": "normal(auto)"}),
        "cajas": write_case(outdir / "cajas.3mf", mesh,
                            paint.paint_supports(mesh, enforce_boxes=[SUPPORT_HALF_BOX]),
                            paint.paint_seam(mesh, SEAM_BOX), MANUAL),
        "tapa": tapa_case(outdir / "tapa.3mf"),
    }
    for name, src in sources.items():
        dst = outdir / f"{name}_rt.3mf"
        start = time.time()
        code, tail = run_slicer(slicer, ["--export-3mf", dst.name, "--outputdir", str(outdir), str(src)])
        line = f"{slicer:13} {name:7} salida={code} {time.time() - start:.0f}s"
        if not dst.exists():
            print(line, "SIN ARCHIVO", repr(tail))
            continue
        want, got = painted_regions(src), painted_regions(dst)
        ok = {k: k in got and same_region(want[k], got[k]) for k in want}
        areas = {k: round(v[0], 1) for k, v in want.items()}
        print(line, "conserva:", ok, "área:", areas, "de más:", sorted(set(got) - set(want)))


def slice_cases(slicer: str) -> None:
    mesh = probeta()
    left, right = side_overhang_masks(mesh)
    both = np.full(len(mesh.faces), NONE)
    both[left], both[right] = ENFORCE, BLOCK
    only_left = np.full(len(mesh.faces), NONE)
    only_left[left] = ENFORCE
    seam = np.full(len(mesh.faces), NONE)
    seam[cylinder_back_mask(mesh)] = ENFORCE
    auto = {"enable_support": "1", "support_type": "normal(auto)"}
    manual = {"enable_support": "1", "support_type": "normal(manual)"}
    tree_manual = {"enable_support": "1", "support_type": "tree(manual)"}
    half_whole = np.full(len(mesh.faces), NONE)
    half_whole[left & (mesh.triangles_center[:, 1] > 0)] = ENFORCE
    half_box = paint.paint_supports(mesh, enforce_boxes=[SUPPORT_HALF_BOX])
    seam_box = paint.paint_seam(mesh, SEAM_BOX)
    cases = {
        "a_sin_pintura_sin_ajustes": (None, None, {}),
        "b_sin_pintura_auto": (None, None, auto),
        "c_forzar_izq_sin_ajustes": (only_left, None, {}),
        "d_forzar_izq_manual": (only_left, None, manual),
        "e_forzar_izq_bloq_der_auto": (both, None, auto),
        "f_costura": (None, seam, {}),
        "g_forzar_izq_arbol_manual": (only_left, None, tree_manual),
        "h_mitad_triangulos_enteros": (half_whole, None, manual),
        "i_mitad_caja": (half_box, None, manual),
        "j_costura_caja": (None, seam_box, {}),
    }
    args = settings_args(slicer)
    bounds_center = mesh.bounds.mean(axis=0)
    results = {}
    for name, (sup, sm, settings) in cases.items():
        outdir = WORK / "slice" / f"{slicer}{'_proyecto' if PROJECT else ''}" / name
        shutil.rmtree(outdir, ignore_errors=True)
        outdir.mkdir(parents=True)
        src = write_case(outdir / f"{name}.3mf", mesh, sup, sm, settings)
        code, tail = run_slicer(slicer, [*args, "--slice", "0", "--outputdir", str(outdir), str(src)])
        gcode = outdir / "plate_1.gcode"
        if not gcode.exists():
            print(f"{slicer:13} {name:28} salida={code} SIN G-CODE {tail!r}")
            continue
        report = analyze(gcode.read_text(errors="replace"))
        # El slicer puede recolocar la pieza; todo se mide respecto a su caja en el G-code.
        wall = report.points("outer wall")
        wall_center = (wall.min(axis=0) + wall.max(axis=0)) / 2
        offset = wall_center[:2] - bounds_center[:2]
        support_pts = np.concatenate(
            [report.points(k) for k in report.extrusions if "support" in k] or [np.empty((0, 3))])
        rel_x = support_pts[:, 0] - offset[0]
        rel_y = support_pts[:, 1] - offset[1]
        angles = seam_angles(report, (CYLINDER_X + offset[0], offset[1]), 8.0)
        back = float(np.mean(np.abs(angles - 90) < 20)) if len(angles) else 0.0
        # Inicios de pared en el centro de la cara +Y del tronco, en las capas de la caja.
        starts = np.array(report.outer_wall_starts)[:, :3] - np.r_[offset, 0]
        stem = (np.abs(starts[:, 0]) < 11) & (starts[:, 2] > 3) & (starts[:, 2] < 17)
        in_box = (np.abs(starts[:, 0]) <= 3.5) & (starts[:, 1] > 9)
        results[name] = {"support_left": int((rel_x < 0).sum()), "support_right": int((rel_x >= 0).sum()),
                         "seams": len(angles), "seam_back": back, "exit": str(code),
                         "support_y_neg": int((rel_y < -2).sum()), "support_y_pos": int((rel_y > 2).sum()),
                         "stem_seam_in_box": float(in_box[stem].mean()) if stem.any() else 0.0}
        print(f"{slicer:13} {name:28} salida={code} soporte izq={results[name]['support_left']:6} "
              f"der={results[name]['support_right']:6} y<-2={results[name]['support_y_neg']:6} "
              f"y>2={results[name]['support_y_pos']:6} costuras +Y={back:4.0%} "
              f"en caja={results[name]['stem_seam_in_box']:4.0%}")
    (WORK / "slice" / f"{slicer}{'_proyecto' if PROJECT else ''}.json").write_text(json.dumps(results, indent=1), encoding="utf8")


def main() -> None:
    global PROJECT
    action, *slicers = sys.argv[1:]
    if action.endswith("_proyecto"):
        PROJECT = load_project_settings()
        action = action.removesuffix("_proyecto")
    for slicer in slicers:
        roundtrip(slicer) if action == "roundtrip" else slice_cases(slicer)


if __name__ == "__main__":
    main()
