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
    'Para quitarla, vuelve a abrir el diálogo y desmárcala. No se guarda en el archivo.':
        'The layer stays after closing the dialog and is recomputed whenever the model changes. '
        'To remove it, open the dialog again and uncheck this. It is not saved in the file.',
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
    'La capa se queda al cerrar el diálogo, hasta que cambie alguno de los cuerpos: '
    'entonces se quita y hay que volver a abrir el diálogo. No se guarda en el archivo.':
        'The layer stays after closing the dialog until one of the bodies changes: then it is removed and '
        'the dialog has to be opened again. It is not saved in the file.',
    'menos de %s mm': 'below %s mm',
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
    # ------------------------------------------------ errores
    'Voladizos FDM: error': 'FDM overhangs: error',
    'Voladizos FDM: error al arrancar': 'FDM overhangs: error on start',
    'Voladizos FDM: error al parar': 'FDM overhangs: error on stop',
    'Error interno del complemento:': 'Add-in internal error:',
}
