# FDM overhangs (Fusion 360 add-in)

[Español](README.md) · **English**

Paints over the model what will need support, like a slicer's support preview:

- **red → orange**: faces pointing down at less than the limit angle from the horizontal. Pure red is a flat ceiling; orange is just below the limit;
- **green**: what rests on the bed.

The design is not modified: these are custom graphics, they don't go into the timeline and they disappear when the dialog is closed.

It is in **DESIGN > INSPECT > FDM overhangs**.

![Overhangs at 45°](img/ejemplo.png)

Test parts seen from below with the limit at 45°: the top of the T is a flat ceiling (red), the lying cylinder and the sphere go from red to orange, the cone with its wall at 30° from the horizontal is orange and the 60° one is not marked.

![Real part in section, limit at 30°](img/seccion.png)

A real part seen from below and cut with a section analysis, with the limit at 30° and *High* mesh quality: the inner vault is orange and the rim resting on the bed is green. The dialog gives the overhang area, the worst angle and the area on the bed.

## Dialog

| Field | What it does |
|---|---|
| Bodies | *All visible* (including those in occurrences and mesh bodies) or *Selected* |
| Bed | *XY plane (Z up)*, *XZ plane (Y up)* or *Selected planar face*: the face that goes on the bed, like the slicers' "place on face". Defaults to Fusion's modeling orientation |
| Each body on the bed | Each body rests on its own lowest point. Unchecked, the bed is the lowest point of all of them (useful for an assembly) |
| Limit angle (°) | Measured from the horizontal, as in PrusaSlicer and Orca: 45° for most materials; 30° if the printer and material can handle it |
| Gradient | Red → orange by inclination; unchecked, everything red |
| Mesh quality | *Low*, *Normal* or *High* tessellation. Curves are classified per triangle: higher quality gives a finer edge to the marked area |
| Keep when closed | The layer stays after closing the dialog and is recomputed after every command that may change the model. To remove it, open the dialog again and uncheck this. It only lasts while the design is open: it is not saved in the file |

**Result** shows the overhang area (total, percentage of the surface and per body), the angle of the worst overhang and the area on the bed, with a warning if nothing rests flat on it.

Faces exactly at the limit (a teardrop or a chamfer at exactly 45° with the limit at 45°) are not marked: there is a half-degree margin.

## Installation

With Fusion closed:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

It registers the repo folder in Fusion's add-in list with *Run on startup*. It can also be added by hand: **Utilities > Add-ins** (Shift+S) > **+** > this folder.

## How it works

1. Tessellates each body (`MeshManager`; mesh bodies use their own mesh) and moves it to root coordinates if it is in an occurrence.
2. Classifies each triangle by the average normal of its vertices (the surface normal): if it points down, its inclination from the horizontal is `acos(-n·up)`.
3. Paints the marked triangles with a `CustomGraphicsMesh` with per-vertex colours, on top of the body (`depthPriority`). Unmarked areas keep the body's normal appearance.

The classification is in [overhang/analysis.py](overhang/analysis.py), with no Fusion dependencies. Its tests:

```
python -m unittest discover -s tests
```

## License

MIT
