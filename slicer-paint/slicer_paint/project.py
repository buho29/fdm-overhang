"""Ajustes de proyecto para los archivos destinados a Bambu Studio.

Bambu Studio 02.08.02.60 considera inválido un 3MF sin `nozzle_diameter` ni un `printer_model`
de Bambu, y entonces carga solo la geometría y borra los ajustes por objeto, como
`enable_support` (Plater.cpp, check_project_config). Una configuración parcial tampoco sirve,
porque la completa con valores por defecto y pisa los presets. Hace falta un proyecto completo,
y al abrir el archivo se usan sus presets en lugar de los seleccionados.

Orca, en cambio, rechaza estos ajustes y la metadata Application, por eso hay dos destinos.
Sí acepta los suyos: al guardar, escribe la misma Application que Bambu Studio y además una
metadata OrcaSlicer.

Al reescribir un 3MF que el laminador ya guardó, read_previous recoge sus opciones de
impresión (proyecto, ajustes de cada objeto y de la placa) para conservarlas.
"""
from __future__ import annotations

import colorsys
import json
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_FILE = "Metadata/project_settings.config"
# Proyecto P1S guardado por Bambu Studio 02.08.02.60, con 5 filamentos (PLA y PC).
DEFAULT_TEMPLATE = Path(__file__).resolve().parent / "templates" / "bambu_p1s_project_settings.config"


def load_project_settings(path: str | Path | None = None) -> bytes:
    """Lee los ajustes de un .config o de un proyecto .3mf; sin ruta, la plantilla P1S."""
    source = Path(path) if path else DEFAULT_TEMPLATE
    if source.suffix.lower() == ".3mf":
        with zipfile.ZipFile(source) as archive:
            if PROJECT_FILE not in archive.namelist():
                raise ValueError(f"{source} no tiene ajustes de proyecto")
            data = archive.read(PROJECT_FILE)
    else:
        data = source.read_bytes()
    application_version(data)
    return data


@dataclass
class Previous:
    """Opciones de impresión que el laminador guardó en un 3MF que se va a reescribir.

    slicer es "orca" u "bambu". Orca escribe la misma metadata Application que Bambu Studio
    y además una metadata OrcaSlicer, que es lo que los distingue. metadata son esas dos, tal
    cual. objects va por nombre de objeto, sin el nombre; plate lleva los ajustes de la
    primera placa, sin su número ni sus miniaturas.
    """
    slicer: str
    metadata: list[tuple[str, str]]
    project_settings: bytes
    objects: dict[str, dict[str, str]] = field(default_factory=dict)
    plate: dict[str, str] = field(default_factory=dict)


# Metadata del 3dmodel.model que identifica al laminador que guardó los ajustes.
_SLICER_METADATA = ("Application", "OrcaSlicer")
_CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def _keyed(element: ET.Element) -> dict[str, str]:
    """Las <metadata key value> directas de un elemento."""
    return {m.get("key"): m.get("value", "") for m in element.findall("metadata") if m.get("key")}


def read_previous(path: str | Path) -> Previous | None:
    """Lee las opciones de impresión de un 3MF guardado por un laminador.

    None si no existe, no es un 3MF o no tiene ajustes de proyecto (como los de destino orca
    que aún no se han guardado desde Orca).
    """
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if PROJECT_FILE not in names:
                return None
            settings = archive.read(PROJECT_FILE)
            model = ET.fromstring(archive.read("3D/3dmodel.model"))
            config = (ET.fromstring(archive.read("Metadata/model_settings.config"))
                      if "Metadata/model_settings.config" in names else None)
        application_version(settings)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError):
        return None
    found: dict[str, str] = {}
    for m in model.findall(f"{_CORE}metadata"):   # Orca repite la suya cada vez que guarda
        if m.get("name") in _SLICER_METADATA:
            found.setdefault(m.get("name"), m.text or "")
    metadata = list(found.items())
    objects: dict[str, dict[str, str]] = {}
    plate: dict[str, str] = {}
    if config is not None:
        for obj in config.findall("object"):
            values = _keyed(obj)
            name = values.pop("name", None)
            if name is not None:
                objects.setdefault(name, values)
        first = config.find("plate")
        if first is not None:
            plate = {k: v for k, v in _keyed(first).items()
                     if k != "plater_id" and not k.endswith("_file")}
    slicer = "orca" if any(name == "OrcaSlicer" for name, _ in metadata) else "bambu"
    return Previous(slicer, metadata, settings, objects, plate)


def _per_filament_keys() -> dict[str, int]:
    """Claves de los ajustes que llevan valores por filamento, con cuántos lleva cada uno. Salen
    de la plantilla, que tiene 5 filamentos: con 5, 10 o 20 valores son 1, 2 o 4 por filamento."""
    template = json.loads(DEFAULT_TEMPLATE.read_bytes())
    count = len(template["filament_colour"])
    return {key: len(value) // count for key, value in template.items()
            if isinstance(value, list) and len(value) in (count, 2 * count, 4 * count)}


def _rgb(colour: str) -> tuple[float, float, float]:
    return tuple(int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))


def flush_volume(source: str, target: str) -> float:
    """Purga de un color a otro (mm³), sin la purga mínima del filamento de origen: la fórmula de
    Bambu Studio (FlushVolCalculator::calc_flush_vol_rgb). Pasar a un color más claro pide mucho
    más que pasar a uno más oscuro."""
    src, dst = _rgb(source), _rgb(target)
    src_hsv, dst_hsv = colorsys.rgb_to_hsv(*src), colorsys.rgb_to_hsv(*dst)

    def cone(hue: float, sat: float, val: float) -> tuple[float, float]:
        return math.cos(2 * math.pi * hue) * sat * val, math.sin(2 * math.pi * hue) * sat * val

    (x1, y1), (x2, y2) = cone(*src_hsv), cone(*dst_hsv)
    hs_dist = min(1.2, math.hypot(x1 - x2, y1 - y2))
    src_lumi = 0.3 * src[0] + 0.59 * src[1] + 0.11 * src[2]
    dst_lumi = 0.3 * dst[0] + 0.59 * dst[1] + 0.11 * dst[2]
    if dst_lumi >= src_lumi:
        lumi_flush = (dst_lumi - src_lumi) ** 0.7 * 560
    else:
        lumi_flush = (src_lumi - dst_lumi) * 80
        hs_dist = min(0.67 * dst_hsv[2] + 0.33 * src_hsv[2], hs_dist)
    hs_flush = 230 * hs_dist
    # Tercer lado de un triángulo con esos dos lados y 120° entre ellos.
    volume = math.sqrt(hs_flush ** 2 + lumi_flush ** 2 + hs_flush * lumi_flush)
    return max(volume, 60.0)


_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")
# Purga mínima de un filamento de PLA de Bambu en la plantilla (mm³).
_DEFAULT_MIN_FLUSH = 63.0


def with_filament_colours(project_settings: bytes, colours: list[str | None]) -> bytes:
    """Los mismos ajustes con un filamento por color: colours[0] es el filamento 1, y None deja el
    color que tenía. Los filamentos que faltan copian los ajustes del 1; los que sobran se quedan
    como estaban. La tabla de purgas se recalcula con los colores nuevos, como hace Bambu Studio
    al cambiar un color."""
    settings = json.loads(project_settings)
    old = list(settings["filament_colour"])
    count = len(old)
    total = max(count, len(colours))
    new = [(colours[i] if i < len(colours) and colours[i] else (old[i] if i < count else old[0])).upper()
           for i in range(total)]
    for colour in new:
        if not _COLOUR.fullmatch(colour):
            raise ValueError(f"Color de filamento no válido: {colour!r}")
    # Un color de Fusion en un filamento de otro material que el 1 (como el PC de la plantilla)
    # lo cambia por una copia del 1: la pieza es de un solo material.
    types = settings.get("filament_type") or []
    replaced = {i for i in range(1, min(count, len(colours)))
                if colours[i] and len(types) == count and types[i] != types[0]}
    per = _per_filament_keys()
    for key, value in list(settings.items()):
        if not isinstance(value, list):
            continue
        each = per.get(key)
        if each is None and key.startswith("filament_") and count > 2 and len(value) in (count, 2 * count, 4 * count):
            each = len(value) // count
        if each is not None and len(value) == each * count:
            chunks = [value[i * each:(i + 1) * each] for i in range(count)]
            chunks += [list(chunks[0]) for _ in range(total - count)]
            for i in replaced:
                chunks[i] = list(chunks[0])
            if key == "filament_self_index":
                chunks = [[str(i + 1)] * each for i in range(total)]
            settings[key] = [v for chunk in chunks for v in chunk]
    for key in ("filament_colour", "filament_multi_colour"):
        if key in settings:
            settings[key] = new
    limits = settings.get("filament_dev_ams_drying_ams_limitations")
    if isinstance(limits, list) and len(limits) == 2 * count - 1 and total > count:
        settings["filament_dev_ams_drying_ams_limitations"] = limits + limits[1:3] * (total - count)
    different = settings.get("different_settings_to_system")
    if isinstance(different, list) and len(different) == count + 2:
        middle = [different[1] if i in replaced else different[1 + i] for i in range(count)]
        settings["different_settings_to_system"] = (different[:1] + middle + [different[1]] * (total - count)
                                                    + different[-1:])
    matrix = settings.get("flush_volumes_matrix")
    if isinstance(matrix, list) and len(matrix) == count * count:
        # La purga mínima va por filamento de origen: lo que sobra de la fórmula en la tabla vieja.
        minimum = []
        for i in range(count):
            extra = sorted(float(matrix[i * count + j]) - flush_volume(old[i], old[j])
                           for j in range(count) if j != i)
            minimum.append(extra[len(extra) // 2] if extra else _DEFAULT_MIN_FLUSH)
        minimum += [minimum[0]] * (total - count)
        for i in replaced:
            minimum[i] = minimum[0]
        settings["flush_volumes_matrix"] = [
            "0" if i == j else str(round(flush_volume(new[i], new[j]) + minimum[i]))
            for i in range(total) for j in range(total)]
    return json.dumps(settings, indent=4, ensure_ascii=False).encode("utf-8")


def application_version(project_settings: bytes) -> str:
    """Valor de la metadata Application, con la versión que guardó esos ajustes."""
    try:
        version = json.loads(project_settings)["version"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Los ajustes de proyecto no son un JSON con «version»") from exc
    return f"BambuStudio-{version}"
