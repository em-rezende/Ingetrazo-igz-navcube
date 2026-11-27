"""
igz_navcube.core.core - Translations (KEYS), persisted settings, and host adapter.

Version: 1.0.1
Author: Ezequiel Mendonça Rezende (ARK-Z Arquitetura Ltda)
License: GPL-3.0-or-later
"""
import json
import os
import re
import time
import traceback
from dataclasses import dataclass, fields

from PySide6.QtCore import QLocale, QSettings, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

try:                                    # Qt6: lives in its own module
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
except ImportError:                     # pragma: no cover
    QOpenGLWidget = None

_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_I18N_DIR = os.path.join(_PACKAGE_DIR, "i18n")
DEFAULT_LOCALE = "en-US"
_strings = {}


# ------------------------------------------------------------------ i18n
def _read_json(locale):
    try:
        with open(os.path.join(_I18N_DIR, f"{locale}.json"), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _host_language() -> str:
    """Retorna o idioma atual do IngeTrazo (código tipo 'en-US', 'pt-BR')."""
    try:
        from core.i18n import current_language
        lang = current_language()
        if lang:
            return str(lang).replace("_", "-")
    except Exception:
        pass
    return QLocale().name().replace("_", "-")


def load_language(locale=None):
    """Load en-US (base keys) and overlay the requested locale, if a file exists."""
    global _strings
    data = _read_json(DEFAULT_LOCALE)
    locale = locale or _host_language()
    if locale != DEFAULT_LOCALE:
        data.update(_read_json(locale))
    _strings = data


def tr(key, **kwargs):
    """Translate a KEY. Falls back to the key itself so missing strings are visible."""
    if not _strings:
        load_language()
    text = _strings.get(key, key)
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError):
        return text


# -------------------------------------------------------------- settings
CORNERS = ("top_right", "top_left", "bottom_right", "bottom_left")
OPACITY_RANGE = (10, 100)
SIZE_RANGE = (80, 300)


@dataclass
class NavCubeSettings:
    enabled: bool = False
    opacity: int = 60            # idle opacity, in percent
    size: int = 120              # cube edge area, in pixels
    corner: str = "top_right"
    hover_opaque: bool = True    # become 100% opaque while the mouse is over it
    animate: bool = True
    show_arrows: bool = True
    show_compass: bool = True

    _ORG = "IngeTrazo"
    _APP = "igz_navcube"

    @classmethod
    def load(cls):
        qs = QSettings(cls._ORG, cls._APP)
        s = cls()
        for f in fields(cls):
            default = getattr(s, f.name)
            value = qs.value(f.name, default, type=type(default))
            setattr(s, f.name, value)
        s.clamp()
        return s

    def save(self):
        qs = QSettings(self._ORG, self._APP)
        for f in fields(self):
            qs.setValue(f.name, getattr(self, f.name))

    def clamp(self):
        self.opacity = max(OPACITY_RANGE[0], min(OPACITY_RANGE[1], int(self.opacity)))
        self.size = max(SIZE_RANGE[0], min(SIZE_RANGE[1], int(self.size)))
        if self.corner not in CORNERS:
            self.corner = "top_right"

    def update_from(self, other):
        for f in fields(self):
            setattr(self, f.name, getattr(other, f.name))

    def copy(self):
        c = NavCubeSettings()
        c.update_from(self)
        return c


# ----------------------------------------------------------- host adapter
class Host:
    """Everything the plugin needs from IngeTrazo. Implement these five methods.

    Camera vectors are world-space tuples (x, y, z) in a Z-up system:
      toward = direction from the target (orbit center) to the eye
      up     = camera up vector
    """

    def main_window(self):
        raise NotImplementedError

    def viewport_widget(self):
        """QWidget that displays the 3D scene; the overlay is parented to it."""
        raise NotImplementedError

    def get_camera(self):
        """Return (toward, up)."""
        raise NotImplementedError

    def set_camera(self, toward, up):
        """Orient the camera keeping the current target and distance."""
        raise NotImplementedError

    def add_toolbar(self, toolbar):
        raise NotImplementedError


_CAM_NAMES = ("camera", "cam", "_camera", "_cam", "active_camera")
_EYE_NAMES = ("eye", "position", "pos", "location")
_TGT_NAMES = ("target", "center", "look_at", "lookat", "focus", "pivot")
_UP_NAMES = ("up", "up_vector")


def _first_attr(obj, names):
    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            if callable(v):
                try:
                    v = v()
                except Exception:
                    continue
            return n, v
    return None, None


def _to_tuple(v):
    x = getattr(v, "x", None)
    if callable(x):                              # QVector3D
        return (float(v.x()), float(v.y()), float(v.z()))
    if x is not None:                            # simple object with .x .y .z
        return (float(v.x), float(v.y), float(v.z))
    return tuple(float(c) for c in v)[:3]        # tuple / list / numpy array


def _like(old, tup):
    """Build a value of the same kind as `old` from a 3-tuple."""
    try:
        if callable(getattr(old, "x", None)) or hasattr(old, "x"):
            return type(old)(*tup)
        if isinstance(old, list):
            return list(tup)
        if type(old).__module__.startswith("numpy"):
            import numpy as np
            return np.array(tup, dtype=old.dtype)
    except Exception:
        pass
    return tuple(tup)


try:
    from shiboken6 import isValid as _valid
except ImportError:                     # pragma: no cover
    _valid = lambda obj: True           # noqa: E731


def _area(w):
    return w.width() * w.height()


class IngeTrazoHost(Host):
    """Adapter for the real application (best-effort discovery).

    Window, viewport and camera are discovered by name. The canonical camera
    is ``vp.camera`` (a ``core.camera.OrbitCamera``) with ``eye``, ``target``
    and ``up`` attributes, updated via ``cam.place(...)`` followed by
    ``vp.update()``.
    """

    Y_UP = False

    def __init__(self, app=None):
        self.app = app
        self._diagnosed = False
        self._vp_cache = (None, 0.0)

    # -- window / viewport / toolbar
    def main_window(self):
        for n in ("main_window", "mainwindow", "window", "win"):
            w = getattr(self.app, n, None)
            w = w() if callable(w) else w
            if isinstance(w, QWidget) and w.isVisible():
                return w
        wins = [w for w in QApplication.topLevelWidgets()
                if isinstance(w, QMainWindow) and w.isVisible()]
        if not wins:                       # custom (non-QMainWindow) top-level window
            wins = [w for w in QApplication.topLevelWidgets()
                    if w.isVisible() and not (w.windowFlags() & Qt.Tool)]
        if not wins:
            return None
        active = QApplication.activeWindow()
        return active if active in wins else max(wins, key=_area)

    def viewport_widget(self):
        """The *visible* 3D viewport (changes when the user switches tabs)."""
        w, stamp = self._vp_cache
        now = time.monotonic()
        if w is not None and _valid(w) and w.isVisible() and now - stamp < 0.5:
            return w
        w = self._find_viewport()
        self._vp_cache = (w, now)
        return w

    def _find_viewport(self):
        for n in ("viewport", "view", "gl_widget", "canvas"):
            w = getattr(self.app, n, None)
            w = w() if callable(w) else w
            if isinstance(w, QWidget) and w.isVisible():
                return w
        win = self.main_window()
        if win is None:
            return None
        pat = re.compile(r"viewport|glwidget|canvas|scene|view3d|opengl", re.I)
        found = [w for w in win.findChildren(QWidget)
                 if w.isVisible()
                 and ((QOpenGLWidget is not None and isinstance(w, QOpenGLWidget))
                      or pat.search(type(w).__name__))]
        if found:
            return max(found, key=_area)
        central = win.centralWidget() if isinstance(win, QMainWindow) else None
        return central or win

    def add_toolbar(self, toolbar):
        adder = getattr(self.app, "add_toolbar", None)
        if callable(adder):
            try:
                adder(toolbar)
                toolbar.show()
                return
            except Exception:
                pass
        win = self.main_window()
        if isinstance(win, QMainWindow):
            win.addToolBar(Qt.TopToolBarArea, toolbar)
        else:                              # no QMainWindow: float it as a tool window
            toolbar.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        toolbar.show()

    # -- camera
    def _find_orbit_camera(self):
        """Return ``(vp, camera)`` where ``camera`` is the IngeTrazo OrbitCamera.

        The canonical source of truth in IngeTrazo is ``vp.camera`` with
        ``.eye`` / ``.target`` / ``.up``. Falls back to ``(vp, None)`` when
        the attribute is missing or malformed.
        """
        vp = self.viewport_widget()
        if vp is None:
            return None, None
        cam = getattr(vp, "camera", None)
        if cam is None:
            return vp, None
        if not all(hasattr(cam, a) for a in ("eye", "target", "up")):
            return vp, None
        return vp, cam

    def _owners(self):
        vp = self.viewport_widget()
        owners = [self.app, getattr(self.app, "viewport", None), vp, self.main_window()]
        return [o for o in owners if o is not None]

    def _camera(self):
        # 1) caminho canônico: vp.camera (OrbitCamera do IngeTrazo)
        _vp, cam = self._find_orbit_camera()
        if cam is not None:
            return cam, ("eye", cam.eye), ("target", cam.target), ("up", cam.up)

        # 2) fallback antigo (não usado quando vp.camera existe)
        for owner in self._owners():
            for cand in (owner, *[_first_attr(owner, (n,))[1] for n in _CAM_NAMES]):
                if cand is None:
                    continue
                e_n, e = _first_attr(cand, _EYE_NAMES)
                t_n, t = _first_attr(cand, _TGT_NAMES)
                u_n, u = _first_attr(cand, _UP_NAMES)
                if e is not None and t is not None and u is not None:
                    return cand, (e_n, e), (t_n, t), (u_n, u)
        return None

    def _diagnose(self):
        if self._diagnosed:
            return
        self._diagnosed = True
        pat = re.compile(r"cam|eye|view|target|orbit|zoom|pan|look", re.I)
        print("[igz_navcube] camera not found. Camera-like attributes seen:")
        for o in self._owners():
            names = [n for n in dir(o) if pat.search(n) and not n.startswith("__")]
            print(f"  {type(o).__name__}: {names}")

    def _zup(self, v):
        x, y, z = _to_tuple(v)
        return (x, -z, y) if self.Y_UP else (x, y, z)

    def _native(self, v):
        x, y, z = v
        return (x, z, -y) if self.Y_UP else (x, y, z)

    def _invalidate_viewport_caches(self, vp):
        """Request a viewport redraw after camera updates."""
        if vp is not None:
            try:
                vp.update()
            except Exception:
                traceback.print_exc()

    def get_camera(self):
        _vp, cam = self._find_orbit_camera()
        if cam is None:
            self._diagnose()
            raise NotImplementedError(tr("navcube.error.camera_unavailable"))

        eye_attr = cam.eye
        eye = eye_attr() if callable(eye_attr) else eye_attr

        e = self._zup(_to_tuple(eye))
        t = self._zup(_to_tuple(cam.target))
        u = self._zup(_to_tuple(cam.up))
        return (e[0] - t[0], e[1] - t[1], e[2] - t[2]), u

    def set_camera(self, toward, up):
        vp, cam = self._find_orbit_camera()
        if cam is None:
            self._diagnose()
            raise NotImplementedError(tr("navcube.error.camera_unavailable"))

        # lê eye atual (pode ser método) e target
        eye_attr = cam.eye
        eye = eye_attr() if callable(eye_attr) else eye_attr
        e = self._zup(_to_tuple(eye))
        t = self._zup(_to_tuple(cam.target))
        dist = sum((a - b) ** 2 for a, b in zip(e, t)) ** 0.5 or 1.0
        n = sum(c * c for c in toward) ** 0.5 or 1.0
        new_eye = tuple(t[i] + dist * toward[i] / n for i in range(3))

        # Converte para o sistema nativo do IngeTrazo (QVector3D, Y-up se for o caso)
        native_eye = self._native(new_eye)
        native_target = self._native(t)

        eye_vec = _like(eye, native_eye)
        tgt_vec = _like(cam.target, native_target)

        # Caminho canônico: place() atualiza eye/target/up/view_matrix
        placed = False
        try:
            if hasattr(cam, "place"):
                cam.place(eye_vec, tgt_vec)
                placed = True
        except Exception:
            traceback.print_exc()

        # Fallback: escreve eye/up manualmente apenas se place() não existir/falhar
        if not placed:
            setattr(cam, "eye", eye_vec)
            setattr(cam, "up", _like(cam.up, self._native(up)))

        if vp is not None:
            try:
                vp.update()
            except Exception:
                traceback.print_exc()