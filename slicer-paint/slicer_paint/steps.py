"""Pasos de montaje de la guía de ensamblaje de Bambu Studio (Metadata/assembly_step.json).

Solo los lee Bambu Studio (2.8 en adelante); Orca no los tiene. El formato sale de
AssemblyStepsJson.cpp de Bambu Studio 2.8.2: una lista de pasos ("sub") con sus piezas
("single"). Cada pieza se busca por su nombre de objeto, con object_idx como pista; la cámara
y las notas de cada paso (keyframes) son opcionales y Bambu las pone al editar la guía.

Comprobado el 2026-11-15 en Bambu Studio 2.8.2: con los pasos escritos así, la Lista de
ensamblaje dice en qué paso va cada pieza en vez de «Sin ensamblar», y al pulsar un paso se
abre su guía de montaje (tipo de unión, notas y línea de tiempo).
"""
from __future__ import annotations

import json

STEPS_FILE = "Metadata/assembly_step.json"
STEPS_VERSION = 1.1
FINAL_NAME = "Montaje final"
_FINAL = 1   # AssemblyStepKind::FinalAssembly


def _single(name: str, index: int) -> dict:
    return {"type": "single", "name": name, "object_idx": index, "keyframes": []}


def _step(name: str, children: list[dict], final: bool = False) -> dict:
    return {"type": "sub", "name": name, "is_final_assembly": _FINAL if final else 0,
            "keyframes": [], "children": children}


def _document(items: list[dict], title: str, extra: dict | None = None) -> bytes:
    """Los pasos se numeran en orden, desde 1. Uno sin id recibe uno nuevo; los que ya lo tienen
    lo conservan, porque inherited_from_step_id apunta a él."""
    used = [item["id"] for item in items if isinstance(item.get("id"), int)]
    fresh = max(used, default=0)
    for number, item in enumerate(items, 1):
        if not isinstance(item.get("id"), int):
            fresh += 1
            item["id"] = fresh
        item["step"] = number
    root = {"version": STEPS_VERSION, "assembly_part_number_label_font_size": 0.0,
            "camera_ref_viewport_w": 0, "camera_ref_viewport_h": 0,
            "pdf_export": {"title": title}, **(extra or {}), "items": items}
    return json.dumps(root, indent=2, ensure_ascii=False).encode("utf-8")


def build(names: list[str], title: str) -> bytes:
    """Un paso por pieza, en orden, y al final el montaje con todas."""
    items = [_step(name, [_single(name, i)]) for i, name in enumerate(names)]
    items.append(_step(FINAL_NAME, [_single(name, i) for i, name in enumerate(names)], final=True))
    return _document(items, title)


def _names_in(item: dict) -> set[str]:
    if item.get("type") == "single":
        return {item.get("name", "")}
    return set().union(*(_names_in(c) for c in item.get("children", []) if isinstance(c, dict)))


def _forget_object_ids(item: dict) -> None:
    """object_id es el id interno de Bambu en la sesión que guardó: en la siguiente puede ser el
    de otro objeto. Sin él, Bambu busca la pieza por object_idx y su nombre."""
    item.pop("object_id", None)
    for child in item.get("children", []):
        if isinstance(child, dict):
            _forget_object_ids(child)


def merge(saved: bytes, names: list[str], title: str) -> bytes | None:
    """Los pasos que se guardaron en Bambu, con las piezas nuevas añadidas: cada una en su paso,
    antes del montaje final, y también en él. None si lo guardado no se entiende."""
    try:
        root = json.loads(saved.decode("utf-8"))
        items = root["items"]
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            return None
    except (ValueError, KeyError, TypeError):
        return None
    for item in items:
        _forget_object_ids(item)
    present = set().union(*(_names_in(i) for i in items)) if items else set()
    missing = [(i, name) for i, name in enumerate(names) if name not in present]
    if missing:
        finals = [i for i, item in enumerate(items) if item.get("is_final_assembly") == _FINAL]
        at = finals[0] if finals else len(items)
        items[at:at] = [_step(name, [_single(name, i)]) for i, name in missing]
        for item in items[at + len(missing):]:
            if item.get("is_final_assembly") == _FINAL:
                item.setdefault("children", []).extend(_single(name, i) for i, name in missing)
    extra = {k: v for k, v in root.items() if k not in ("version", "items", "pdf_export")}
    pdf = root.get("pdf_export") if isinstance(root.get("pdf_export"), dict) else {}
    return _document(items, pdf.get("title") or title, extra)
