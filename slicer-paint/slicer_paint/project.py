"""Ajustes de proyecto para los archivos destinados a Bambu Studio.

Bambu Studio 02.08.02.60 considera inválido un 3MF sin `nozzle_diameter` ni un `printer_model`
de Bambu, y entonces carga solo la geometría y borra los ajustes por objeto, como
`enable_support` (Plater.cpp, check_project_config). Una configuración parcial tampoco sirve,
porque la completa con valores por defecto y pisa los presets. Hace falta un proyecto completo,
y al abrir el archivo se usan sus presets en lugar de los seleccionados.

Orca, en cambio, rechaza estos ajustes y la metadata Application, por eso hay dos destinos.
"""
from __future__ import annotations

import json
import zipfile
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


def application_version(project_settings: bytes) -> str:
    """Valor de la metadata Application, con la versión que guardó esos ajustes."""
    try:
        version = json.loads(project_settings)["version"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Los ajustes de proyecto no son un JSON con «version»") from exc
    return f"BambuStudio-{version}"
