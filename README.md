# Voladizos FDM (add-in de Fusion 360)

**Español** · [English](README.en.md)

Pinta encima del modelo lo que va a necesitar soporte, como la vista de soportes de un laminador:

- **rojo → naranja**: lo que mira hacia abajo con menos del ángulo límite desde la horizontal. El rojo puro es un techo plano y el naranja está justo por debajo del límite;
- **verde**: lo que apoya en la cama.

No modifica el diseño: son gráficos personalizados, no entran en la línea de tiempo y desaparecen al cerrar el diálogo.

Está en **DISEÑO > INSPECCIONAR > Voladizos FDM**.

![Voladizos a 45°](img/ejemplo.png)

Piezas de prueba vistas desde abajo con el límite en 45°: el tablero de la T es un techo plano (rojo), el cilindro tumbado y la esfera pasan de rojo a naranja, el cono con la pared a 30° de la horizontal sale naranja y el de 60° no se marca.

![Pieza real en sección, límite a 30°](img/seccion.png)

Una pieza real vista desde abajo y cortada con un análisis de sección, con el límite en 30° y la malla en calidad *Alta*: la bóveda interior sale en naranja y el borde que apoya en la cama, en verde. El diálogo da el área en voladizo, el peor ángulo y el área de apoyo.

## Diálogo

| Campo | Qué hace |
|---|---|
| Cuerpos | *Todos los visibles* (también los de las ocurrencias y los de malla) o *Elegidos* |
| Cama | *Plano XY (Z arriba)*, *Plano XZ (Y arriba)* o *Cara plana elegida*: la cara que irá sobre la cama, como el "colocar en cara" de los laminadores. Por defecto, según la orientación de modelado de Fusion |
| Cada cuerpo sobre la cama | Cada cuerpo se apoya en su punto más bajo. Sin marcar, la cama es el punto más bajo de todos (útil para un conjunto montado) |
| Ángulo límite (°) | Medido desde la horizontal, como en PrusaSlicer y Orca: 45° para la mayoría de materiales; 30° si la impresora y el material lo aguantan |
| Degradado | Rojo → naranja según la inclinación; sin marcar, todo rojo |
| Calidad de la malla | Teselado *Baja*, *Normal* o *Alta*. Las curvas se clasifican por triángulos: con más calidad, el borde de la zona marcada es más fino |
| Mantener al cerrar | La capa se queda al cerrar el diálogo y se recalcula cada vez que termina un comando que pueda cambiar el modelo. Para quitarla, se vuelve a abrir el diálogo y se desmarca. Solo dura mientras el diseño está abierto: no se guarda en el archivo |

En **Resultado** salen el área en voladizo (total, porcentaje de la superficie y por cuerpo), el ángulo del peor voladizo y el área apoyada en la cama, con un aviso si nada apoya en plano.

Lo que está justo en el límite (una gota o un chaflán a 45° exactos con el límite en 45°) no se marca: hay medio grado de margen.

## Instalación

### Windows

1. Descarga `FDMOverhang-<versión>.zip` de las [Releases](https://github.com/buho29/fdm-overhang/releases) y descomprímelo entero.
2. Haz doble clic en `instalar.bat`. Copia la carpeta `FDMOverhang` en la carpeta de complementos de Fusion y no pide permisos de administrador.
3. En Fusion: **Utilidades > Complementos** (Mayús+S) > *FDMOverhang* > **Ejecutar**, y marca *Al iniciar*.

Para actualizar, ejecuta el `instalar.bat` de la versión nueva: se conservan los últimos valores del diálogo. Para quitarlo, usa `desinstalar.bat`. No los uses en un equipo con la instalación de desarrollo de `install.ps1`: tendrías el complemento dos veces.

### Mac

Copia la carpeta `FDMOverhang` del zip a `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/`.

### Desde el repo (desarrollo)

Con Fusion cerrado:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

Registra la carpeta del repo en la lista de complementos de Fusion con *Ejecutar al inicio*. También se puede añadir a mano: **Utilidades > Complementos** (Mayús+S) > **+** > esta carpeta.

Para hacer una release: sube la versión en `FDMOverhang.manifest`, ejecuta `powershell -ExecutionPolicy Bypass -File installer\make_release.ps1` (deja el zip en `dist/`, que no va en git) y sube el zip a una Release de GitHub.

## Cómo funciona

1. Tesela cada cuerpo (`MeshManager`; en los cuerpos de malla, su propia malla) y lo pasa a coordenadas del raíz si está en una ocurrencia.
2. Clasifica cada triángulo por la normal media de sus vértices (la de la superficie): si mira hacia abajo, su inclinación desde la horizontal es `acos(-n·arriba)`.
3. Pinta los triángulos marcados con `CustomGraphicsMesh` y color por vértice. Fusion dibuja el cuerpo con su propia malla, así que la capa se aparta de la superficie, a lo largo de la normal, algo más que la mayor de las dos tolerancias (la de esa malla y la del análisis): si no, queda medio enterrada y se ve a manchas. Lo que no está marcado se ve con el aspecto normal del cuerpo.

La clasificación está en [overhang/analysis.py](overhang/analysis.py), sin dependencias de Fusion. Sus pruebas:

```
python -m unittest discover -s tests
```

## Licencia

MIT
