"""igz_navcube - setup, toolbar and commands."""
import importlib.util
import os
import sys
import traceback

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import (QAction, QColor, QIcon, QPainter, QPainterPath,
                           QPalette, QPixmap, QPolygonF, QTransform)
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QToolBar

_HERE = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_HERE)
_ICON_DIR = os.path.join(_PACKAGE_DIR, "icons")


def _load_sibling(alias, filename):
    path = os.path.join(_HERE, filename)
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {filename} from {_HERE}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(alias, None)
        raise
    return mod

try:
    from .core import (IngeTrazoHost, NavCubeSettings, _host_language,
                       load_language, tr)
    from .dialogs import SettingsDialog
    from .overlay import NavCubeOverlay
except ImportError:
    _core_mod = _load_sibling("_igz_navcube_core", "core.py")
    _dialogs_mod = _load_sibling("_igz_navcube_dialogs", "dialogs.py")
    _overlay_mod = _load_sibling("_igz_navcube_overlay", "overlay.py")

    IngeTrazoHost = _core_mod.IngeTrazoHost
    NavCubeSettings = _core_mod.NavCubeSettings
    _host_language = _core_mod._host_language
    load_language = _core_mod.load_language
    tr = _core_mod.tr
    SettingsDialog = _dialogs_mod.SettingsDialog
    NavCubeOverlay = _overlay_mod.NavCubeOverlay

_plugin = None


# ----------------------------------------------------------------- icons
def _svg_icon(name, fallback):
    """Load icons/<name>; fall back to the painted icon if the SVG can't render."""
    path = os.path.join(_ICON_DIR, name)
    if os.path.isfile(path):
        icon = QIcon(path)
        if not icon.isNull() and not icon.pixmap(32, 32).isNull():
            return icon
    return fallback()


def _canvas():
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    return pm, p


def icon_cube():
    pm, p = _canvas()
    P = QPointF
    faces = (
        ([P(16, 3), P(28, 9.5), P(16, 16), P(4, 9.5)], QColor(214, 222, 235)),
        ([P(4, 9.5), P(16, 16), P(16, 29), P(4, 22.5)], QColor(150, 165, 190)),
        ([P(28, 9.5), P(16, 16), P(16, 29), P(28, 22.5)], QColor(110, 128, 160)),
    )
    p.setPen(QColor(60, 70, 90))
    for pts, col in faces:
        p.setBrush(col)
        p.drawPolygon(QPolygonF(pts))
    p.end()
    return QIcon(pm)


def icon_gear():
    pm, p = _canvas()
    p.translate(16, 16)
    path = QPainterPath()
    path.addEllipse(QPointF(0, 0), 9.5, 9.5)
    for i in range(8):
        tooth = QPainterPath()
        tooth.addRect(-2.5, -14, 5, 6)
        path = path.united(QTransform().rotate(i * 45).map(tooth))
    hole = QPainterPath()
    hole.addEllipse(QPointF(0, 0), 4.5, 4.5)
    path = path.subtracted(hole)
    p.setPen(Qt.NoPen)
    p.setBrush(QApplication.palette().color(QPalette.ButtonText))
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def _norm_menu_title(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum())


# ---------------------------------------------------------------- plugin
class NavCubePlugin:
    def __init__(self, host):
        load_language()
        self.host = host
        self.settings = NavCubeSettings.load()
        self.overlay = None
        self.toolbar = None
        self._extensions_menu = None
        self._created_extensions_menu = False
        self._navcube_menu = None
        self._menu_toggle_action = None
        self._menu_settings_action = None

    def _find_or_create_extensions_menu(self, win):
        if not isinstance(win, QMainWindow):
            return None, False
        menubar = win.menuBar()
        if menubar is None:
            return None, False

        target_names = {"extensions", "extensoes", "extensoes", "plugins"}
        for action in menubar.actions():
            menu = action.menu()
            if menu is None:
                continue
            title_clean = _norm_menu_title(menu.title())
            obj_clean = _norm_menu_title(menu.objectName() or "")
            if title_clean in target_names or obj_clean in target_names:
                return menu, False

        ext_menu = QMenu("Extensions", menubar)
        ext_menu.setObjectName("igz_extensions_menu")
        menubar.addMenu(ext_menu)
        return ext_menu, True

    def _setup_menu(self):
        win = self.host.main_window()
        ext_menu, created = self._find_or_create_extensions_menu(win)
        if ext_menu is None:
            return

        self._extensions_menu = ext_menu
        self._created_extensions_menu = created

        sub = QMenu("NavCube", ext_menu)
        sub.setObjectName("igz_navcube_menu")
        sub.setIcon(_svg_icon("navcube.svg", icon_cube))

        act_toggle = QAction(
            _svg_icon("navcube.svg", icon_cube),
            tr("navcube.action.toggle"),
            sub,
        )
        act_toggle.setToolTip(tr("navcube.action.toggle.tip"))
        act_toggle.setCheckable(True)
        act_toggle.setChecked(self.settings.enabled)
        act_toggle.toggled.connect(self._on_menu_toggle)

        act_settings = QAction(
            _svg_icon("navcube_settings.svg", icon_gear),
            tr("navcube.action.settings"),
            sub,
        )
        act_settings.setToolTip(tr("navcube.action.settings.tip"))
        act_settings.triggered.connect(self.open_settings)

        sub.addAction(act_toggle)
        sub.addAction(act_settings)
        ext_menu.addMenu(sub)

        self._navcube_menu = sub
        self._menu_toggle_action = act_toggle
        self._menu_settings_action = act_settings

    def _on_menu_toggle(self, checked):
        if self.act_toggle.isChecked() != checked:
            self.act_toggle.setChecked(checked)
        else:
            self.set_enabled(checked)

    def _sync_toggle_state(self, enabled):
        enabled = bool(enabled)
        if self.act_toggle is not None and self.act_toggle.isChecked() != enabled:
            self.act_toggle.blockSignals(True)
            self.act_toggle.setChecked(enabled)
            self.act_toggle.blockSignals(False)
        if self._menu_toggle_action is not None and self._menu_toggle_action.isChecked() != enabled:
            self._menu_toggle_action.blockSignals(True)
            self._menu_toggle_action.setChecked(enabled)
            self._menu_toggle_action.blockSignals(False)

    def setup(self):
        if self.host.main_window() is None:
            raise RuntimeError("igz_navcube: main window not ready")
        load_language()
        self._current_lang = _host_language()

        self.overlay = NavCubeOverlay(self.host, self.settings)

        tb = QToolBar(tr("navcube.toolbar.title"))
        tb.setObjectName("igz_navcube_toolbar")

        self.act_toggle = QAction(_svg_icon("navcube.svg", icon_cube), tr("navcube.action.toggle"), tb)
        self.act_toggle.setToolTip(tr("navcube.action.toggle.tip"))
        self.act_toggle.setCheckable(True)
        self.act_toggle.toggled.connect(self._on_toolbar_toggle)

        self.act_settings = QAction(_svg_icon("navcube_settings.svg", icon_gear), tr("navcube.action.settings"), tb)
        self.act_settings.setToolTip(tr("navcube.action.settings.tip"))
        self.act_settings.triggered.connect(self.open_settings)

        tb.addAction(self.act_toggle)
        tb.addAction(self.act_settings)
        self.toolbar = tb
        self.host.add_toolbar(tb)

        self._setup_menu()

        self._sync_toggle_state(self.settings.enabled)
        self.overlay.set_active(self.settings.enabled)

        # Monitora a mudança de idioma do IngeTrazo
        self._lang_timer = QTimer()
        self._lang_timer.setInterval(2000)
        self._lang_timer.timeout.connect(self._check_language)
        self._lang_timer.start()

    def _on_toolbar_toggle(self, checked):
        if self._menu_toggle_action is not None and self._menu_toggle_action.isChecked() != checked:
            self._menu_toggle_action.blockSignals(True)
            self._menu_toggle_action.setChecked(checked)
            self._menu_toggle_action.blockSignals(False)
        self.set_enabled(checked)

    def _check_language(self):
        lang = _host_language()
        if lang == self._current_lang:
            return
        self._current_lang = lang
        load_language()

        # Atualiza os textos da toolbar
        if self.toolbar is not None:
            self.toolbar.setWindowTitle(tr("navcube.toolbar.title"))
        if self.act_toggle is not None:
            self.act_toggle.setText(tr("navcube.action.toggle"))
            self.act_toggle.setToolTip(tr("navcube.action.toggle.tip"))
        if self.act_settings is not None:
            self.act_settings.setText(tr("navcube.action.settings"))
            self.act_settings.setToolTip(tr("navcube.action.settings.tip"))

        # Atualiza os textos do menu
        if self._menu_toggle_action is not None:
            self._menu_toggle_action.setText(tr("navcube.action.toggle"))
            self._menu_toggle_action.setToolTip(tr("navcube.action.toggle.tip"))
        if self._menu_settings_action is not None:
            self._menu_settings_action.setText(tr("navcube.action.settings"))
            self._menu_settings_action.setToolTip(tr("navcube.action.settings.tip"))

        # Redesenha o overlay (labels TOPO, FRENTE, etc.)
        if self.overlay is not None:
            self.overlay.update()

    def set_enabled(self, on):
        self.settings.enabled = bool(on)
        self.settings.save()
        self._sync_toggle_state(self.settings.enabled)
        if self.overlay is not None:
            self.overlay.set_active(self.settings.enabled)

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self._on_settings_changed,
                             parent=self.host.main_window())
        dlg.exec()

    def _on_settings_changed(self, _settings):
        self.overlay.apply_settings()

    def teardown(self):
        if getattr(self, "_lang_timer", None) is not None:
            self._lang_timer.stop()
        if self._navcube_menu is not None:
            if self._extensions_menu is not None:
                self._extensions_menu.removeAction(self._navcube_menu.menuAction())
            self._navcube_menu.deleteLater()
            self._navcube_menu = None
        if self._created_extensions_menu and self._extensions_menu is not None:
            win = self.host.main_window()
            if isinstance(win, QMainWindow) and win.menuBar() is not None:
                win.menuBar().removeAction(self._extensions_menu.menuAction())
            self._extensions_menu.deleteLater()
        self._extensions_menu = None
        self._created_extensions_menu = False
        self._menu_toggle_action = None
        self._menu_settings_action = None

        if self.overlay is not None:
            self.overlay.set_active(False)
            self.overlay.deleteLater()
        if self.toolbar is not None:
            self.toolbar.deleteLater()
        self.overlay = self.toolbar = None


def register(app=None, host=None):
    """Plugin entry point. Pass a custom Host to override the default adapter."""
    global _plugin
    if _plugin is not None:
        return _plugin
    plugin = NavCubePlugin(host or IngeTrazoHost(app))
    try:
        plugin.setup()
    except Exception:
        plugin.teardown()
        raise
    _plugin = plugin
    return _plugin


def unregister(app=None):
    global _plugin
    if _plugin is not None:
        _plugin.teardown()
        _plugin = None


# Common entry-point names, so whichever one the IngeTrazo loader calls works.
setup = init = activate = on_load = register_plugin = register


def start_when_ready(tries=0, app=None, host=None):
    """Register the plugin once the host window exists (never raises).

    Used by ``setup(app)`` when the main window is not on screen yet and by
    the self-start timer below. Retries every 500 ms for ~20 s, then reports
    the traceback instead of leaving a half-registered plugin behind.
    """
    if _plugin is not None:
        return _plugin
    try:
        return register(app=app, host=host)
    except Exception:
        if tries < 40:
            QTimer.singleShot(
                500, lambda: start_when_ready(tries + 1, app=app, host=host))
        else:
            traceback.print_exc()
    return None


def _autostart():
    """Self-start after import, retrying until the main window is visible."""
    start_when_ready()


if QApplication.instance() is not None and not os.environ.get("IGZ_NAVCUBE_NO_AUTOSTART"):
    QTimer.singleShot(0, _autostart)