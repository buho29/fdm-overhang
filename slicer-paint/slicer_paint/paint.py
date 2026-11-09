"""Reglas de pintura de soportes y costura, sobre la malla ya orientada."""
from __future__ import annotations

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from .orient import overhang_mask
from .selection import Face, Patch, Selection
from .selector import BLOCK, DEFAULT_RESOLUTION, ENFORCE, Capsule, PaintLayer
from .selector import Patch as PatchRegion

# Una cara cuenta como pared si su normal se separa de la horizontal menos de 20°.
_WALL_MAX_NZ = np.sin(np.radians(20.0))
# La costura trasera acepta paredes girando hasta unos 30° respecto a +Y.
_BACK_MIN_NY = np.cos(np.radians(30.0))
# La franja de una arista no pinta suelos ni techos: en ellos no hay contorno que empiece ahí.
_EDGE_MAX_NZ = np.cos(np.radians(20.0))
# Por debajo de esta altura, una arista corre paralela a las capas (mm).
_EDGE_MIN_Z_SPAN = 0.2
# Una arista con menos pendiente solo la cruzan unas pocas capas.
_EDGE_MIN_SLOPE_DEG = 20.0
# Separación admitida entre la arista y la malla, por la cuerda de las curvas (mm).
_EDGE_ON_MESH_TOLERANCE = 0.2
_EDGE_CHECK_POINTS = 8
# Reconocer una cara en el STL: muestras de su malla cada tanto, distancia y ángulo admitidos.
_FACE_SAMPLE_MM = 0.25
_FACE_TOLERANCE_MM = 0.2
_FACE_MIN_COS = np.cos(np.radians(30.0))
# Una zona se pinta a esta distancia de sus muestras, que van cada _FACE_SAMPLE_MM: el borde
# queda con esta precisión (mm).
_PATCH_TOLERANCE_MM = 0.2
# Diferencia de área admitida entre la cara de Fusion y lo reconocido en el STL, sin avisar.
_FACE_AREA_TOLERANCE = 0.05
# Franja de soportes alrededor de una arista elegida en Fusion (mm).
SUPPORT_EDGE_RADIUS = 1.0
# Una caja de soportes actúa en caras que miran hacia abajo al menos este ángulo.
_DOWN_MIN_DEG = 1.0


def parse_box(text: str) -> tuple[np.ndarray, np.ndarray]:
    """Convierte x0,y0,z0,x1,y1,z1 en esquinas ordenadas."""
    values = [float(v) for v in text.split(",")]
    if len(values) != 6:
        raise ValueError(f"Una caja lleva seis números: {text!r}")
    corners = np.array(values).reshape(2, 3)
    return corners.min(axis=0), corners.max(axis=0)


def downward_mask(mesh: trimesh.Trimesh) -> np.ndarray:
    """Caras donde la pintura de soportes puede actuar: miran abajo y no apoyan en la cama."""
    return overhang_mask(mesh.face_normals, mesh.triangles_center[:, 2],
                         mesh.vertices[:, 2].min(), _DOWN_MIN_DEG)


def paint_supports(mesh: trimesh.Trimesh, overhang_deg: float | None = None,
                   enforce_boxes: list | None = None, block_boxes: list | None = None,
                   resolution: float = DEFAULT_RESOLUTION,
                   warnings: list[str] | None = None) -> PaintLayer:
    """Pintura de soportes. El ángulo pinta caras enteras; las cajas, justo lo que abarcan.

    Cada zona es una caja o una selección de Fusion, ya en coordenadas de la pieza orientada; en
    las dos, solo cuentan las caras que miran hacia abajo. Las zonas se aplican después del
    ángulo, y bloquear en último lugar: bloquear gana. Los avisos de las selecciones se añaden
    a warnings.
    """
    layer = PaintLayer(len(mesh.faces))
    if overhang_deg is not None:
        layer.set_faces(overhang_mask(mesh.face_normals, mesh.triangles_center[:, 2],
                                      mesh.vertices[:, 2].min(), overhang_deg), ENFORCE)
    down = downward_mask(mesh)
    warnings = [] if warnings is None else warnings
    for state, zones in ((ENFORCE, enforce_boxes or []), (BLOCK, block_boxes or [])):
        for zone in zones:
            if isinstance(zone, Selection):
                warnings += paint_selection(layer, mesh, zone, state, SUPPORT_EDGE_RADIUS,
                                                  resolution, where=down, seam=False)
            else:
                layer.apply_box(mesh.triangles, down, zone, state, resolution)
    return layer


def wall_mask(mesh: trimesh.Trimesh) -> np.ndarray:
    return np.abs(mesh.face_normals[:, 2]) < _WALL_MAX_NZ


def paint_seam(mesh: trimesh.Trimesh, rule: str | None,
               resolution: float = DEFAULT_RESOLUTION) -> PaintLayer:
    """Costura forzada: rule es back (paredes hacia +Y) o box:x0,y0,z0,x1,y1,z1."""
    layer = PaintLayer(len(mesh.faces))
    if rule is None:
        return layer
    if rule == "back":
        layer.set_faces(wall_mask(mesh) & (mesh.face_normals[:, 1] > _BACK_MIN_NY), ENFORCE)
    elif rule.startswith("box:"):
        layer.apply_box(mesh.triangles, wall_mask(mesh), parse_box(rule[4:]), ENFORCE, resolution)
    else:
        raise ValueError(f"Regla de costura no válida: {rule!r}. Usa back o box:x0,y0,z0,x1,y1,z1")
    return layer


def _distance_to_mesh(mesh: trimesh.Trimesh, points: np.ndarray) -> float:
    """Mayor distancia de unos puntos a la malla."""
    triangles = mesh.triangles
    worst = 0.0
    for point in points:
        closest = trimesh.triangles.closest_point(triangles, np.tile(point, (len(triangles), 1)))
        worst = max(worst, float(np.linalg.norm(closest - point, axis=1).min()))
    return worst


def face_mask(mesh: trimesh.Trimesh, face: Face) -> np.ndarray:
    """Triángulos del STL que caen sobre una cara de Fusion.

    Fusion exporta el STL cara a cara, así que cada triángulo es de una sola cara, aunque su malla
    no coincida con la de la cara exportada. Cuenta si sus vértices y su centro están sobre la cara
    y su normal es parecida a la de la cara en ese punto.
    """
    vertices, triangles = trimesh.remesh.subdivide_to_size(face.vertices, face.triangles,
                                                           _FACE_SAMPLE_MM)
    corners = vertices[triangles]
    centers = corners.mean(axis=1)
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    samples = cKDTree(np.vstack([vertices, centers]))
    near_vertex = samples.query(mesh.vertices, distance_upper_bound=_FACE_TOLERANCE_MM)[0]
    on_face = np.isfinite(near_vertex)[mesh.faces].all(axis=1)
    candidates = np.flatnonzero(on_face)
    distance, nearest = cKDTree(centers).query(mesh.triangles_center[candidates])
    # La orientación de la malla de Fusion no importa: se compara la dirección, no el sentido.
    alike = np.abs((mesh.face_normals[candidates] * normals[nearest]).sum(axis=1)) > _FACE_MIN_COS
    mask = np.zeros(len(mesh.faces), dtype=bool)
    mask[candidates[(distance <= _FACE_TOLERANCE_MM) & alike]] = True
    return mask


def patch_region(patch: Patch) -> tuple[PatchRegion, cKDTree, np.ndarray]:
    """Región de pintura de una zona, y sus centros y normales para comparar orientaciones."""
    vertices, triangles = trimesh.remesh.subdivide_to_size(patch.vertices, patch.triangles,
                                                           _FACE_SAMPLE_MM)
    corners = vertices[triangles]
    centers = corners.mean(axis=1)
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    region = PatchRegion(np.vstack([vertices, centers]), _PATCH_TOLERANCE_MM)
    return region, cKDTree(centers), normals


def patch_mask(mesh: trimesh.Trimesh, patch: Patch) -> tuple[np.ndarray, PatchRegion]:
    """Triángulos del STL que puede pintar una zona, y la región con que pintarlos.

    A diferencia de una cara, aquí cuenta el sentido de la normal: en una ranura estrecha, la pared
    de enfrente está a menos de la tolerancia, pero mira al revés.
    """
    region, centers, normals = patch_region(patch)
    candidates = np.flatnonzero(region.reach(mesh.triangles))
    _, nearest = centers.query(mesh.triangles_center[candidates])
    alike = (mesh.face_normals[candidates] * normals[nearest]).sum(axis=1) > _FACE_MIN_COS
    mask = np.zeros(len(mesh.faces), dtype=bool)
    mask[candidates[alike]] = True
    return mask, region


def paint_selection(layer: PaintLayer, mesh: trimesh.Trimesh, selection: Selection, state: int,
                    radius: float, resolution: float = DEFAULT_RESOLUTION,
                    where: np.ndarray | None = None, seam: bool = True) -> list[str]:
    """Pinta con state las caras enteras, las zonas y una franja alrededor de cada arista de la selección.

    La selección debe estar ya en coordenadas de la pieza orientada. where limita los triángulos
    que se pintan; por defecto, en la costura, las franjas no pintan suelos ni techos. Devuelve los
    avisos. Es un error una arista, cara o zona que no está sobre la malla, o forzar la costura en una
    arista que corre paralela a las capas.
    """
    if radius <= 0:
        raise ValueError(f"El radio de la franja debe ser positivo: {radius}")
    warnings: list[str] = []
    for number, face in enumerate(selection.faces, 1):
        mask = face_mask(mesh, face)
        found = float(mesh.area_faces[mask].sum())
        if where is not None:
            mask &= where
        if found == 0:
            raise ValueError(f"La cara {number} no está sobre la malla: "
                             "¿el STL es de otra versión o de otra posición?")
        if abs(found - face.area) > _FACE_AREA_TOLERANCE * face.area:
            warnings.append(f"La cara {number} mide {face.area:.1f} mm² en Fusion, pero en el STL "
                            f"solo se reconocen {found:.1f} mm²")
        if not mask.any():
            warnings.append(f"La cara {number} no tiene ningún triángulo donde pueda actuar esta pintura")
        layer.set_faces(mask, state)
    for number, patch in enumerate(selection.patches, 1):
        mask, region = patch_mask(mesh, patch)
        if not mask.any():
            raise ValueError(f"La zona {number} no está sobre la malla: "
                             "¿el STL es de otra versión o de otra posición?")
        if where is not None:
            mask &= where
        if not mask.any():
            warnings.append(f"La zona {number} no tiene ningún triángulo donde pueda actuar esta pintura")
        layer.apply_region(mesh.triangles, mask, region, state, resolution)
    if where is None:
        where = np.abs(mesh.face_normals[:, 2]) < _EDGE_MAX_NZ
    for number, edge in enumerate(selection.edges, 1):
        sample = edge[np.linspace(0, len(edge) - 1, min(len(edge), _EDGE_CHECK_POINTS)).astype(int)]
        off = _distance_to_mesh(mesh, sample)
        if off > _EDGE_ON_MESH_TOLERANCE:
            raise ValueError(f"La arista {number} está a {off:.2f} mm de la malla: "
                             "¿el STL es de otra versión o de otra posición?")
        if seam and state == ENFORCE:
            warnings += _edge_slope_warnings(number, edge, radius)
        layer.apply_region(mesh.triangles, where, Capsule(edge, radius), state, resolution)
    return warnings


def _edge_slope_warnings(number: int, edge: np.ndarray, radius: float) -> list[str]:
    """Para forzar la costura, la arista tiene que cruzar las capas."""
    span = float(np.ptp(edge[:, 2]))
    if span < _EDGE_MIN_Z_SPAN:
        raise ValueError(f"La arista {number} queda horizontal en esta orientación: corre paralela "
                         "a las capas y no indica dónde empezar el contorno")
    length = float(np.linalg.norm(np.diff(edge, axis=0), axis=1).sum())
    slope = float(np.degrees(np.arcsin(min(span / length, 1.0))))
    if slope >= _EDGE_MIN_SLOPE_DEG:
        return []
    # Cada capa corta la franja a lo largo de este tramo de arista.
    stretch = 2 * radius / np.tan(np.radians(max(slope, 0.1)))
    return [f"La arista {number} sube solo {slope:.0f}°: en cada capa, la franja abarca "
            f"unos {stretch:.0f} mm a lo largo del contorno, y la costura puede caer en "
            "cualquier punto de ese tramo. Si es una esquina hundida, el slicer suele "
            "elegirla; si no, prueba con un --seam-radius menor"]
