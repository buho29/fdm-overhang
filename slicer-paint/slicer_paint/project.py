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

import json
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


def application_version(project_settings: bytes) -> str:
    """Valor de la metadata Application, con la versión que guardó esos ajustes."""
    try:
        version = json.loads(project_settings)["version"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Los ajustes de proyecto no son un JSON con «version»") from exc
    return f"BambuStudio-{version}"
