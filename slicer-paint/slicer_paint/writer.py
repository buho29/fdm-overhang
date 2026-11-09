"""Escritura de 3MF con pintura de costura y soportes por triángulo.

La estructura es la mínima que Bambu Studio y OrcaSlicer cargan sin avisos y
respetando los ajustes por objeto (comprobado en spikes/ con ambos slicers):

- Cada pieza va en su 3D/Objects/object_N.model, y Metadata/model_settings.config lleva la
  placa y los ajustes de cada una.
- Se declara BambuStudio:3mfVersion. Sin ajustes de proyecto NO se declara "Application":
  con ella, Orca rechaza el archivo y Bambu falla por línea de comandos.
- Con ajustes de proyecto (destino Bambu, ver project.py) se añaden los ajustes y "Application".
  Orca no abre esa variante.
- Si se conservan las opciones de un 3MF que Orca guardó, van sus ajustes con su Application y
  su metadata OrcaSlicer: así Orca lo reconoce como suyo.
"""
from __future__ import annotations

import io
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from .project import PROJECT_FILE, application_version
from .selector import BLOCK, ENFORCE, NONE, PaintLayer  # noqa: F401  (estados reexportados)

# Centro de la cama de la Bambu Lab P1S (256×256).
P1S_BED_CENTER = (128.0, 128.0)

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
BAMBU_NS = "http://schemas.bambulab.com/package/2021"
PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MODEL_REL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
XML_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n'

CONTENT_TYPES = f"""{XML_HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="gcode" ContentType="text/x.gcode"/>
</Types>
"""
ROOT_RELS = f"""{XML_HEAD}<Relationships xmlns="{RELS_NS}">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="{MODEL_REL}"/>
</Relationships>
"""
_MODEL_ATTRS = (f'unit="millimeter" xml:lang="en-US" xmlns="{CORE_NS}" '
                f'xmlns:BambuStudio="{BAMBU_NS}" xmlns:p="{PROD_NS}" requiredextensions="p"')
_VERSION_META = ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'


@dataclass
class PlateObject:
    """Una pieza de la placa. Los vértices van ya orientados; center es dónde queda el centro
    de su caja en la cama."""
    vertices: np.ndarray
    faces: np.ndarray
    support: PaintLayer | np.ndarray | None = None
    seam: PaintLayer | np.ndarray | None = None
    name: str = "pieza"
    settings: dict[str, str] = field(default_factory=dict)
    center: tuple[float, float] = P1S_BED_CENTER


def _ids(number: int) -> tuple[int, int]:
    """Identificadores de la malla y de su envoltorio para la pieza number (desde 1), como
    los numera Bambu Studio: 1 y 2, 3 y 4..."""
    return 2 * number - 1, 2 * number


def _object_path(number: int) -> str:
    return f"3D/Objects/object_{number}.model"


def _as_layer(paint: PaintLayer | np.ndarray | None) -> PaintLayer | None:
    """Admite una PaintLayer o un vector con el estado de cada triángulo."""
    if paint is None or isinstance(paint, PaintLayer):
        return paint
    return PaintLayer.from_states(np.asarray(paint))


def _write_mesh(out: io.TextIOBase, vertices: np.ndarray, faces: np.ndarray,
                support: PaintLayer | None, seam: PaintLayer | None) -> None:
    """Escribe <mesh> en streaming; las mallas pueden tener millones de triángulos."""
    out.write("<mesh>\n<vertices>\n")
    for x, y, z in vertices:
        out.write(f'<vertex x="{x:.8g}" y="{y:.8g}" z="{z:.8g}"/>\n')
    out.write("</vertices>\n<triangles>\n")
    for i, (a, b, c) in enumerate(faces):
        attrs = ""
        support_text = support.string(i) if support else None
        seam_text = seam.string(i) if seam else None
        if support_text:
            attrs += f' paint_supports="{support_text}"'
        if seam_text:
            attrs += f' paint_seam="{seam_text}"'
        out.write(f'<triangle v1="{a}" v2="{b}" v3="{c}"{attrs}/>\n')
    out.write("</triangles>\n</mesh>\n")




def _keyed(values: dict[str, str], indent: str) -> str:
    return "".join(f"{indent}<metadata key={quoteattr(k)} value={quoteattr(v)}/>\n"
                   for k, v in values.items())


def _object_settings(number: int, obj: PlateObject) -> str:
    part_id, wrapper_id = _ids(number)
    face_count = len(obj.faces)
    settings = _keyed({"extruder": "1", **obj.settings}, "    ")
    return f"""  <object id="{wrapper_id}">
    <metadata key="name" value={quoteattr(obj.name)}/>
{settings}    <metadata face_count="{face_count}"/>
    <part id="{part_id}" subtype="normal_part" uuid="{uuid.uuid4()}">
      <metadata key="name" value={quoteattr(obj.name)}/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
      <mesh_stat face_count="{face_count}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
    </part>
  </object>
"""


def _model_instance(number: int) -> str:
    return f"""    <model_instance>
      <metadata key="object_id" value="{_ids(number)[1]}"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="{number}"/>
    </model_instance>
"""


def _model_settings(objects: list[PlateObject], plate_settings: dict[str, str]) -> str:
    """Ajustes de cada objeto y una sola placa con todos ellos."""
    numbers = range(1, len(objects) + 1)
    plate = {"plater_name": "", "locked": "false", **plate_settings}
    return (f"{XML_HEAD}<config>\n"
            + "".join(_object_settings(n, obj) for n, obj in zip(numbers, objects))
            + "  <plate>\n"
            '    <metadata key="plater_id" value="1"/>\n'
            + _keyed(plate, "    ")
            + "".join(_model_instance(n) for n in numbers)
            + "  </plate>\n</config>\n")


def _item_transform(vertices: np.ndarray, center: tuple[float, float]) -> str:
    """Lleva el centro de la caja de la pieza a center y su Z mínima a 0."""
    mins, maxs = vertices.min(axis=0), vertices.max(axis=0)
    tx = center[0] - (mins[0] + maxs[0]) / 2
    ty = center[1] - (mins[1] + maxs[1]) / 2
    return f"1 0 0 0 1 0 0 0 1 {tx:.6f} {ty:.6f} {-mins[2]:.6f}"


def _write_object(z: zipfile.ZipFile, number: int, obj: PlateObject) -> None:
    with z.open(_object_path(number), "w", force_zip64=True) as raw:
        out = io.TextIOWrapper(raw, encoding="utf-8", newline="\n")
        out.write(f'{XML_HEAD}<model {_MODEL_ATTRS}>\n{_VERSION_META}<resources>\n'
                  f'<object id="{_ids(number)[0]}" p:UUID="{uuid.uuid4()}" type="model">\n')
        _write_mesh(out, obj.vertices, obj.faces, _as_layer(obj.support), _as_layer(obj.seam))
        out.write("</object>\n</resources>\n<build/>\n</model>\n")
        out.flush()
        out.detach()


def _main_model(objects: list[PlateObject], main_meta: str) -> str:
    wrappers, items = [], []
    for number, obj in enumerate(objects, 1):
        part_id, wrapper_id = _ids(number)
        wrappers.append(
            f'<object id="{wrapper_id}" p:UUID="{uuid.uuid4()}" type="model">\n<components>\n'
            f'<component p:path="/{_object_path(number)}" objectid="{part_id}" '
            f'p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n'
            f'</components>\n</object>\n')
        items.append(f'<item objectid="{wrapper_id}" p:UUID="{uuid.uuid4()}" '
                     f'transform="{_item_transform(obj.vertices, obj.center)}" printable="1"/>\n')
    return (f'{XML_HEAD}<model {_MODEL_ATTRS}>\n{main_meta}<resources>\n{"".join(wrappers)}'
            f'</resources>\n<build p:UUID="{uuid.uuid4()}">\n{"".join(items)}</build>\n</model>\n')


def _model_rels(count: int) -> str:
    relations = "".join(
        f' <Relationship Target="/{_object_path(n)}" Id="rel-{n}" Type="{MODEL_REL}"/>\n'
        for n in range(1, count + 1))
    return f'{XML_HEAD}<Relationships xmlns="{RELS_NS}">\n{relations}</Relationships>\n'


def write_plate(path: str | Path, objects: list[PlateObject],
                project_settings: bytes | None = None, *,
                metadata: list[tuple[str, str]] | None = None,
                plate_settings: dict[str, str] | None = None) -> None:
    """Escribe un 3MF con una o varias piezas en una sola placa.

    Cada pieza va en su propio 3D/Objects/object_N.model, con su envoltorio, su <item> y sus
    ajustes. Se coloca con la transformación del <item>, sin tocar los vértices; así la malla
    queda tal como se pintó. Sin ajustes de proyecto, Orca abre el archivo con los presets
    que tenga seleccionados.

    metadata sustituye a la Application que se deduce de los ajustes de proyecto: es la del
    3MF que el laminador guardó, cuando se conservan sus opciones (ver project.read_previous).
    plate_settings son ajustes de la placa, como los de esa misma placa guardada.
    """
    if not objects:
        raise ValueError("Una placa necesita al menos una pieza")
    objects = [PlateObject(np.asarray(o.vertices, dtype=float), np.asarray(o.faces, dtype=np.int64),
                           o.support, o.seam, o.name, o.settings, o.center) for o in objects]
    main_meta = _VERSION_META
    if project_settings is not None and metadata is None:
        metadata = [("Application", application_version(project_settings))]
    if metadata:
        main_meta = "".join(f" <metadata name={quoteattr(k)}>{escape(v)}</metadata>\n"
                            for k, v in metadata) + _VERSION_META

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        for number, obj in enumerate(objects, 1):
            _write_object(z, number, obj)
        z.writestr("3D/3dmodel.model", _main_model(objects, main_meta))
        z.writestr("3D/_rels/3dmodel.model.rels", _model_rels(len(objects)))
        z.writestr("Metadata/model_settings.config", _model_settings(objects, plate_settings or {}))
        if project_settings is not None:
            z.writestr(PROJECT_FILE, project_settings)


def write_3mf(path: str | Path, vertices: np.ndarray, faces: np.ndarray,
              support: PaintLayer | np.ndarray | None = None,
              seam: PaintLayer | np.ndarray | None = None,
              *, name: str = "pieza", bed_center: tuple[float, float] = P1S_BED_CENTER,
              object_settings: dict[str, str] | None = None,
              project_settings: bytes | None = None) -> None:
    """Escribe un 3MF con una sola pieza, centrada en la cama y apoyada en Z=0."""
    write_plate(path, [PlateObject(vertices, faces, support, seam, name,
                                   object_settings or {}, bed_center)], project_settings)
