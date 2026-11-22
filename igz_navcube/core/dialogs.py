"""NavCube settings dialog (live preview, Cancel restores the previous values)."""
import importlib.util
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QSlider, QSpinBox,
                               QWidget)

try:
    from .core import CORNERS, OPACITY_RANGE, SIZE_RANGE, NavCubeSettings, tr
except ImportError:
    _here = os.path.dirname(os.path.abspath(__file__))
    _alias = "_igz_navcube_core"
    if _alias not in sys.modules:
        _spec = importlib.util.spec_from_file_location(_alias, os.path.join(_here, "core.py"))
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_alias] = _mod
        _spec.loader.exec_module(_mod)
    else:
        _mod = sys.modules[_alias]
    CORNERS = _mod.CORNERS
    OPACITY_RANGE = _mod.OPACITY_RANGE
    SIZE_RANGE = _mod.SIZE_RANGE
    NavCubeSettings = _mod.NavCubeSettings
    tr = _mod.tr
    
    
def _slider_row(lo, hi, value, suffix):
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    slider = QSlider(Qt.Horizontal)
    slider.setRange(lo, hi)
    slider.setValue(value)
    spin = QSpinBox()
    spin.setRange(lo, hi)
    spin.setValue(value)
    spin.setSuffix(suffix)
    slider.valueChanged.connect(spin.setValue)
    spin.valueChanged.connect(slider.setValue)
    lay.addWidget(slider, 1)
    lay.addWidget(spin)
    return box, spin


class SettingsDialog(QDialog):
    def __init__(self, settings, on_change, parent=None):
        super().__init__(parent)
        self._s = settings
        self._original = settings.copy()
        self._on_change = on_change
        self.setWindowTitle(tr("navcube.settings.title"))
        self.setMinimumWidth(380)

        form = QFormLayout(self)

        row, self._opacity = _slider_row(*OPACITY_RANGE, settings.opacity, " %")
        form.addRow(tr("navcube.settings.opacity"), row)
        row, self._size = _slider_row(*SIZE_RANGE, settings.size, " px")
        form.addRow(tr("navcube.settings.size"), row)

        self._corner = QComboBox()
        for c in CORNERS:
            self._corner.addItem(tr(f"navcube.corner.{c}"), c)
        self._corner.setCurrentIndex(CORNERS.index(settings.corner))
        form.addRow(tr("navcube.settings.corner"), self._corner)

        # Criando os Checkboxes
        self._hover = QCheckBox(tr("navcube.settings.hover_opaque"))
        self._hover.setChecked(settings.hover_opaque)
        
        self._animate = QCheckBox(tr("navcube.settings.animate"))
        self._animate.setChecked(settings.animate)
        
        self._arrows = QCheckBox(tr("navcube.settings.show_arrows"))
        self._arrows.setChecked(settings.show_arrows)
        
        self._compass = QCheckBox(tr("navcube.settings.show_compass"))
        self._compass.setChecked(getattr(settings, "show_compass", True))
        
        # CORREÇÃO: Adicionando todos, incluindo o compass, ao formulário
        for cb in (self._hover, self._animate, self._arrows, self._compass):
            form.addRow(cb)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel
                                   | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._restore)
        form.addRow(buttons)

        # Conectando os sinais
        self._opacity.valueChanged.connect(self._apply)
        self._size.valueChanged.connect(self._apply)
        self._corner.currentIndexChanged.connect(self._apply)
        
        # CORREÇÃO: Loop único e correto
        for cb in (self._hover, self._animate, self._arrows, self._compass):
            cb.toggled.connect(self._apply)

    def _apply(self, *_):
        s = self._s
        s.opacity = self._opacity.value()
        s.size = self._size.value()
        s.corner = self._corner.currentData()
        s.hover_opaque = self._hover.isChecked()
        s.animate = self._animate.isChecked()
        s.show_arrows = self._arrows.isChecked()
        s.show_compass = self._compass.isChecked()  # CORREÇÃO: Lendo o compasso
        s.clamp()
        self._on_change(s)

    def _restore(self):
        d = NavCubeSettings()
        self._opacity.setValue(d.opacity)
        self._size.setValue(d.size)
        self._corner.setCurrentIndex(CORNERS.index(d.corner))
        self._hover.setChecked(d.hover_opaque)
        self._animate.setChecked(d.animate)
        self._arrows.setChecked(d.show_arrows)
        self._compass.setChecked(d.show_compass)  # CORREÇÃO: Resetando o compasso

    def accept(self):
        self._s.save()
        super().accept()

    def reject(self):
        self._s.update_from(self._original)
        self._on_change(self._s)
        super().reject()