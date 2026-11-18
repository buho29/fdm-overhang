# Add-in de Fusion 360 con tres comandos en INSPECCIONAR:
# - "Voladizos FDM" (overhang/ui/overhang_cmd.py): pinta encima del modelo, como la vista de soportes de un
#   laminador, lo que mira hacia abajo con menos del ángulo límite desde la horizontal (rojo -> naranja), los puentes
#   (azul) y lo que apoya en la cama (verde).
# - "Espesor y espacios" (overhang/ui/thickness_cmd.py): mapa de color del espesor de las paredes o del espacio entre
#   superficies (rojo lo estrecho -> azul lo ancho), o solo lo que no llega al mínimo.
#   Los dos son gráficos personalizados: no tocan el diseño ni la línea de tiempo y se borran al cerrar el diálogo.
# - "Enviar al laminador" (overhang/ui/slicer_cmd.py): exporta uno o varios cuerpos en STL con su cama y dónde forzar
#   o prohibir la costura y los soportes, y los pasa a slicer-paint, que genera el 3MF pintado.
# La API sin diálogo está en overhang/ui/api.py; aquí se reexporta. Las cuentas, sin Fusion y con pruebas, están en
# overhang/*.py. Este archivo solo registra los botones y los eventos.
import importlib
import os
import sys
import traceback

import adsk.core
import adsk.fusion

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# En orden de dependencias. Al reiniciar el add-in, Fusion vuelve a ejecutar este archivo pero no los módulos ya
# importados: se recargan aquí, cada uno después de los que usa.
_MODULES = ('overhang.i18n', 'overhang.analysis', 'overhang.thickness', 'overhang.slicer', 'overhang.pick',
            'overhang.ui.common', 'overhang.ui.slicer_cmd', 'overhang.ui.overhang_cmd', 'overhang.ui.thickness_cmd',
            'overhang.ui.api')
for _name in _MODULES:
    if _name in sys.modules:
        importlib.reload(sys.modules[_name])
    else:
        importlib.import_module(_name)

from overhang.i18n import tr, set_language  # noqa: E402
from overhang.ui import overhang_cmd as OV, thickness_cmd as TH, slicer_cmd as SL, api as API  # noqa: E402
from overhang.ui.common import (  # noqa: E402
    API_GROUP_ID, API_SEND_EVENT, CMD_ID, GROUP_ID, KEEP_EVENT, PANEL_IDS, SL_CMD_ID, SL_DONE_EVENT, SL_GROUP_ID,
    SL_RESET_EVENT, SL_SAVE_EVENT, SL_SHOW_EVENT, TH_CMD_ID, TH_GROUP_ID, TH_KEEP_EVENT, WORKSPACE_ID,
    _app, _clear, _handlers, _ui)
# La API sin diálogo, también aquí: así se llamaba antes (m = este módulo) y lo explican los README
from overhang.ui.api import (  # noqa: E402
    analyze, clear_marks, describe, edges_where, faces_where, hide, mark, marks, reset, send, send_status, set_body,
    show, unmark)
# Para depurar desde execute_code: los mismos diccionarios que usan los comandos
from overhang.ui.common import _meshes  # noqa: E402
from overhang.ui.overhang_cmd import _state, _keep  # noqa: E402
from overhang.ui.thickness_cmd import _th_state, _th_meshes, _gap_cache, _th_keep  # noqa: E402
from overhang.ui.slicer_cmd import _sl_state  # noqa: E402

__all__ = ['run', 'stop', 'analyze', 'clear_marks', 'describe', 'edges_where', 'faces_where', 'hide', 'mark', 'marks',
           'reset', 'send', 'send_status', 'set_body', 'show', 'unmark', '_meshes', '_state', '_keep', '_th_state',
           '_th_meshes', '_gap_cache', '_th_keep', '_sl_state']

# CustomEvents del add-in y quién los atiende
EVENTS = ((KEEP_EVENT, OV._KeepHandler), (TH_KEEP_EVENT, TH._ThKeepHandler), (SL_DONE_EVENT, SL._SlDoneHandler),
          (SL_SHOW_EVENT, SL._SlShowHandler), (SL_RESET_EVENT, SL._SlResetHandler),
          (SL_SAVE_EVENT, SL._SlSaveHandler), (API_SEND_EVENT, API._ApiSendHandler))
# Capas de gráficos personalizados que se quitan al parar el add-in
GROUPS = (GROUP_ID, TH_GROUP_ID, SL_GROUP_ID, API_GROUP_ID)


def _commands():
    """(id, nombre, descripción, carpeta de iconos, handler de commandCreated) de cada botón. Es una función porque los
    textos dependen del idioma, que se fija al arrancar."""
    return [
        (CMD_ID, tr('Voladizos FDM'),
         tr('Pinta como un laminador lo que necesitará soporte: en rojo lo que mira hacia abajo con menos del '
            'ángulo límite desde la horizontal, en azul los puentes y en verde lo que apoya en la cama. '
            'No modifica el diseño.'),
         ('resources',), OV._CreatedHandler),
        (TH_CMD_ID, tr('Espesor y espacios'),
         tr('Mapa de color del espesor de las paredes o del espacio entre superficies, de rojo (estrecho) a '
            'azul (ancho), o solo lo que no llega al mínimo. No modifica el diseño.'),
         ('resources', 'thickness'), TH._ThCreatedHandler),
        (SL_CMD_ID, tr('Enviar al laminador'),
         tr('Exporta un cuerpo con su cama y con dónde forzar o prohibir la costura y los soportes, y lo abre en el '
            'laminador con slicer-paint.'),
         ('resources', 'slicer'), SL._SlCreatedHandler),
    ]


class _TerminatedHandler(adsk.core.ApplicationCommandEventHandler):
    """Al terminar cualquier comando que pueda haber cambiado el modelo: recalcula la capa de voladizos
    mantenida y quita la de espesor si sus cuerpos han cambiado (esa no se puede recalcular fuera del diálogo)."""
    def notify(self, args):
        try:
            if (args.commandId in (CMD_ID, TH_CMD_ID, SL_CMD_ID, 'SelectCommand')
                    or args.terminationReason != adsk.core.CommandTerminationReason.CompletedTerminationReason):
                return
            design = _keep.get('design')
            if design and design.isValid and _app.activeProduct == design:
                _app.fireCustomEvent(KEEP_EVENT)
            if _th_keep:
                _app.fireCustomEvent(TH_KEEP_EVENT)
        except Exception:
            pass


def _language():
    """'es' si Fusion está en castellano; si no, 'en'."""
    try:
        spanish = _app.preferences.generalPreferences.userLanguage == adsk.core.UserLanguages.SpanishLanguage
    except Exception:
        spanish = False
    return 'es' if spanish else 'en'


def _panel(pid):
    ws = _ui.workspaces.itemById(WORKSPACE_ID)
    return ws.toolbarPanels.itemById(pid) if ws else None


def run(context):
    try:
        set_language(_language())
        defs = []
        for cid, name, tooltip, icons, created in _commands():
            cmd_def = _ui.commandDefinitions.itemById(cid)
            if cmd_def:
                cmd_def.deleteMe()
            cmd_def = _ui.commandDefinitions.addButtonDefinition(cid, name, tooltip, os.path.join(HERE, *icons))
            h = created()
            cmd_def.commandCreated.add(h)
            _handlers.append(h)
            defs.append(cmd_def)
        for ev_id, handler in EVENTS:
            _app.unregisterCustomEvent(ev_id)   # por si quedó de una carga anterior
            h = handler()
            _app.registerCustomEvent(ev_id).add(h)
            _handlers.append(h)
        h = _TerminatedHandler()
        _ui.commandTerminated.add(h)
        _handlers.append(h)
        for pid in PANEL_IDS:
            panel = _panel(pid)
            for cmd_def in defs:
                if panel and not panel.controls.itemById(cmd_def.id):
                    panel.controls.addCommand(cmd_def)
    except Exception:
        _ui.messageBox(tr('Voladizos FDM: error al arrancar') + '\n' + traceback.format_exc())


def stop(context):
    try:
        OV._drop_keep()
        TH._th_drop_keep()
        for group_id in GROUPS:
            _clear(group_id)
        for h in _handlers:
            if isinstance(h, _TerminatedHandler):
                _ui.commandTerminated.remove(h)
        for ev_id, _ in EVENTS:
            _app.unregisterCustomEvent(ev_id)
        ids = [c[0] for c in _commands()]
        for pid in PANEL_IDS:
            panel = _panel(pid)
            for cid in ids:
                ctrl = panel.controls.itemById(cid) if panel else None
                if ctrl:
                    ctrl.deleteMe()
        for cid in ids:
            cmd_def = _ui.commandDefinitions.itemById(cid)
            if cmd_def:
                cmd_def.deleteMe()
        _handlers.clear()
    except Exception:
        _ui.messageBox(tr('Voladizos FDM: error al parar') + '\n' + traceback.format_exc())
