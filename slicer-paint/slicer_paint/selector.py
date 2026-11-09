"""Pintura por partes de un triángulo: el árbol de TriangleSelector y su cadena hexadecimal.

Cada triángulo de la malla se guarda como un árbol, en un flujo de nibbles:
- Hoja: 2 bits a cero y 2 bits de estado (4 es forzar y 8 es bloquear).
- División: 2 bits con el número de lados divididos y 2 con special_side, seguidos
  de los hijos del último al primero.
La cadena se escribe al revés que el flujo, de modo que la raíz es el último carácter.
La malla no cambia: la subdivisión solo existe dentro de la pintura.

Ojo: si la cadena está mal formada, el slicer deja el triángulo sin pintar y no avisa.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree

# Estados de pintura. Coinciden con EnforcerBlockerType de los slicers.
NONE, ENFORCE, BLOCK = 0, 1, 2
# Estado de face_states() para un triángulo pintado solo en parte.
MIXED = -1
DEFAULT_RESOLUTION = 0.25
# Limita el tamaño de la cadena: 8 niveles dejan 0,4 mm en una arista de 100 mm.
MAX_DEPTH = 8
_EPS = 1e-9
# Pares punto-tramo por bloque al medir la distancia a una polilínea.
_DISTANCE_PAIRS = 200_000
# Con tan pocos tramos, medir a todos es más rápido que buscar los cercanos.
_FEW_SEGMENTS = 32


@dataclass
class Node:
    state: int = NONE
    sides: int = 0
    special: int = 0
    children: list["Node"] = field(default_factory=list)

    @property
    def is_split(self) -> bool:
        return self.sides > 0


def encode(node: Node) -> str:
    nibbles: list[int] = []

    def visit(current: Node) -> None:
        if current.is_split:
            nibbles.append(current.sides | (current.special << 2))
            for child in reversed(current.children):
                visit(child)
        else:
            nibbles.append(current.state << 2)

    visit(node)
    return "".join(f"{n:X}" for n in reversed(nibbles))


def decode(text: str) -> Node:
    """Convierte una cadena en su árbol. Rechaza lo que un slicer descartaría."""
    nibbles = [int(c, 16) for c in reversed(text)]
    position = 0

    def read() -> Node:
        nonlocal position
        if position >= len(nibbles):
            raise ValueError(f"Cadena de pintura incompleta: {text[:40]!r}")
        value = nibbles[position]
        position += 1
        sides, high = value & 0b11, value >> 2
        if sides == 0:
            if high == 0b11:
                raise ValueError(f"Estado de varios colores no admitido: {text[:40]!r}")
            return Node(state=high)
        # En el flujo van del último al primero.
        children = [read() for _ in range(sides + 1)]
        return Node(sides=sides, special=high, children=children[::-1])

    root = read()
    if position != len(nibbles):
        raise ValueError(f"Cadena de pintura con datos de más: {text[:40]!r}")
    return root


def split_triangle(triangle: np.ndarray, sides: int, special: int) -> list[np.ndarray]:
    """Hijos de un triángulo, en el orden de TriangleSelector::perform_split."""
    v0, v1, v2 = triangle[special], triangle[(special + 1) % 3], triangle[(special + 2) % 3]
    if sides == 1:
        m12 = (v1 + v2) / 2
        return [np.array([v0, v1, m12]), np.array([m12, v2, v0])]
    if sides == 2:
        m01, m20 = (v0 + v1) / 2, (v2 + v0) / 2
        return [np.array([v0, m01, m20]), np.array([m01, v1, m20]), np.array([v1, v2, m20])]
    m01, m12, m20 = (v0 + v1) / 2, (v1 + v2) / 2, (v2 + v0) / 2
    return [np.array([v0, m01, m20]), np.array([m01, v1, m12]),
            np.array([m12, v2, m20]), np.array([m01, m12, m20])]


def leaves(triangle: np.ndarray, node: Node) -> list[tuple[np.ndarray, int]]:
    """Geometría y estado de cada hoja del árbol."""
    if not node.is_split:
        return [(triangle, node.state)]
    result: list[tuple[np.ndarray, int]] = []
    for sub, child in zip(split_triangle(triangle, node.sides, node.special), node.children):
        result.extend(leaves(sub, child))
    return result


def triangle_area(triangle: np.ndarray) -> float:
    return float(np.linalg.norm(np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])) / 2)


def overlaps_box(triangle: np.ndarray, box: tuple[np.ndarray, np.ndarray]) -> bool:
    """Prueba de ejes separadores triángulo-caja. Solo tocarse no cuenta como solape."""
    center, half = (box[0] + box[1]) / 2, (box[1] - box[0]) / 2
    points = triangle - center
    edges = points[[1, 2, 0]] - points
    normal = np.cross(edges[0], edges[1])
    axes = [np.eye(3)[i] for i in range(3)] + [normal]
    axes += [np.cross(np.eye(3)[i], edge) for i in range(3) for edge in edges]
    for axis in axes:
        if np.allclose(axis, 0):
            continue
        projection = points @ axis
        radius = np.abs(axis) @ half
        if projection.min() >= radius - _EPS or projection.max() <= -radius + _EPS:
            return False
    return True


class Box:
    """Zona de pintura: una caja de esquinas ordenadas."""
    # reach mira solo las cajas envolventes; may_touch es más estricto (tocar no cuenta).
    reach_is_touch = False

    def __init__(self, low: np.ndarray, high: np.ndarray):
        self.low, self.high = low, high

    def reach(self, triangles: np.ndarray) -> np.ndarray:
        return (triangles.max(axis=1) >= self.low).all(axis=1) & (
            triangles.min(axis=1) <= self.high).all(axis=1)

    def may_touch(self, triangle: np.ndarray) -> bool:
        return overlaps_box(triangle, (self.low, self.high))

    def contains(self, points: np.ndarray) -> np.ndarray:
        return ((points >= self.low - _EPS) & (points <= self.high + _EPS)).all(axis=-1)

    def holds(self, points: np.ndarray) -> bool:
        return bool(self.contains(points.reshape(-1, 3)).all())


class Capsule:
    """Zona de pintura: lo que queda a menos de radius de una polilínea, como la franja de una arista."""
    reach_is_touch = True   # may_touch es reach de un solo triángulo

    def __init__(self, polyline: np.ndarray, radius: float):
        self.start, self.end = polyline[:-1], polyline[1:]
        self.radius = radius
        self._tree: cKDTree | None = None

    def _near(self, points: np.ndarray, limit: float | np.ndarray) -> np.ndarray:
        """Distancia de cada punto a la polilínea, exacta donde no pasa de limit (uno o uno por
        punto); más lejos, cualquier valor mayor que limit. Solo mide los tramos cercanos, que
        se buscan por su punto medio: con limit no se pierde ninguno que pueda estar más cerca."""
        if len(self.start) <= _FEW_SEGMENTS:
            return self.distance(points)
        if self._tree is None:
            self._tree = cKDTree((self.start + self.end) / 2)
            self._half = float(np.linalg.norm(self.end - self.start, axis=1).max()) / 2
        result = np.full(len(points), np.inf)
        if not len(points) or not len(self.start):
            return result
        lists = self._tree.query_ball_point(points, np.broadcast_to(limit, len(points)) + self._half + _EPS)
        counts = np.fromiter(map(len, lists), dtype=np.int64, count=len(lists))
        if not counts.sum():
            return result
        segment = np.fromiter(itertools.chain.from_iterable(lists), dtype=np.int64, count=int(counts.sum()))
        point = np.repeat(np.arange(len(points)), counts)
        along = self.end[segment] - self.start[segment]
        offset = points[point] - self.start[segment]
        t = np.clip((offset * along).sum(axis=1) / np.maximum((along * along).sum(axis=1), 1e-12), 0, 1)
        np.minimum.at(result, point, np.linalg.norm(offset - t[:, None] * along, axis=1))
        return result

    def distance(self, points: np.ndarray) -> np.ndarray:
        """Distancia de cada punto a la polilínea."""
        along = self.end - self.start
        length2 = np.maximum((along * along).sum(axis=1), 1e-12)
        # Por bloques: una hélice tiene cientos de tramos, y todos los pares a la vez no caben en memoria.
        chunk = max(1, _DISTANCE_PAIRS // len(along))
        result = np.empty(len(points))
        for first in range(0, len(points), chunk):
            offset = points[first:first + chunk, None, :] - self.start
            t = np.clip((offset * along).sum(axis=2) / length2, 0, 1)
            result[first:first + chunk] = np.linalg.norm(offset - t[:, :, None] * along, axis=2).min(axis=1)
        return result

    def reach(self, triangles: np.ndarray) -> np.ndarray:
        centers = triangles.mean(axis=1)
        sizes = np.linalg.norm(triangles - centers[:, None, :], axis=2).max(axis=1)
        limit = self.radius + sizes
        # Antes, descarta de una vez lo que está lejos de la caja de la polilínea.
        low = np.minimum(self.start, self.end).min(axis=0)
        high = np.maximum(self.start, self.end).max(axis=0)
        gap = np.linalg.norm(np.maximum(np.maximum(low - centers, centers - high), 0), axis=1)
        result = np.zeros(len(centers), dtype=bool)
        near = np.flatnonzero(gap <= limit + _EPS)
        result[near] = self._near(centers[near], limit[near]) <= limit[near]
        return result

    def may_touch(self, triangle: np.ndarray) -> bool:
        return bool(self.reach(triangle[None])[0])

    def contains(self, points: np.ndarray) -> np.ndarray:
        return self._near(points, self.radius) <= self.radius

    def holds(self, points: np.ndarray) -> bool:
        return bool(self.contains(points.reshape(-1, 3)).all())

    def around(self, triangle: np.ndarray) -> "Capsule":
        """La misma zona con solo los tramos que pueden tocar el triángulo, para subdividirlo más deprisa."""
        center = triangle.mean(axis=0)
        reach = self.radius + np.linalg.norm(triangle - center, axis=1).max()
        along = self.end - self.start
        t = np.clip(((center - self.start) * along).sum(axis=1)
                    / np.maximum((along * along).sum(axis=1), 1e-12), 0, 1)
        near = np.linalg.norm(center - self.start - t[:, None] * along, axis=1) <= reach + _EPS
        local = Capsule(np.zeros((2, 3)), self.radius)
        local.start, local.end = self.start[near], self.end[near]
        return local


class Patch:
    """Zona de pintura: lo que queda a menos de tolerance de unos puntos que cubren una superficie.

    Los puntos tienen que estar más juntos que tolerance para que no queden huecos.
    """
    reach_is_touch = True

    def __init__(self, samples: np.ndarray, tolerance: float):
        self.tree = cKDTree(samples)
        self.tolerance = tolerance

    def reach(self, triangles: np.ndarray) -> np.ndarray:
        centers = triangles.mean(axis=1)
        sizes = np.linalg.norm(triangles - centers[:, None, :], axis=2).max(axis=1)
        return self.tree.query(centers)[0] <= self.tolerance + sizes

    def may_touch(self, triangle: np.ndarray) -> bool:
        return bool(self.reach(triangle[None])[0])

    def contains(self, points: np.ndarray) -> np.ndarray:
        return self.tree.query(points)[0] <= self.tolerance

    def holds(self, points: np.ndarray) -> bool:
        return bool(self.contains(points.reshape(-1, 3)).all())


def paint_region(node: Node, triangle: np.ndarray, region: Box | Capsule | Patch, state: int,
                 resolution: float = DEFAULT_RESOLUTION, depth: int = 0) -> Node:
    """Devuelve el árbol con la parte del triángulo dentro de la zona pintada con state."""
    if not region.may_touch(triangle):
        return node
    if region.holds(triangle):
        return Node(state=state)
    if not node.is_split:
        longest = max(np.linalg.norm(triangle[i] - triangle[(i + 1) % 3]) for i in range(3))
        if longest < resolution or depth >= MAX_DEPTH:
            return Node(state=state) if region.holds(triangle.mean(axis=0)) else node
        node = Node(sides=3, children=[Node(state=node.state) for _ in range(4)])
    subs = split_triangle(triangle, node.sides, node.special)
    children = [paint_region(child, sub, region, state, resolution, depth + 1)
                for child, sub in zip(node.children, subs)]
    # Si todo queda igual, una hoja basta y la cadena es más corta.
    first = children[0]
    if not first.is_split and all(not c.is_split and c.state == first.state for c in children):
        return Node(state=first.state)
    return Node(sides=node.sides, special=node.special, children=children)


def paint_leaves(triangles: np.ndarray, old: np.ndarray, region: Capsule | Patch, state: int,
                 resolution: float = DEFAULT_RESOLUTION) -> list[Node]:
    """paint_region de muchos triángulos sin dividir (hojas con estado old), con el mismo
    resultado: se va nivel a nivel y cada nivel se mide de una vez. Solo para zonas cuyo reach
    es may_touch (reach_is_touch)."""
    levels = []
    tris = triangles
    for depth in range(MAX_DEPTH + 1):
        touch = region.reach(tris) if len(tris) else np.zeros(0, dtype=bool)
        inside = np.zeros(len(tris), dtype=bool)
        inside[touch] = region.contains(tris[touch].reshape(-1, 3)).reshape(-1, 3).all(axis=1)
        longest = np.linalg.norm(tris - tris[:, [1, 2, 0]], axis=2).max(axis=1)
        last = touch & ~inside & ((longest < resolution) | (depth >= MAX_DEPTH))
        fill = inside.copy()
        fill[last] = region.contains(tris[last].mean(axis=1))
        split = touch & ~inside & ~last
        levels.append((old, fill, split))
        if not split.any():
            break
        # Los cuatro hijos de cada uno, en el orden de split_triangle(…, 3, 0).
        v0, v1, v2 = tris[split, 0], tris[split, 1], tris[split, 2]
        m01, m12, m20 = (v0 + v1) / 2, (v1 + v2) / 2, (v2 + v0) / 2
        tris = np.stack([np.stack(c, axis=1) for c in
                         ((v0, m01, m20), (m01, v1, m12), (m12, v2, m20), (m01, m12, m20))],
                        axis=1).reshape(-1, 3, 3)
        old = np.repeat(old[split], 4)
    below: list[Node] = []
    for old, fill, split in reversed(levels):
        nodes, child = [], 0
        for i in range(len(old)):
            if split[i]:
                children = below[child:child + 4]
                child += 4
                first = children[0]
                if not first.is_split and all(not c.is_split and c.state == first.state for c in children):
                    nodes.append(Node(state=first.state))
                else:
                    nodes.append(Node(sides=3, special=0, children=children))
            else:
                nodes.append(Node(state=state if fill[i] else int(old[i])))
        below = nodes
    return below


def paint_box(node: Node, triangle: np.ndarray, box: tuple[np.ndarray, np.ndarray], state: int,
              resolution: float = DEFAULT_RESOLUTION) -> Node:
    return paint_region(node, triangle, Box(*box), state, resolution)


class PaintLayer:
    """Pintura de un tipo (soportes o costura) para toda la malla."""

    def __init__(self, face_count: int):
        self.face_count = face_count
        self.nodes: dict[int, Node] = {}

    @classmethod
    def from_states(cls, states: np.ndarray) -> "PaintLayer":
        layer = cls(len(states))
        for index in np.flatnonzero(states):
            layer.nodes[int(index)] = Node(state=int(states[index]))
        return layer

    def set_faces(self, mask: np.ndarray, state: int) -> None:
        """Pinta triángulos enteros."""
        for index in np.flatnonzero(mask):
            self.nodes[int(index)] = Node(state=state)

    def apply_region(self, triangles: np.ndarray, mask: np.ndarray, region: Box | Capsule | Patch, state: int,
                     resolution: float = DEFAULT_RESOLUTION) -> None:
        """Pinta lo que cae dentro de la zona, solo en los triángulos de mask.

        Los triángulos sin pintura dividida se pintan todos a la vez con paint_leaves; uno a uno
        se tardaba mucho (unos 20 s en un sinfín con una hélice de 768 tramos). Los demás, y
        todos con una caja, con paint_region.
        """
        reached = np.flatnonzero(mask & region.reach(triangles))
        if not len(reached):
            return
        batch = np.zeros(len(reached), dtype=bool)
        if region.reach_is_touch:
            batch = np.array([not self.nodes.get(int(i), Node()).is_split for i in reached], dtype=bool)
            old = np.array([self.nodes.get(int(i), Node()).state for i in reached[batch]], dtype=np.int64)
            for index, node in zip(reached[batch], paint_leaves(triangles[reached[batch]], old, region,
                                                                state, resolution)):
                self._set(int(index), node)
        for index in reached[~batch]:
            key = int(index)
            local = region.around(triangles[key]) if isinstance(region, Capsule) else region
            self._set(key, paint_region(self.nodes.get(key, Node()), triangles[key], local, state, resolution))

    def _set(self, key: int, node: Node) -> None:
        if node.is_split or node.state != NONE:
            self.nodes[key] = node
        else:
            self.nodes.pop(key, None)

    def apply_box(self, triangles: np.ndarray, mask: np.ndarray,
                  box: tuple[np.ndarray, np.ndarray], state: int,
                  resolution: float = DEFAULT_RESOLUTION) -> None:
        self.apply_region(triangles, mask, Box(*box), state, resolution)

    def string(self, index: int) -> str | None:
        node = self.nodes.get(index)
        if node is None or (not node.is_split and node.state == NONE):
            return None
        return encode(node)

    def is_painted(self) -> bool:
        return bool(self.nodes)

    def face_states(self) -> np.ndarray:
        """Estado de cada triángulo; MIXED si está pintado solo en parte."""
        states = np.full(self.face_count, NONE, dtype=np.int8)
        for index, node in self.nodes.items():
            states[index] = MIXED if node.is_split else node.state
        return states

    def areas(self, triangles: np.ndarray) -> dict[int, float]:
        """Área pintada por estado."""
        pieces: dict[int, list[np.ndarray]] = {ENFORCE: [], BLOCK: []}
        whole: dict[int, list[int]] = {ENFORCE: [], BLOCK: []}
        for index, node in self.nodes.items():
            if not node.is_split:
                if node.state in whole:
                    whole[node.state].append(index)
                continue
            for leaf, state in leaves(triangles[index], node):
                if state in pieces:
                    pieces[state].append(leaf)
        total = {}
        for state in pieces:
            parts = [triangles[whole[state]]] + ([np.array(pieces[state])] if pieces[state] else [])
            t = np.concatenate(parts).reshape(-1, 3, 3)
            total[state] = float(np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() / 2)
        return total
