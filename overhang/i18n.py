# Textos en inglés. Los textos del código están en castellano y sirven de clave: tr(texto) devuelve la
# traducción si Fusion no está en castellano. Al añadir un texto con tr(), añade aquí su traducción,
# con los mismos % en el mismo orden.

LANG = 'es'


def set_language(name):
    """'es', 'es-ES', 'Spanish'… -> castellano; cualquier otro idioma -> inglés."""
    global LANG
    LANG = 'es' if name.lower().startswith(('es', 'spanish')) else 'en'


def tr(text):
    return text if LANG == 'es' else EN.get(text, text)


EN = {
    # ------------------------------------------------ nombres y diálogo
    'Voladizos FDM': 'FDM overhangs',
    'Pinta como un laminador lo que necesitará soporte: en rojo lo que mira hacia abajo con menos del '
    'ángulo límite desde la horizontal, en azul los puentes y en verde lo que apoya en la cama. '
    'No modifica el diseño.':
        'Paints what will need support, like a slicer: overhangs below the limit angle from the horizontal '
        'in red, bridges in blue and what rests on the bed in green. The design is not modified.',
    'Cerrar': 'Close',
    'Cuerpos': 'Bodies',
    'Todos los visibles': 'All visible',
    'Elegidos': 'Selected',
    'Selección': 'Selection',
    'Cama': 'Bed',
    'Plano XY (Z arriba)': 'XY plane (Z up)',
    'Plano XZ (Y arriba)': 'XZ plane (Y up)',
    'Cara plana elegida': 'Selected planar face',
    'Cara sobre la cama': 'Face on the bed',
    'Cada cuerpo sobre la cama': 'Each body on the bed',
    'Ángulo límite (°)': 'Limit angle (°)',
    'Degradado': 'Gradient',
    'Detectar puentes': 'Detect bridges',
    'Pinta en otro color los techos planos tendidos entre dos paredes, que se imprimen sin '
    'soporte si no son muy largos. Sin marcar, salen como voladizo.':
        'Paints flat ceilings spanning two walls in another color: they print without support if they are '
        'not too long. Unchecked, they show as overhangs.',
    'Puente máximo': 'Maximum bridge',
    'puente (hasta %s mm)': 'bridge (up to %s mm)',
    'Puentes: <b>%.0f mm²</b>, el más largo %s mm': 'Bridges: <b>%.0f mm²</b>, the longest %s mm',
    'Puente de %s mm, más que el máximo: sigue en rojo.': '%s mm bridge, over the maximum: it stays red.',
    'Calidad de la malla': 'Mesh quality',
    'Baja': 'Low',
    'Normal': 'Normal',
    'Alta': 'High',
    'Resultado': 'Result',
    'Mantener al cerrar': 'Keep when closed',
    'La capa se queda al cerrar el diálogo y se recalcula cada vez que cambia el modelo. '
    'Se quita al volver a abrir el diálogo. No se guarda en el archivo.':
        'The layer stays after closing the dialog and is recomputed whenever the model changes. '
        'It is removed when the dialog is opened again. It is not saved in the file.',
    'Analizar': 'Analyse',
    'Calcula con los ajustes actuales. Después, lo que no necesita volver a medir se actualiza solo.':
        'Computes with the current settings. After that, whatever does not need measuring again updates by itself.',
    'Pulsa <b>Analizar</b> para ver el resultado.': 'Press <b>Analyse</b> to see the result.',
    # ------------------------------------------------ espesor de pared
    'Espesor y espacios': 'Thickness and gaps',
    'Midiendo… %p %': 'Measuring… %p %',
    'Dibujando…': 'Drawing…',
    'Mapa de color del espesor de las paredes o del espacio entre superficies, de rojo (estrecho) a '
    'azul (ancho), o solo lo que no llega al mínimo. No modifica el diseño.':
        'Colour map of the wall thickness or of the gap between surfaces, from red (narrow) to blue (wide), '
        'or only what is below the minimum. The design is not modified.',
    'Medir': 'Measure',
    'Ver a través': 'See through',
    'Pone los cuerpos medidos en transparencia mientras el diálogo está abierto, para ver '
    'lo que queda por dentro. Al cerrar vuelven a su opacidad.':
        'Makes the measured bodies transparent while the dialog is open, to see what is inside. '
        'They go back to their opacity when it is closed.',
    'Espesor': 'Thickness',
    'Espacio': 'Gap',
    'Espesor: de cada pared hasta su otra cara. Espacio: de cada cara hasta lo que tiene '
    'delante, sea del mismo cuerpo o de otro.':
        'Thickness: from each wall to its other side. Gap: from each face to whatever is in front of it, '
        'in the same body or in another one.',
    'Espacio mínimo': 'Minimum gap',
    'El espacio mínimo tiene que ser mayor que 0.': 'The minimum gap must be greater than 0.',
    '%s Lo más estrecho: <b>%s mm</b> (%s)': '%s Narrowest: <b>%s mm</b> (%s)',
    'Por debajo de %s mm: <b>%.0f mm²</b>': 'Below %s mm: <b>%.0f mm²</b>',
    'Ninguna cara tiene otra enfrente.': 'No face has another one in front of it.',
    'Caras en contacto: %.0f mm²': 'Faces in contact: %.0f mm²',
    'Interferencia: <b>%.0f mm²</b> (%s)': 'Interference: <b>%.0f mm²</b> (%s)',
    'Espesor mínimo': 'Minimum thickness',
    'Pintar': 'Paint',
    'Mapa de color': 'Colour map',
    'Solo lo que no llega al mínimo': 'Only what is below the minimum',
    'Escala desde': 'Scale from',
    'Escala hasta': 'Scale to',
    'Resolución': 'Resolution',
    'Rápida (2 mm)': 'Fast (2 mm)',
    'Normal (1 mm)': 'Normal (1 mm)',
    'Fina (0,5 mm)': 'Fine (0.5 mm)',
    'Lado máximo de los triángulos con los que se mide. Más fina, más detalle y más lento.':
        'Maximum side of the triangles used to measure. Finer is more detailed and slower.',
    'La capa se queda al cerrar el diálogo, hasta que cambie alguno de los cuerpos o se '
    'vuelva a abrir el diálogo. No se guarda en el archivo.':
        'The layer stays after closing the dialog until one of the bodies changes or the dialog is opened '
        'again. It is not saved in the file.',
    'menos de %s mm': 'below %s mm',
    'en contacto': 'in contact',
    'interferencia': 'interference',
    'El espesor mínimo tiene que ser mayor que 0.': 'The minimum thickness must be greater than 0.',
    'El final de la escala tiene que ser mayor que el principio.': 'The end of the scale must be greater than its start.',
    '%s Lo más fino: <b>%s mm</b> (%s)': '%s Thinnest: <b>%s mm</b> (%s)',
    'Por debajo de %s mm: <b>%.0f mm²</b> (%.1f %% de la superficie)':
        'Below %s mm: <b>%.0f mm²</b> (%.1f %% of the surface)',
    'Malla abierta, puede medir de más: %s': 'Open mesh, it may measure too much: %s',
    'Espesor y espacios: error': 'Thickness and gaps: error',
    'No hay cuerpos sólidos que medir.': 'There are no solid bodies to measure.',
    # ------------------------------------------------ resultado
    'Abre un diseño (espacio de trabajo DISEÑO).': 'Open a design (DESIGN workspace).',
    'No hay cuerpos que analizar.': 'There are no bodies to analyse.',
    'Elige los cuerpos.': 'Select the bodies.',
    'Elige la cara plana que va sobre la cama.': 'Select the planar face that goes on the bed.',
    'voladizo (menos de %d° desde la horizontal)': 'overhang (below %d° from the horizontal)',
    'apoyo en la cama': 'on the bed',
    'Voladizo: <b>%.0f mm²</b> (%.1f %% de la superficie), el peor a %.0f°':
        'Overhang: <b>%.0f mm²</b> (%.1f %% of the surface), worst at %.0f°',
    'Sin voladizos.': 'No overhangs.',
    'Apoyo en la cama: %.0f mm²': 'On the bed: %.0f mm²',
    'Nada apoya en plano sobre la cama: reorienta la pieza o usa borde de adherencia.':
        'Nothing rests flat on the bed: reorient the part or use a brim.',
    '%d triángulos en %.2f s': '%d triangles in %.2f s',
    # ------------------------------------------------ enviar al laminador
    'Enviar al laminador': 'Send to slicer',
    'Exporta un cuerpo con su cama y con dónde forzar o prohibir la costura y los soportes, también donde '
    'hay poca holgura, y lo abre en el laminador con slicer-paint.':
        'Exports a body with its bed face and where to enforce or block the seam and supports, also where the '
        'clearance is small, and opens it in the slicer with slicer-paint.',
    'Enviar': 'Send',
    'Cuerpo': 'Body',
    'El cuerpo que vas a imprimir. Los demás cuerpos visibles solo cuentan al medir la holgura.':
        'The body you are going to print. The other visible bodies only count when measuring the clearance.',
    'No hay ningún cuerpo sólido visible.': 'There is no visible solid body.',
    'Costura': 'Seam',
    'Soportes': 'Supports',
    'Forzar en': 'Enforce on',
    'Prohibir en': 'Block on',
    'Bloquear en': 'Block on',
    'Aristas o caras donde poner la costura. Una arista solo vale si sube respecto a las capas.':
        'Edges or faces where the seam goes. An edge only works if it rises across the layers.',
    'Caras o aristas donde no puede ir la costura.': 'Faces or edges where the seam must not go.',
    'Caras donde forzar soportes. Solo cuenta lo que mire hacia abajo una vez orientada la pieza.':
        'Faces where supports are enforced. Only what faces down once the part is oriented counts.',
    'Caras donde no puede haber soportes.': 'Faces where supports are not allowed.',
    'Prohibir donde hay poca holgura': 'Block where clearance is small',
    'Mide el espacio delante de cada cara, como Espesor y espacios, y prohíbe la costura donde no llega al mínimo, '
    'toca otra pieza o se mete en ella: la costura abulta.':
        'Measures the space in front of each face, like Thickness and gaps, and blocks the seam where it is below '
        'the minimum, touches another part or goes into it: the seam bulges.',
    'Medir holgura': 'Measure clearance',
    'Mide ahora para ver en amarillo dónde se prohibirá la costura. Si no, se mide al enviar.':
        'Measures now to show in yellow where the seam will be blocked. Otherwise it is measured when sending.',
    'Abrir en': 'Open in',
    'No abrir': 'Do not open',
    'Malla del STL': 'STL mesh',
    'Baja (0,05 mm)': 'Low (0.05 mm)',
    'Media (0,025 mm)': 'Medium (0.025 mm)',
    'Alta (0,01 mm)': 'High (0.01 mm)',
    'Muy alta (0,003 mm)': 'Very high (0.003 mm)',
    'Separación máxima entre los triángulos y la superficie real. Alta basta para imprimir; Muy alta es la de Orca '
    'y Bambu Studio al importar un STEP, pero da muchos más triángulos y slicer-paint tarda más.':
        'Maximum distance between the triangles and the real surface. High is enough for printing; Very high is what '
        'Orca and Bambu Studio use when importing a STEP, but it gives many more triangles and slicer-paint takes '
        'longer.',
    'costura forzada': 'seam enforced',
    'costura prohibida': 'seam blocked',
    'soportes forzados': 'supports enforced',
    'soportes bloqueados': 'supports blocked',
    '%d arista': '%d edge',
    '%d aristas': '%d edges',
    '%d cara': '%d face',
    '%d caras': '%d faces',
    'Cuerpo: <b>%s</b>': 'Body: <b>%s</b>',
    'Cama: %s': 'Bed: %s',
    'Nada elegido a mano.': 'Nothing selected by hand.',
    'La holgura se mide al pulsar <b>Medir holgura</b> o al enviar.':
        'Clearance is measured when you press <b>Measure clearance</b> or when sending.',
    'poca holgura (menos de %s mm): %.0f mm², costura prohibida':
        'small clearance (below %s mm): %.0f mm², seam blocked',
    'Ninguna cara tiene menos de %s mm de holgura.': 'No face has less than %s mm of clearance.',
    'Lo elegido tiene que ser del cuerpo que se envía.': 'What you select must belong to the body being sent.',
    'No se pudo recorrer una arista.': 'An edge could not be traced.',
    'No encuentro slicer-paint: al enviar te preguntaré dónde está.':
        'slicer-paint not found: you will be asked where it is when sending.',
    '¿Dónde está slicer-paint? Si cancelas, solo se guardan el STL y el JSON':
        'Where is slicer-paint? If you cancel, only the STL and the JSON are saved',
    'Todos los archivos': 'All files',
    '%s no es slicer-paint.': '%s is not slicer-paint.',
    'No se pudo exportar el STL: %s': 'The STL could not be exported: %s',
    'El STL no está en las coordenadas del diseño: las zonas no caerían sobre la pieza.\n'
    'STL (mm): %s\nCuerpo (cm): %s':
        'The STL is not in the design coordinates: the zones would not land on the part.\n'
        'STL (mm): %s\nBody (cm): %s',
    'Guardados %s y %s.\n\nSin slicer-paint. Para generar el 3MF, ejecútalo a mano:\n%s':
        'Saved %s and %s.\n\nNo slicer-paint. To build the 3MF, run it by hand:\n%s',
    'slicer-paint ha fallado (código %d):': 'slicer-paint failed (code %d):',
    'Guardado: %s': 'Saved: %s',
    'Enviar al laminador: error': 'Send to slicer: error',
    # ------------------------------------------------ varias piezas en una placa
    'Este cuerpo': 'This body',
    'Varios en una placa': 'Several on one plate',
    'Un cuerpo en su 3MF, o varios en una sola placa: los marcados con Incluir en la placa, cada uno con lo que '
    'tenga elegido.':
        'One body in its own 3MF, or several on a single plate: those marked with Include on the plate, each with '
        'what was chosen for it.',
    'Incluir en la placa': 'Include on the plate',
    'Este cuerpo va en la placa. Lo elegido para cada cuerpo se guarda en el diseño.':
        'This body goes on the plate. What you choose for each body is saved in the design.',
    'Placa: <b>%s</b>': 'Plate: <b>%s</b>',
    'Ningún cuerpo en la placa: marca <b>Incluir en la placa</b>.':
        'No body on the plate: tick <b>Include on the plate</b>.',
    'Este cuerpo no va en la placa.': 'This body is not on the plate.',
    'Ningún cuerpo en la placa: marca Incluir en la placa en los que quieras enviar.':
        'No body on the plate: tick Include on the plate on those you want to send.',
    'placa': 'plate',
    'Guardados la placa %s y sus piezas.\n\nSin slicer-paint. Para generar el 3MF, ejecútalo a mano:\n%s':
        'Saved the plate %s and its parts.\n\nNo slicer-paint. To build the 3MF, run it by hand:\n%s',
    # ------------------------------------------------ errores
    'Voladizos FDM: error': 'FDM overhangs: error',
    'Voladizos FDM: error al arrancar': 'FDM overhangs: error on start',
    'Voladizos FDM: error al parar': 'FDM overhangs: error on stop',
    'Error interno del complemento:': 'Add-in internal error:',
}
