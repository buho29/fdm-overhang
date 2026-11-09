"""Línea de comandos: orienta una o varias piezas, pinta soportes y costura y genera el 3MF."""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import trimesh

from . import mesh_io, orient, paint, plate, project, selection
from .selector import BLOCK, DEFAULT_RESOLUTION, ENFORCE, PaintLayer
from .writer import PlateObject, write_plate

ORCA_PATHS = [
    r"C:\Program Files\WindowsApps\OrcaSlicer.OrcaSlicer_*\orca-slicer.exe",
    os.path.expanduser(r"~\Desktop\OrcaSlicer_nightly_portable\OrcaSlicer\orca-slicer.exe"),
]
BAMBU_PATHS = [r"C:\Program Files\Bambu Studio\bambu-studio.exe"]


def find_slicer(kind: str) -> str:
    """Busca el ejecutable; SLICER_PAINT_ORCA o SLICER_PAINT_BAMBU tienen prioridad."""
    override = os.environ.get(f"SLICER_PAINT_{kind.upper()}")
    if override:
        return override
    for pattern in ORCA_PATHS if kind == "orca" else BAMBU_PATHS:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]
    raise FileNotFoundError(f"No encuentro {kind}. Indica la ruta en SLICER_PAINT_{kind.upper()}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slicer-paint",
        description="Genera un 3MF orientado y con soportes y costura pintados.")
    parser.add_argument("input", nargs="?", help="malla de entrada (STL, OBJ o 3MF); no se pone con --plate")
    parser.add_argument("-o", "--output", required=True, help="3MF de salida")
    parser.add_argument("--plate", metavar="PLACA.json",
                        help="archivo de placa: varias piezas, cada una con su STL y su archivo de "
                             "pieza, en un solo 3MF")
    parser.add_argument("--part", help="pieza dentro de un 3MF, por su archivo interno")
    parser.add_argument("--fusion", metavar="ARCHIVO.json",
                        help="archivo de pieza de Fusion (versión 3): cara de cama, costura y "
                             "soportes; se suma a las demás opciones y --orient gana a su cama")
    parser.add_argument("--orient", default=None,
                        help="auto (por defecto), none, face:-z o face:x,y,z (la cara con esa normal a la "
                             "cama) o rot:rx,ry,rz en grados")
    parser.add_argument("--overhang-limit", type=float, default=orient.DEFAULT_OVERHANG_DEG,
                        help="voladizo máximo admitido al orientar, en grados desde la vertical")
    parser.add_argument("--support-overhang", type=float,
                        help="fuerza soportes en caras que vuelan más de estos grados")
    parser.add_argument("--support-enforce", action="append", default=[],
                        metavar="x0,y0,z0,x1,y1,z1 o fusion:ARCHIVO.json",
                        help="fuerza soportes en esta caja o en lo elegido en Fusion")
    parser.add_argument("--support-block", action="append", default=[],
                        metavar="x0,y0,z0,x1,y1,z1 o fusion:ARCHIVO.json",
                        help="bloquea soportes en esta caja o en lo elegido en Fusion")
    parser.add_argument("--support-mode", choices=["manual", "auto"],
                        help="manual (por defecto): solo donde se pinta; auto: el slicer añade los que "
                             "calcule. Sin esta opción ni --support-style, se conserva el tipo guardado")
    parser.add_argument("--support-style", choices=["normal", "tree"], help="normal (por defecto) o tree")
    parser.add_argument("--seam", help="fuerza la costura: back, box:x0,y0,z0,x1,y1,z1 o "
                                       "fusion:ARCHIVO.json (aristas y caras elegidas en Fusion)")
    parser.add_argument("--seam-block", action="append", default=[],
                        metavar="box:... o fusion:ARCHIVO.json",
                        help="prohíbe la costura en esta zona; se puede repetir y gana a forzar")
    parser.add_argument("--seam-radius", type=float, default=selection.DEFAULT_RADIUS,
                        help="con fusion:, ancho en mm de la franja a cada lado de una arista")
    parser.add_argument("--paint-resolution", type=float, default=DEFAULT_RESOLUTION,
                        help="precisión en mm del borde de las cajas pintadas")
    parser.add_argument("--target", choices=["orca", "bambu"],
                        help="slicer de destino; por defecto el de --open, o orca")
    parser.add_argument("--project-settings", metavar="ARCHIVO",
                        help="con destino bambu, ajustes de este .3mf o .config en vez de la plantilla P1S")
    parser.add_argument("--fresh", action="store_true",
                        help="si el 3MF de salida ya existe, no conserva las opciones de impresión "
                             "que guardó el laminador")
    parser.add_argument("--open", choices=["orca", "bambu"], help="abre el resultado en el slicer")
    return parser


def chosen_in_fusion(path: str, mesh, rotation) -> selection.Selection:
    """Selección de Fusion llevada a las coordenadas de la pieza orientada."""
    return selection.load_selection(path).moved(
        lambda points: orient.transform_points(points, mesh, rotation))


def support_zone(text: str, mesh, rotation):
    """Zona de --support-enforce o --support-block: una caja o una selección de Fusion."""
    if text.startswith("fusion:"):
        return chosen_in_fusion(text[7:], mesh, rotation)
    return paint.parse_box(text)


def job_zone(job: selection.Job | None, kind: str, role: str, mesh, rotation) -> list:
    """Selección del archivo de pieza para un papel, en coordenadas de la pieza orientada."""
    chosen = getattr(job, kind).get(role) if job else None
    if chosen is None:
        return []
    return [chosen.moved(lambda points: orient.transform_points(points, mesh, rotation))]


def orientation_spec(args: argparse.Namespace, job: selection.Job | None) -> str:
    """--orient si se ha dado; si no, la cama del archivo de pieza; si no, auto."""
    if args.orient:
        return args.orient
    if job is not None and job.bed is not None:
        return "face:" + ",".join(f"{v:.6f}" for v in job.bed)
    return "auto"


def paint_seam(args: argparse.Namespace, mesh, rotation, oriented,
               warnings: list[str], job: selection.Job | None = None) -> PaintLayer:
    """Costura forzada por --seam y por el archivo de pieza, y prohibida después por cada
    --seam-block y por el archivo de pieza."""
    if args.seam and args.seam.startswith("fusion:"):
        seam = PaintLayer(len(oriented.faces))
        warnings += paint.paint_selection(seam, oriented, chosen_in_fusion(args.seam[7:], mesh, rotation), ENFORCE,
                                          args.seam_radius, args.paint_resolution)
    else:
        seam = paint.paint_seam(oriented, args.seam, args.paint_resolution)
    for chosen in job_zone(job, "seam", "enforce", mesh, rotation):
        warnings += paint.paint_selection(seam, oriented, chosen, ENFORCE,
                                          args.seam_radius, args.paint_resolution)
    for rule in args.seam_block:
        if rule.startswith("fusion:"):
            warnings += paint.paint_selection(seam, oriented, chosen_in_fusion(rule[7:], mesh, rotation), BLOCK,
                                              args.seam_radius, args.paint_resolution)
        elif rule.startswith("box:"):
            seam.apply_box(oriented.triangles, paint.wall_mask(oriented), paint.parse_box(rule[4:]),
                           BLOCK, args.paint_resolution)
        else:
            raise ValueError(f"Zona sin costura no válida: {rule!r}. Usa box:x0,y0,z0,x1,y1,z1 "
                             "o fusion:ARCHIVO.json")
    for chosen in job_zone(job, "seam", "block", mesh, rotation):
        warnings += paint.paint_selection(seam, oriented, chosen, BLOCK,
                                          args.seam_radius, args.paint_resolution)
    return seam


@dataclass
class PreparedPart:
    """Una pieza orientada y pintada, lista para escribir."""
    name: str
    oriented: trimesh.Trimesh
    chosen: orient.OrientationScore
    support: PaintLayer
    seam: PaintLayer


# Opciones que solo tienen sentido para una pieza; con --plate van en el archivo de cada una.
PER_PART_OPTIONS = {"orient": "--orient", "part": "--part", "fusion": "--fusion", "seam": "--seam",
                    "seam_block": "--seam-block", "support_enforce": "--support-enforce",
                    "support_block": "--support-block"}


def check_options(args: argparse.Namespace) -> str:
    """Comprueba las combinaciones de opciones y devuelve el destino del archivo."""
    if args.plate and args.input:
        raise ValueError(f"Con --plate las piezas salen del archivo de placa: quita {args.input}")
    if not args.plate and not args.input:
        raise ValueError("Falta la malla de entrada o --plate")
    if args.plate:
        given = [flag for key, flag in PER_PART_OPTIONS.items() if getattr(args, key)]
        if given:
            raise ValueError(
                f"Con --plate no valen {', '.join(given)}: son de una sola pieza. La cama, la "
                "costura y los soportes de cada pieza van en su archivo de pieza (versión 3), "
                "que se indica con «fusion» en el archivo de placa")
    target = args.target or args.open or "orca"
    if args.open and args.open != target:
        raise ValueError(f"Un archivo para {target} no se puede abrir en {args.open}")
    if args.project_settings and target != "bambu":
        raise ValueError("--project-settings solo sirve con destino bambu")
    return target


def prepare_part(args: argparse.Namespace, name: str, mesh: trimesh.Trimesh,
                 job: selection.Job | None, warnings: list[str]) -> PreparedPart:
    """Orienta la pieza y pinta sus soportes y su costura con las opciones y su archivo de pieza."""
    chosen = orient.parse_orientation(orientation_spec(args, job), mesh, args.overhang_limit)
    oriented = orient.apply_rotation(mesh, chosen.rotation)
    support = paint.paint_supports(
        oriented, args.support_overhang,
        [support_zone(z, mesh, chosen.rotation) for z in args.support_enforce]
        + job_zone(job, "support", "enforce", mesh, chosen.rotation),
        [support_zone(z, mesh, chosen.rotation) for z in args.support_block]
        + job_zone(job, "support", "block", mesh, chosen.rotation),
        args.paint_resolution, warnings)
    seam = paint_seam(args, mesh, chosen.rotation, oriented, warnings, job)
    return PreparedPart(name, oriented, chosen, support, seam)


def prepare_plate(args: argparse.Namespace) -> list[PreparedPart]:
    """Prepara cada pieza del archivo de placa; un error dice de qué pieza es."""
    parts = []
    for number, part in enumerate(plate.load_plate(args.plate), 1):
        label = f"pieza {number} ({part.name})"
        warnings: list[str] = []
        try:
            mesh = mesh_io.load_mesh(part.stl)
            job = selection.load_job(part.fusion) if part.fusion else None
            parts.append(prepare_part(args, part.name, mesh, job, warnings))
        except (ValueError, OSError) as exc:
            raise ValueError(f"{label}: {exc}") from exc
        for warning in warnings:
            print(f"Aviso: {label}: {warning}", file=sys.stderr)
    return parts


def kept_settings(args: argparse.Namespace, output: Path, target: str) -> project.Previous | None:
    """Las opciones de impresión del 3MF de salida, si ya existe y las guardó el laminador de
    destino: proyecto, ajustes de cada objeto (por su nombre) y de la placa. Los ajustes de
    otro laminador no se conservan, porque no los aceptaría."""
    if args.fresh or not output.exists():
        return None
    previous = project.read_previous(output)
    if previous is None:
        return None
    if previous.slicer != target:
        print(f"Aviso: {output.name} se guardó con {previous.slicer} y el destino es {target}: "
              "sus opciones de impresión no se conservan", file=sys.stderr)
        return None
    print(f"Conservadas las opciones de impresión de {output.name}")
    return previous


def part_settings(args: argparse.Namespace, part: PreparedPart,
                  kept: dict[str, str] | None = None) -> dict[str, str]:
    """Ajustes del objeto: los conservados (kept) y, si la pieza tiene pintura de soportes, los
    soportes activados. Su tipo (normal o árbol, manual o automático) es el conservado, salvo que
    se pida otro con --support-style o --support-mode."""
    settings = dict(kept or {})
    if not part.support.is_painted():
        return settings
    settings["enable_support"] = "1"
    if args.support_style or args.support_mode or "support_type" not in settings:
        settings["support_type"] = f"{args.support_style or 'normal'}({args.support_mode or 'manual'})"
    return settings


def print_summary(args: argparse.Namespace, part: PreparedPart) -> None:
    oriented, chosen = part.oriented, part.chosen
    extents = oriented.extents
    print(f"Malla: {len(oriented.faces)} triángulos, "
          f"{'estanca' if oriented.is_watertight else 'NO estanca: revísala'}")
    print(f"Tamaño: {extents[0]:.1f} × {extents[1]:.1f} × {extents[2]:.1f} mm")
    print(f"Voladizo de más de {args.overhang_limit:.0f}°: {chosen.overhang_area:.1f} mm²; "
          f"apoyo en la cama: {chosen.contact_area:.1f} mm²")
    support_areas = part.support.areas(oriented.triangles)
    seam_areas = part.seam.areas(oriented.triangles)
    print(f"Soportes: forzados {support_areas[ENFORCE]:.1f} mm², "
          f"bloqueados {support_areas[BLOCK]:.1f} mm²; "
          f"costura: forzada {seam_areas[ENFORCE]:.1f} mm², bloqueada {seam_areas[BLOCK]:.1f} mm²")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target = check_options(args)
        if args.plate:
            parts = prepare_plate(args)
        else:
            mesh = mesh_io.load_mesh(args.input, args.part)
            job = selection.load_job(args.fusion) if args.fusion else None
            warnings: list[str] = []
            parts = [prepare_part(args, Path(args.input).stem, mesh, job, warnings)]
            for warning in warnings:
                print(f"Aviso: {warning}", file=sys.stderr)
        output = Path(args.output)
        previous = kept_settings(args, output, target)
        if args.project_settings:
            project_settings = project.load_project_settings(args.project_settings)
        elif previous:
            project_settings = previous.project_settings
        else:
            project_settings = project.load_project_settings() if target == "bambu" else None
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    centers, fits = plate.arrange([tuple(p.oriented.extents[:2]) for p in parts])
    output.parent.mkdir(parents=True, exist_ok=True)
    kept_objects = previous.objects if previous else {}
    write_plate(output, [PlateObject(p.oriented.vertices, p.oriented.faces, p.support, p.seam,
                                     p.name, part_settings(args, p, kept_objects.get(p.name)),
                                     center)
                         for p, center in zip(parts, centers)], project_settings,
                metadata=previous.metadata if previous and not args.project_settings else None,
                plate_settings=previous.plate if previous else None)

    for number, part in enumerate(parts, 1):
        if args.plate:
            print(f"Pieza {number}: {part.name}")
        print_summary(args, part)
    if not fits:
        width, depth = plate.P1S_BED_SIZE
        what = "Las piezas no caben" if len(parts) > 1 else "La pieza no cabe"
        print(f"Aviso: {what} en la cama de {width:.0f} × {depth:.0f} mm; ordénalas en el laminador",
              file=sys.stderr)
    print(f"Escrito: {output} (para {target}{f', {len(parts)} piezas' if args.plate else ''})")
    if args.open:
        try:
            subprocess.Popen([find_slicer(args.open), str(output.resolve())])
        except OSError as exc:
            print(f"Error al abrir el slicer: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
