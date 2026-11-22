try:
    from . import navcube_math as nm
    from .core import Host
    from .igz_navcube import NavCubePlugin
except ImportError:
    import importlib.util
    import os
    import sys

    _here = os.path.dirname(os.path.abspath(__file__))

    def _get_mod(alias, filename):
        if alias not in sys.modules:
            spec = importlib.util.spec_from_file_location(alias, os.path.join(_here, filename))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[alias] = mod
            spec.loader.exec_module(mod)
        return sys.modules[alias]

    nm = _get_mod("_igz_navcube_math", "navcube_math.py")
    Host = _get_mod("_igz_navcube_core", "core.py").Host
    NavCubePlugin = _get_mod("_igz_navcube_main", "igz_navcube.py").NavCubePlugin
    

class DemoViewport(QWidget):
    """Tiny fake 3D viewport: axes + a box, drawn with the NavCube projection."""

    def __init__(self):
        super().__init__()
        self.frame = nm.frame_from_view((1, -1, 1), (0, 0, 1))
        self.setMinimumSize(640, 480)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(38, 42, 50))
        cx, cy, sc = self.width() / 2, self.height() / 2, 70
        pr = lambda v: QPointF(*nm.project(v, self.frame, cx, cy, sc))
        for axis, col in (((3, 0, 0), "#e55"), ((0, 3, 0), "#5c5"), ((0, 0, 3), "#58f")):
            p.setPen(QPen(QColor(col), 2))
            p.drawLine(pr((0, 0, 0)), pr(axis))
        p.setPen(QPen(QColor(200, 200, 210), 1))
        box = [(x, y, z) for x in (0.5, 2) for y in (0.5, 1.5) for z in (0, 1)]
        for a in box:
            for b in box:
                if sum(abs(a[i] - b[i]) > 0 for i in range(3)) == 1 and a < b:
                    p.drawLine(pr(a), pr(b))


class DemoHost(Host):
    def __init__(self, win, viewport):
        self.win, self.vp = win, viewport

    def main_window(self):
        return self.win

    def viewport_widget(self):
        return self.vp

    def get_camera(self):
        return self.vp.frame[2], self.vp.frame[1]

    def set_camera(self, toward, up):
        self.vp.frame = nm.frame_from_view(toward, up)
        self.vp.update()

    def add_toolbar(self, toolbar):
        self.win.addToolBar(toolbar)


def main():
    app = QApplication(sys.argv)
    win = QMainWindow()
    vp = DemoViewport()
    win.setCentralWidget(vp)
    plugin = NavCubePlugin(DemoHost(win, vp))
    plugin.setup()
    plugin.act_toggle.setChecked(True)
    win.resize(900, 640)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
