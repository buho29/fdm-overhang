"""Se ejecuta dentro de Fusion: guarda las aristas y caras seleccionadas para `--seam fusion:ARCHIVO`
o `--seam-block fusion:ARCHIVO`.

Solo usa la API de Fusion, porque su Python no tiene el resto de dependencias del proyecto.
"""
import json

import adsk.fusion

# Fusion trabaja siempre en cm.
_MM_PER_CM = 10.0
_STROKE_TOLERANCE_CM = 0.001
# Tolerancia de la malla de una cara. Solo sirve para reconocer sus triángulos en el STL.
_FACE_TOLERANCE_CM = 0.002


def _mm(point) -> list:
    return [round(v * _MM_PER_CM, 5) for v in point.asArray()]


def edge_polyline(edge) -> list:
    ok, start, end = edge.evaluator.getParameterExtents()
    ok_strokes, points = edge.evaluator.getStrokes(start, end, _STROKE_TOLERANCE_CM)
    if not (ok and ok_strokes):
        raise ValueError("No se pudo recorrer una arista")
    return [_mm(p) for p in points]


def face_mesh(face) -> dict:
    calculator = face.meshManager.createMeshCalculator()
    calculator.surfaceTolerance = _FACE_TOLERANCE_CM
    mesh = calculator.calculate()
    coords = mesh.nodeCoordinatesAsDouble
    indices = mesh.nodeIndices
    return {"area": round(face.area * _MM_PER_CM ** 2, 4),
            "vertices": [[round(v * _MM_PER_CM, 5) for v in coords[i:i + 3]]
                         for i in range(0, len(coords), 3)],
            "triangles": [list(indices[i:i + 3]) for i in range(0, len(indices), 3)]}


def selection_payload(entities) -> dict:
    """Aristas y caras de un mismo cuerpo, en mm y en las coordenadas del diseño."""
    bodies, edges, faces = set(), [], []
    for entity in entities:
        edge, face = adsk.fusion.BRepEdge.cast(entity), adsk.fusion.BRepFace.cast(entity)
        if edge is not None:
            bodies.add(edge.body.name)
            edges.append(edge_polyline(edge))
        elif face is not None:
            bodies.add(face.body.name)
            faces.append(face_mesh(face))
        else:
            raise ValueError("La selección tiene algo que no es una arista ni una cara")
    if not bodies:
        raise ValueError("No hay ninguna arista ni cara seleccionada")
    if len(bodies) > 1:
        raise ValueError(f"La selección es de varios cuerpos: {sorted(bodies)}")
    return {"version": 2, "units": "mm", "body": bodies.pop(), "edges": edges, "faces": faces}


def write_selection(ui, path: str) -> str:
    """Escribe la selección actual y devuelve un resumen."""
    entities = [ui.activeSelections.item(i).entity for i in range(ui.activeSelections.count)]
    payload = selection_payload(entities)
    with open(path, "w", encoding="utf-8") as out:
        json.dump(payload, out)
    return (f"{len(payload['edges'])} arista(s) y {len(payload['faces'])} cara(s) "
            f"de {payload['body']} en {path}")
