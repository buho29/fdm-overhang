# Formato de los archivos de Fusion

Lo que se elige o se mide en Fusion llega a slicer-paint como JSON, junto con el STL del cuerpo. Hay dos formatos para una pieza, y un archivo de [placa](#placa) para mandar varias juntas:

| | Selección (versión 2) | Pieza (versión 3) |
| --- | --- | --- |
| Lo escribe | `write_selection` de [fusion/export_selection.py](../fusion/export_selection.py) | Un add-in, como el botón *Enviar al laminador* de fdm-overhang |
| Contiene | Una selección | Cara de cama y una selección por papel |
| Se usa con | `--seam fusion:`, `--seam-block fusion:`, `--support-enforce fusion:`, `--support-block fusion:` | `--fusion ARCHIVO.json` |
| Papel | Lo decide la opción | Va dentro del archivo |

```powershell
slicer-paint Sinfin.stl -o Sinfin.3mf --fusion Sinfin.json --open orca
```

## Reglas comunes

- Todo en **mm** y en las **coordenadas del STL**: las mismas del diseño, sin orientar. slicer-paint aplica la misma orientación a la malla y al JSON.
- El STL tiene que ser **el mismo cuerpo, en la misma posición y la misma versión**. Si algo no cae sobre la malla, da error.
- Un solo cuerpo por archivo.
- JSON en UTF-8.

## Selección

```json
{
  "edges":   [[[x, y, z], [x, y, z], ...], ...],
  "faces":   [{"vertices": [[x, y, z], ...], "triangles": [[i, j, k], ...], "area": 123.4}, ...],
  "patches": [{"vertices": [[x, y, z], ...], "triangles": [[i, j, k], ...]}, ...]
}
```

Las tres listas son opcionales. Cada elemento se pinta así:

- **`edges`, aristas**: la polilínea de la arista, con puntos cada poco (`getStrokes` con 0,01 mm). Se pinta una franja de `--seam-radius` a cada lado (1 mm en soportes). Para forzar la costura, la arista tiene que subir respecto a las capas.
- **`faces`, caras enteras de B-Rep**: su malla, con la tolerancia que quieras, y el área exacta de `face.area` en mm². Se pintan los triángulos del STL que caen sobre ella, enteros, porque Fusion exporta el STL cara a cara. El sentido de los triángulos da igual. Avisa si el área reconocida en el STL no coincide con `area`.
- **`patches`, zonas**: un trozo de superficie que no coincide con una cara, como lo que queda por debajo del espacio mínimo. Se pinta lo que hay a menos de 0,2 mm de la zona, recortando los triángulos del STL. Por eso el borde sale unos 0,2-0,3 mm más ancho que la zona.
  - Los triángulos tienen que ir **orientados hacia fuera del cuerpo**, como los da la malla de Fusion. Aquí el sentido sí cuenta: en una ranura estrecha la pared de enfrente está más cerca que la tolerancia, y solo se distingue porque mira al revés.
  - No hace falta que los triángulos sean pequeños ni que formen una sola pieza: se subdividen hasta 0,25 mm al leerlos.
  - Una zona grande tarda: unos 10 s para 1300 mm² de un flanco helicoidal en un STL de 40 000 triángulos.

Se admiten también las claves informativas `version`, `units` (`"mm"`) y `body`.

## Pieza

```json
{
  "version": 3,
  "units": "mm",
  "body": "Sinfín",
  "bed": [0.0, 0.0, -1.0],
  "seam":    {"enforce": SELECCIÓN, "block": SELECCIÓN},
  "support": {"enforce": SELECCIÓN, "block": SELECCIÓN}
}
```

| Clave | Obligatoria | Qué es |
| --- | --- | --- |
| `version` | Sí | `3` |
| `units` | No | Solo `"mm"` |
| `body` | No | Nombre del cuerpo, para los mensajes |
| `bed` | No | Normal **hacia fuera** de la cara que va sobre la cama. *Plano XY (Z arriba)* es `[0, 0, -1]` y *Plano XZ (Y arriba)* es `[0, -1, 0]`. No hace falta normalizarla. Sin ella, la pieza se orienta sola |
| `seam.enforce` | No | Dónde forzar la costura |
| `seam.block` | No | Dónde prohibirla: aquí van las zonas de poca holgura |
| `support.enforce`, `support.block` | No | Dónde forzar o bloquear soportes. Solo actúa en lo que mira hacia abajo una vez orientada la pieza |

Tiene que haber al menos `bed` o una selección que no esté vacía. Una clave que no está en la tabla es un error, para que una errata no pase sin avisar.

**Cómo se combina con las opciones de la línea de comandos:**

- Las zonas del archivo se suman a las de `--seam`, `--seam-block`, `--support-enforce` y `--support-block`.
- Bloquear gana a forzar, venga de donde venga.
- `--orient` gana a `bed`.

## Ejemplo de pieza

Cama en el plano XY y prohibir la costura en un trozo de flanco:

```json
{
  "version": 3,
  "units": "mm",
  "body": "Sinfín",
  "bed": [0, 0, -1],
  "seam": {
    "block": {
      "patches": [
        {"vertices": [[10, 0, 2], [10, 5, 2], [10, 0, 7]], "triangles": [[0, 1, 2]]}
      ]
    }
  }
}
```

## Placa

Varias piezas, cada una con su STL y su archivo de pieza, en un solo 3MF y en una sola placa:

```powershell
slicer-paint --plate placa.json -o placa.3mf --open orca
```

```json
{
  "version": 1,
  "units": "mm",
  "parts": [
    {"stl": "Caja.stl", "fusion": "Caja.json", "name": "Caja"},
    {"stl": "Tapa.stl", "fusion": "Tapa.json"},
    {"stl": "Soporte.stl"}
  ]
}
```

| Clave | Obligatoria | Qué es |
| --- | --- | --- |
| `version` | Sí | `1` |
| `units` | No | Solo `"mm"` |
| `parts` | Sí | Lista de piezas, al menos una. Van a la placa en este orden |
| `parts[].stl` | Sí | Malla de la pieza: STL, OBJ o 3MF con una sola pieza |
| `parts[].fusion` | No | Su archivo de pieza (versión 3). Sin él, la pieza se orienta sola y no se pinta nada salvo lo que pida `--support-overhang` |
| `parts[].name` | No | Nombre del objeto en el laminador y en los mensajes. Por defecto, el nombre del STL sin extensión |

- Las rutas son relativas a la carpeta del archivo de placa. También se admiten rutas absolutas.
- Una clave que no está en la tabla es un error, en la placa y en cada pieza.
- Cada pieza se procesa como si fuera sola, con su archivo de pieza y las reglas de arriba.
- Con `--plate` no se pone malla de entrada. Las opciones de una sola pieza (`--orient`, `--part`, `--fusion`, `--seam`, `--seam-block`, `--support-enforce` y `--support-block`) dan error: lo que hacen va en el archivo de pieza de cada una. Las demás opciones valen para todas las piezas.
- Cada pieza es un objeto del 3MF con sus propios ajustes. Los soportes solo se activan en las piezas que tienen pintura de soportes.
- **Colocación:** en filas de izquierda a derecha, empezando por detrás, con 5 mm entre piezas y el conjunto centrado en la cama de la P1S (256 × 256 mm, sin la esquina delantera izquierda). Se usa la caja de cada pieza ya orientada y no se giran. Si no caben, el 3MF se escribe igual y avisa de que hay que ordenarlas en el laminador.
- **Errores:** dicen de qué pieza son, como `pieza 2 (Tapa): …`. Si una pieza falla no se escribe nada, y la salida es el código 2.
- La salida por consola da un resumen por pieza, que empieza con `Pieza N: nombre`, y al final `Escrito: placa.3mf (para orca, N piezas)`.
