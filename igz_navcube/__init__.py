"""igz_navcube - AutoCAD/Revit-style navigation cube overlay for IngeTrazo."""
# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
import os
import sys

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(_PLUGIN_DIR, "core")
_PARENT_DIR = os.path.dirname(_PLUGIN_DIR)

for _p in (_PARENT_DIR, _PLUGIN_DIR):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)


def _load_local_module(mod_name, file_path):
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {mod_name} from {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod


_main_mod = _load_local_module(
    "_igz_navcube_main",
    os.path.join(_CORE_DIR, "igz_navcube.py"),
)

NavCubePlugin = _main_mod.NavCubePlugin
register = _main_mod.register
unregister = _main_mod.unregister
start_when_ready = _main_mod.start_when_ready


def setup(app=None, host=None):
    """Entry point IngeTrazo calls once at load (``setup(app)``).

    The toolbar and the Extensions submenu need the main window, so if it is
    not on screen yet the plugin registers itself in the background instead
    of surfacing as a load error on a slow start.
    """
    try:
        return register(app=app, host=host)
    except RuntimeError:
        return start_when_ready(app=app, host=host)


# Common entry-point names, so whichever one a loader calls works.
init = activate = on_load = register_plugin = setup

__all__ = [
    "NavCubePlugin",
    "register",
    "unregister",
    "setup",
    "init",
    "activate",
    "on_load",
    "register_plugin",
    "start_when_ready",
]