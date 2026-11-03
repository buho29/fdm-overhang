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
    'ángulo límite desde la horizontal y en verde lo que apoya en la cama. No modifica el diseño.':
        'Paints what will need support, like a slicer: overhangs below the limit angle from the horizontal '
        'in red and what rests on the bed in green. The design is not modified.',
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
