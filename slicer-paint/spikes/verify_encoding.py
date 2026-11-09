"""Valida la codificación y la geometría de la pintura con la costura real de WormGear.3mf.

Comprueba dos cosas:
1. encode(decode(s)) devuelve cada cadena tal cual.
2. La pintura de un triángulo continúa en su vecino. Las dos caras de una arista se pintaron
   con el mismo pincel, así que deben coincidir si el orden de los hijos es el correcto. Se
   repite con el orden alterado: si no empeora, esta prueba no demuestra nada.
"""
from __future__ import annotations

import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from slicer_paint.reader import _read_meshes  # noqa: E402
from slicer_paint.selector import ENFORCE, Node, decode, encode, leaves  # noqa: E402

DEMO = Path(r"C:\wormgear\demo\3d files\WormGear.3mf")
PARTS = ["3D/Objects/object_16.model", "3D/Objects/object_12.model", "3D/Objects/object_10.model"]


def scramble(node: Node) -> Node:
    """Gira el orden de los hijos, simulando que la geometría fuera errónea."""
    if not node.is_split:
        return node
    children = [scramble(c) for c in node.children]
    return Node(sides=node.sides, special=node.special, children=children[1:] + children[:1])


def edge_intervals(vertices, faces, trees) -> dict[tuple[int, int], list[tuple[float, float]]]:
    """Por cada arista de cada triángulo pintado, los tramos de ambos lados, por separado."""
    result: dict[tuple[int, int], list] = defaultdict(list)
    for index, tree in trees.items():
        ids = faces[index]
        triangle = vertices[ids]
        own: dict[tuple[int, int], list[tuple[float, float]]] = {}
        for k in range(3):
            a, b = sorted((int(ids[k]), int(ids[(k + 1) % 3])))
            own[(a, b)] = []
        for leaf, state in leaves(triangle, tree):
            if state != ENFORCE:
                continue
            for key in own:
                start, end = vertices[key[0]], vertices[key[1]]
                direction = end - start
                length2 = direction @ direction
                if length2 == 0:
                    continue
                rel = leaf - start
                t = rel @ direction / length2
                off = np.linalg.norm(rel - np.outer(t, direction), axis=1)
                on_edge = off < 1e-6 * max(np.sqrt(length2), 1.0)
                if on_edge.sum() >= 2:
                    values = t[on_edge]
                    if values.max() - values.min() > 1e-9:
                        own[key].append((float(values.min()), float(values.max())))
        for key, spans in own.items():
            result[key].append(spans)
    return result


def union_length(spans: list[tuple[float, float]]) -> float:
    total, end = 0.0, -1.0
    for a, b in sorted(spans):
        if b > end:
            total += b - max(a, end)
            end = b
    return total


def agreement(vertices, faces, trees) -> float:
    """Longitud pintada común a los dos lados entre la pintada en cualquiera de ellos."""
    common = either = 0.0
    for sides in edge_intervals(vertices, faces, trees).values():
        first = sides[0]
        second = sides[1] if len(sides) > 1 else []
        both = union_length(first + second)
        either += both
        common += union_length(first) + union_length(second) - both
    return common / either if either else 0.0


def main() -> None:
    with zipfile.ZipFile(DEMO) as z:
        total = bad = 0
        for part in PARTS:
            mesh = _read_meshes(z.read(part), part)
            [painted] = mesh.values()
            strings = painted.paint["paint_seam"]
            for text in strings.values():
                total += 1
                bad += encode(decode(text)) != text
            trees = {i: decode(s) for i, s in strings.items()}
            scrambled = {i: scramble(t) for i, t in trees.items()}
            good = agreement(painted.vertices, painted.faces, trees)
            wrong = agreement(painted.vertices, painted.faces, scrambled)
            print(f"{part}: {len(trees)} triángulos, coincidencia en aristas {good:.1%}; "
                  f"con hijos alterados {wrong:.1%}")
    print(f"Cadenas: {total}, distintas tras recodificar: {bad}")


if __name__ == "__main__":
    main()
