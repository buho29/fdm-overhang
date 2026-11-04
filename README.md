# Voladizos FDM (add-in de Fusion 360)

**Español** · [English](README.en.md)

Pinta encima del modelo lo que va a necesitar soporte, como la vista de soportes de un laminador:

- **rojo → naranja**: lo que mira hacia abajo con menos del ángulo límite desde la horizontal. El rojo puro es un techo plano y el naranja está justo por debajo del límite;
- **verde**: lo que apoya en la cama.

No modifica el diseño: son gráficos personalizados, no entran en la línea de tiempo y desaparecen al cerrar el diálogo.

Está en **DISEÑO > INSPECCIONAR > Voladizos FDM**. En el mismo panel hay un segundo botón, [Espesor de pared](#espesor-de-pared), que pinta el espesor de las paredes.

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

## Espesor de pared

Segundo botón, en **DISEÑO > INSPECCIONAR > Espesor de pared**. Pinta el espesor de las paredes de rojo (fino) a azul (grueso), o solo lo que no llega al espesor mínimo, y dice cuál es el punto más fino de cada cuerpo.

![Espesor de pared](img/espesor.png)

Pieza de prueba con la escala de 0 a 4 mm: aletas de 0,4 a 3,2 mm (de naranja a azul claro), una aleta en cuña de 2,0 a 0,4 mm y un tubo de pared 0,8; las bases, de 3,2 y 4 mm, salen en azul claro y azul.

| Campo | Qué hace |
|---|---|
| Cuerpos | *Todos los visibles* o *Elegidos*. Las superficies no se miden: no tienen espesor |
| Espesor mínimo | Lo que no llega se cuenta en el resultado (área y ✖). Por ejemplo 0,8 mm, dos pasadas de una boquilla de 0,4 |
| Pintar | *Mapa de color* o *Solo lo que no llega al mínimo* (en rojo) |
| Escala desde / hasta | Espesores del rojo y del azul en el mapa de color |
| Resolución | Lado máximo de los triángulos con los que se mide: *Rápida (2 mm)*, *Normal (1 mm)* o *Fina (0,5 mm)* |
| Mantener al cerrar | La capa se queda al cerrar el diálogo hasta que cambie alguno de los cuerpos; entonces se quita y hay que volver a abrir el diálogo (fuera del diálogo no se puede recalcular). No se guarda en el archivo |

En **Resultado** salen lo más fino (y de qué cuerpo), el área por debajo del espesor mínimo y, con varios cuerpos, los dos datos de cada uno.

**Cómo mide:** desde el centro de cada triángulo lanza un rayo hacia dentro, perpendicular a la superficie, hasta la pared de enfrente. Fusion solo lanza rayos contra cuerpos de malla, así que en los sólidos crea uno temporal dentro de la vista previa y lo borra en seguida: no queda nada en el diseño ni en la línea de tiempo. No usa `PolygonMesh.wallThickness` de la API: mide por nodos y en las aristas curvas da casi 0 (0,03 mm en el canto de un tubo de 0,8).

**Límites:**

- El rayo que sale del canto de una pared la recorre a lo largo, no a lo ancho. Para corregirlo, cada triángulo toma el valor más fino de los que tocan con él en una arista convexa, así que el canto de una aleta de 0,4 sale de 0,4. En cantos anchos, de varias filas de triángulos, solo se corrige la primera fila: el centro puede salir más grueso de lo que es.
- Las paredes curvas miden un poco menos por la malla (0,79 en un tubo de 0,8).
- El texto grabado o en relieve tiene tabiques muy finos entre trazos y sale como lo más fino de la pieza. Es real: con una boquilla de 0,4 no se imprimen bien.

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
