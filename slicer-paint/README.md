# slicer-paint

Orienta una o varias piezas, pinta soportes y costura y genera un 3MF que se abre en OrcaSlicer o Bambu Studio sin fork ni plugin.

## Instalación

Forma parte de [fdm-overhang](../README.md), cuyo botón *Enviar al laminador* lo usa, pero funciona solo. Con [pipx](https://pipx.pypa.io):

```powershell
pipx install "git+https://github.com/buho29/fdm-overhang#subdirectory=slicer-paint"
```

Para desarrollo, en esta carpeta:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
```

## Uso

```powershell
slicer-paint pieza.stl -o pieza.3mf --support-overhang 45 --seam back --open orca
```

| Opción | Qué hace |
| --- | --- |
| `--plate` | Archivo de placa con varias piezas, cada una con su STL y su archivo de pieza; todas van a un solo 3MF. Ver [Varias piezas en una placa](#varias-piezas-en-una-placa) |
| `--fusion` | Archivo de pieza de Fusion (versión 3) con la cara de cama, la costura y los soportes; se suma a las demás opciones. Ver [docs/formato-fusion.md](docs/formato-fusion.md) |
| `--orient` | `auto` (por defecto), `none`, `face:-z` o `face:x,y,z` (la cara con esa normal a la cama) o `rot:rx,ry,rz` en grados; gana a la cama de `--fusion` |
| `--overhang-limit` | Voladizo admitido al puntuar orientaciones; 45° por defecto |
| `--support-overhang N` | Fuerza soportes en las caras que vuelan más de N° (0° es una pared y 90° un techo) |
| `--support-enforce`, `--support-block` | Fuerza o bloquea soportes en una caja `x0,y0,z0,x1,y1,z1` o en `fusion:archivo.json`, las caras y aristas elegidas en Fusion; solo en caras que miran hacia abajo, se puede repetir y bloquear gana a forzar |
| `--support-mode` | `manual` (solo donde se pinta, por defecto) o `auto` (el slicer añade los que calcule) |
| `--support-style` | `normal` (por defecto) o `tree` |
| `--seam` | Fuerza la costura: `back` (paredes hacia +Y), `box:x0,y0,z0,x1,y1,z1`, solo en paredes, o `fusion:archivo.json`, las aristas y caras elegidas en Fusion |
| `--seam-block` | Prohíbe la costura en `box:x0,y0,z0,x1,y1,z1`, solo en paredes, o en `fusion:archivo.json`; se puede repetir y prohibir gana a forzar |
| `--seam-radius` | Con `fusion:`, ancho de la franja a cada lado de una arista; 0,5 mm por defecto |
| `--part` | Pieza de un 3MF de entrada, por su archivo interno, como `object_16` |
| `--paint-resolution` | Precisión del borde de las cajas, en mm; 0,25 por defecto |
| `--target` | Slicer de destino, `orca` o `bambu`; por defecto el de `--open`, o `orca` |
| `--project-settings` | Con destino `bambu`, ajustes de otro `.3mf` o `.config` en vez de la plantilla P1S |
| `--fresh` | Si el 3MF de salida ya existe, no conserva las opciones de impresión que guardó el laminador. Ver [Volver a generar el 3MF](#volver-a-generar-el-3mf) |
| `--open` | Abre el resultado en `orca` o `bambu`; las rutas se cambian con `SLICER_PAINT_ORCA` y `SLICER_PAINT_BAMBU` |

## Volver a generar el 3MF

Si el 3MF de salida ya existe y lo guardaste desde el laminador, se conservan sus opciones de impresión al reescribirlo:

- **El proyecto:** impresora, filamentos y proceso, con cualquier cambio que hicieras.
- **Cada objeto, por su nombre:** el filamento que le asignaste y sus ajustes propios, como las paredes o el relleno. `enable_support` y `support_type` los decide la pintura de soportes.
- **La placa:** su nombre y los ajustes que cambiaste solo para ella.

La geometría, la orientación, la colocación en la cama y la pintura salen de nuevo. Los modificadores, las piezas añadidas en el laminador y las placas que no sean la primera se pierden.

Solo se conservan las opciones del laminador de destino. Orca escribe al guardar la misma metadata `Application` que Bambu Studio y además una metadata `OrcaSlicer`, y por esa se distinguen. Si el archivo se guardó con el otro laminador, avisa y empieza de cero. `--project-settings` gana al proyecto guardado, y `--fresh` no conserva nada.

## Varias piezas en una placa

```powershell
slicer-paint --plate placa.json -o placa.3mf --open orca
```

El archivo de placa enumera las piezas: el STL de cada una, su archivo de pieza (opcional) y su nombre (opcional, por defecto el del STL). Las rutas son relativas a la carpeta del archivo de placa. El formato está en [docs/formato-fusion.md](docs/formato-fusion.md#placa).

- Cada pieza se procesa como si fuera sola: se orienta con la cama de su archivo de pieza, o sola si no la tiene, y se pintan su costura y sus soportes.
- Las opciones generales valen para todas: `--overhang-limit`, `--support-overhang`, `--support-mode`, `--support-style`, `--seam-radius`, `--paint-resolution`, `--target`, `--project-settings`, `--fresh` y `--open`.
- `--orient`, `--part`, `--fusion`, `--seam`, `--seam-block`, `--support-enforce` y `--support-block` son de una sola pieza y dan error con `--plate`. Lo que hacen va en el archivo de pieza de cada una.
- Cada pieza es un objeto con sus propios ajustes: `enable_support` solo va en las que tienen pintura de soportes.
- Las piezas se colocan en filas sobre la cama de la P1S, con 5 mm entre ellas, y el conjunto se centra. Si no caben, el archivo se escribe igual y avisa: hay que ordenarlas en el laminador.
- Los avisos y errores dicen de qué pieza son. Si una pieza falla, no se escribe nada y sale con código 2.

Las cajas usan las coordenadas de la pieza ya orientada, con Z mínima 0 y sin el centrado en la cama. Si una caja empieza por un número negativo, escríbela con `=`: `--support-block=-60,0,-1,0,50,60`.

## Costura con lo seleccionado en Fusion

1. Selecciona en Fusion aristas o caras de un mismo cuerpo.
2. Ejecuta `write_selection` de [fusion/export_selection.py](fusion/export_selection.py) dentro de Fusion para escribir el JSON, y exporta el cuerpo a STL.
3. Genera el 3MF, forzando la costura, prohibiéndola o las dos cosas con dos selecciones:

```powershell
slicer-paint pieza.stl -o pieza.3mf --seam fusion:arista.json --seam-block fusion:caras.json
```

- **Una arista** se pinta como una franja de `--seam-radius` a cada lado. Para forzar la costura marca un punto en cada capa: da error si queda horizontal al orientar la pieza y avisa si sube menos de 20°.
- **Una cara** se pinta entera. Para forzar la costura es una zona, no un punto: el slicer la pone en cualquier sitio de ella. Para prohibirla, el slicer elige libremente fuera.

Un add-in puede escribir en un solo archivo de pieza la cara de cama, la costura y los soportes, y también **zonas** que no son caras enteras, como lo que queda por debajo de una holgura. Se pasa con `--fusion`. Los dos formatos están en [docs/formato-fusion.md](docs/formato-fusion.md).

El JSON va en las coordenadas del STL, y la herramienta aplica la misma orientación a las dos cosas. Da error si una arista o una cara no está sobre la malla, y avisa si el área de una cara no coincide con la que se reconoce en el STL. Solo afecta a los contornos que tocan lo seleccionado: agujeros e islas separadas siguen poniendo la costura donde decida el slicer. Si en una capa todo el contorno está prohibido, el slicer tiene que ponerla igualmente en algún sitio.

## Formato

- Cada `<triangle>` lleva `paint_supports` y `paint_seam`. Para un triángulo entero, `4` es forzar y `8` es bloquear.
- Una caja que cruza un triángulo lo divide solo dentro de la pintura, sin tocar la malla. La cadena es el árbol de `TriangleSelector`: ver [selector.py](slicer_paint/selector.py).
- Cada pieza va en su `3D/Objects/object_N.model`. `Metadata/model_settings.config` lleva la placa y los ajustes de cada objeto.
- Para que la pintura de soportes actúe hace falta `enable_support=1` en el objeto. Sin él, ninguno de los slicers genera soportes. La herramienta lo añade si hay pintura de soportes.

Cada slicer necesita su variante, y un archivo no sirve para el otro:

| | Destino `orca` | Destino `bambu` |
| --- | --- | --- |
| Ajustes de proyecto | No lleva, salvo los que guardó Orca | Proyecto P1S completo, o el que guardó Bambu |
| Metadata `Application` | No lleva; con ella sola, Orca rechaza el archivo. Con los ajustes que guardó Orca, va la suya y `OrcaSlicer` | `BambuStudio-<versión de los ajustes>` |
| Presets al abrir | Los que tengas seleccionados | Los del proyecto, con 5 filamentos y 0,20 mm |

Sin proyecto completo, Bambu Studio carga solo la geometría y la pintura, y borra `enable_support` y `support_type`. Entonces hay que activar los soportes a mano.

## Límites

- Las reglas por ángulo y `--seam back` pintan triángulos enteros, porque el límite ya es la cara. Solo las cajas y las aristas recortan.
- Un triángulo enorme limita la precisión de una caja: se divide hasta 8 niveles, y eso deja unos 0,4 mm en una arista de 100 mm.
- Una sola placa por archivo.
- La colocación en filas no gira las piezas ni las encaja: si así no caben, hay que usar *Organizar* en el laminador.
- `--seam back` pinta todas las paredes orientadas a +Y, no solo la exterior.

## Verificación

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe spikes\verify_encoding.py
.venv\Scripts\python.exe spikes\verify_slicers.py roundtrip bambu orca_nightly orca_243
.venv\Scripts\python.exe spikes\verify_slicers.py slice bambu orca_nightly orca_243
.venv\Scripts\python.exe spikes\verify_tapa.py bambu orca_nightly orca_243
.venv\Scripts\python.exe spikes\verify_arista.py prisma.stl bambu orca_nightly orca_243 --edges a.json b.json c.json
.venv\Scripts\python.exe spikes\verify_caras.py sinfin.stl bambu orca_nightly orca_243 --block caras.json
.venv\Scripts\python.exe spikes\verify_placa.py bambu orca_nightly orca_243
```

Los scripts de `spikes/` usan los slicers instalados y las rutas de este PC. Por línea de comandos, Orca recoloca las piezas de un 3MF que no es un proyecto de Bambu, y `verify_placa.py` le pasa `--arrange 0`. La interfaz las deja donde están.
