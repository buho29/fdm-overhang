# Voladizos FDM (add-in de Fusion 360)

**Español** · [English](README.en.md)

Pinta encima del modelo lo que va a necesitar soporte, como la vista de soportes de un laminador:

- **rojo → naranja**: lo que mira hacia abajo con menos del ángulo límite desde la horizontal. El rojo puro es un techo plano y el naranja está justo por debajo del límite;
- **azul**: los puentes, techos planos tendidos entre dos paredes que no pasan del máximo;
- **verde**: lo que apoya en la cama.

No modifica el diseño: son gráficos personalizados, no entran en la línea de tiempo y desaparecen al cerrar el diálogo.

Está en **DISEÑO > INSPECCIONAR > Voladizos FDM**. En el mismo panel hay un segundo botón, [Espesor y espacios](#espesor-y-espacios), que pinta el espesor de las paredes o el espacio entre superficies.

![Voladizos a 45°](img/ejemplo.png)

Piezas de prueba vistas desde abajo con el límite en 45°: el tablero de la T es un techo plano (rojo), el cilindro tumbado y la esfera pasan de rojo a naranja, el cono con la pared a 30° de la horizontal sale naranja y el de 60° no se marca.

![Pieza real en sección, límite a 30°](img/seccion.png)

Una pieza real vista desde abajo y cortada con un análisis de sección, con el límite en 30° y la malla en calidad *Alta*: la bóveda interior sale en naranja y el borde que apoya en la cama, en verde. El diálogo da el área en voladizo, el peor ángulo y el área de apoyo.

![Puentes en un soporte de móvil](img/puentes.png)

Un soporte de móvil visto desde abajo: los dos puentes que no pasan de 23 mm salen en azul; el de 30 mm sigue en rojo y el resultado avisa. Lo que apoya en la cama, en verde.

## Diálogo

| Campo | Qué hace |
|---|---|
| Cuerpos | *Todos los visibles* (también los de las ocurrencias y los de malla) o *Elegidos* |
| Cama | *Plano XY (Z arriba)*, *Plano XZ (Y arriba)* o *Cara plana elegida*: la cara que irá sobre la cama, como el "colocar en cara" de los laminadores. Por defecto, según la orientación de modelado de Fusion |
| Cada cuerpo sobre la cama | Cada cuerpo se apoya en su punto más bajo. Sin marcar, la cama es el punto más bajo de todos (útil para un conjunto montado) |
| Ángulo límite (°) | Medido desde la horizontal, como en PrusaSlicer y Orca: 45° para la mayoría de materiales; 30° si la impresora y el material lo aguantan |
| Degradado | Rojo → naranja según la inclinación; sin marcar, todo rojo |
| Detectar puentes | Pinta en azul los techos planos tendidos entre paredes y descuenta su área del voladizo. Sin marcar, salen como voladizo |
| Puente máximo | Luz a partir de la cual un puente vuelve a salir en rojo, con un aviso. Por defecto 23 mm |
| Calidad de la malla | Teselado *Baja*, *Normal* o *Alta*. Las curvas se clasifican por triángulos: con más calidad, el borde de la zona marcada es más fino |
| Mantener al cerrar | La capa se queda al cerrar el diálogo y se recalcula cada vez que termina un comando que pueda cambiar el modelo. Se quita al volver a abrir el diálogo. Solo dura mientras el diseño está abierto: no se guarda en el archivo |

El diálogo se abre sin calcular nada: se ajustan los campos y se pulsa **Analizar**. A partir de ahí, lo que no necesita calcular de nuevo (el ángulo, el degradado, los puentes…) se actualiza al momento; si cambia algo que sí lo necesita (la calidad o los cuerpos), la capa se quita hasta volver a pulsar.

En **Resultado** salen el área en voladizo (total, porcentaje de la superficie y por cuerpo), el ángulo del peor voladizo, el área y la luz más larga de los puentes y el área apoyada en la cama, con un aviso si nada apoya en plano.

Lo que está justo en el límite (una gota o un chaflán a 45° exactos con el límite en 45°) no se marca: hay medio grado de margen.

**Qué cuenta como puente:** un techo horizontal cuyas líneas, en alguna dirección, van de una pared a otra; la luz es el tramo más largo en la dirección más corta. Se admite que algunas acaben en un borde libre, como en el extremo de una ventana en una pared curva: tiene que haber al menos la mitad de pared a pared. Un techo apoyado por un solo lado o por dos lados contiguos, o el tablero de una T, sigue en rojo. Tampoco cuentan los techos en arco o inclinados, ni un apoyo que sea a su vez voladizo o de otro cuerpo.

## Espesor y espacios

Segundo botón, en **DISEÑO > INSPECCIONAR > Espesor y espacios**. Pinta el espesor de las paredes o el espacio entre superficies, de rojo (estrecho) a azul (ancho), o solo lo que no llega al mínimo, y dice cuál es el punto más estrecho de cada cuerpo.

![Espesor](img/espesor.png)

El soporte de móvil con la escala de 0 a 4 mm y **Ver a través**: la pared curva pasa de azul a verde según se adelgaza hacia arriba y las puntas en cuña de la base llegan a naranja. Lo más fino, 0,19 mm, está en la cuna.

| Campo | Qué hace |
|---|---|
| Medir | *Espesor* o *Espacio* |
| Cuerpos | *Todos los visibles* o *Elegidos*. Las superficies no se miden. Con *Elegidos*, los espacios solo se miden entre ellos |
| Espesor mínimo / Espacio mínimo | Lo que no llega se cuenta en el resultado (área y ✖). Por ejemplo 0,8 mm de pared, dos pasadas de una boquilla de 0,4. Cada medida guarda su propio valor |
| Pintar | *Mapa de color* o *Solo lo que no llega al mínimo* (en rojo) |
| Escala desde / hasta | Medidas del rojo y del azul en el mapa de color. Cada medida guarda las suyas |
| Resolución | Lado máximo de los triángulos con los que se mide: *Rápida (2 mm)*, *Normal (1 mm)* o *Fina (0,5 mm)*. En los cuerpos de malla (un STL) se parten sus triángulos hasta ese tamaño |
| Ver a través | Pone los cuerpos medidos en transparencia mientras el diálogo está abierto, para ver lo que queda por dentro. Al cerrar vuelven a su opacidad, también con *Mantener al cerrar* |
| Mantener al cerrar | La capa se queda al cerrar el diálogo hasta que cambie alguno de los cuerpos o se vuelva a abrir el diálogo (fuera del diálogo no se puede recalcular). No se guarda en el archivo |

Igual que en Voladizos FDM, no se mide nada hasta pulsar **Analizar**. Las medidas se guardan mientras el diálogo está abierto: la escala, el mínimo o *Pintar* se actualizan al momento, y una resolución o unos cuerpos que aún no se han medido esperan al botón.

En **Resultado** salen lo más fino (y de qué cuerpo), el área por debajo del espesor mínimo y, con varios cuerpos, los dos datos de cada uno.

**Cómo mide el espesor:** desde el centro de cada triángulo lanza un rayo hacia dentro, perpendicular a la superficie, hasta la pared de enfrente. Fusion solo lanza rayos contra cuerpos de malla, así que en los sólidos crea uno temporal dentro de la vista previa y lo borra en seguida: no queda nada en el diseño ni en la línea de tiempo. No usa `PolygonMesh.wallThickness` de la API: mide por nodos y en las aristas curvas da casi 0 (0,03 mm en el canto de un tubo de 0,8).

**Límites:**

- El rayo que sale del canto de una pared la recorre a lo largo, no a lo ancho. Para corregirlo, cada triángulo toma el valor más fino de los que tocan con él en una arista convexa, así que el canto de una aleta de 0,4 sale de 0,4. En cantos anchos, de varias filas de triángulos, solo se corrige la primera fila: el centro puede salir más grueso de lo que es.
- Las paredes curvas miden un poco menos por la malla (0,79 en un tubo de 0,8).
- El texto grabado o en relieve tiene tabiques muy finos entre trazos y sale como lo más fino de la pieza. Es real: con una boquilla de 0,4 no se imprimen bien.

### Medir el espacio

Con **Medir: Espacio**, el rayo sale hacia fuera y mide el aire hasta lo que cada cara tiene delante: ranuras y agujeros estrechos del mismo cuerpo, u holguras con otro cuerpo.

![Espacios entre superficies](img/espacios.png)

Con **Ver a través** y la escala de 0 a 2 mm: el reborde de la tapa a 0,1 mm de la pared y el eje a 0,15 mm, en rojo anaranjado; la ranura de 0,25 y el pasador de la bisagra a 0,3, en naranja; un tetón metido 0,2 mm en la pared, en magenta; las caras donde la tapa apoya en la caja, en blanco.

![Espacio entre un sinfín y su rueda](img/sinfin.png)

Un sinfín y su rueda, generados con [WormGear](https://github.com/buho29/wormgear), en su posición de trabajo: el aire entre los flancos se cierra de azul a rojo en los dientes que engranan.

- Solo se pinta lo que entra en la escala. Lo que no tiene nada delante o queda más lejos no se pinta, aunque el resultado da el mínimo igualmente.
- Las caras que se tocan (hasta 0,01 mm) salen en blanco y se dan como área en contacto. Suelen quedar por dentro, así que se ven mejor con **Ver a través**. El borde va por triángulos: sale más limpio con una resolución más fina.
- Los cuerpos que se solapan salen en magenta y se dan como **interferencia**, con los cuerpos implicados.
- Hay 0,01 mm de margen con el espacio mínimo, porque es el error de la medida entre dos curvas: una holgura justa de 0,1 no se marca.
- Lo estrecho suele estar por dentro y no se ve desde fuera: para eso está **Ver a través**. Una sección apenas ayuda: las paredes de una rendija estrecha quedan de canto y no se ven. Ocultar un cuerpo tampoco sirve: con *Todos los visibles* deja de medirse.
- El rayo sale perpendicular a cada cara, así que una arista que pasa cerca de otra cara sin tenerla delante puede quedar sin medir: el mínimo real puede ser algo menor.

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
