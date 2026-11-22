"""Viewport overlay widget that draws and drives the navigation cube."""
import math
import time

from PySide6.QtCore import (QEasingCurve, QEvent, QPoint, QPointF, QRectF, Qt,
                            QTimer, QVariantAnimation)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainter,
                           QPainterPath, QPen, QPolygonF, QTransform,
                           QWheelEvent)
from PySide6.QtWidgets import QApplication, QWidget

try:
    from shiboken6 import isValid as _valid
except ImportError:                     # pragma: no cover
    _valid = lambda obj: True           # noqa: E731

try:
    from . import navcube_math as nm
    from .core import tr
except ImportError:
    import importlib.util
    import os
    import sys

    _here = os.path.dirname(os.path.abspath(__file__))

    def _get_mod(alias, filename):
        if alias not in sys.modules:
            spec = importlib.util.spec_from_file_location(alias, os.path.join(_here, filename))
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load {filename} from {_here}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[alias] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception:
                sys.modules.pop(alias, None)
                raise
        return sys.modules[alias]

    nm = _get_mod("_igz_navcube_math", "navcube_math.py")
    tr = _get_mod("_igz_navcube_core", "core.py").tr

PAD = 24                 # room around the cube for arrows and the home button
MARGIN = 12              # distance from the viewport border
DRAG_DEG_PER_PX = 0.6
DRAG_THRESHOLD_PX = 4

COL_FACE = QColor(236, 240, 245)  # Cor de preenchimento das faces principais
COL_EDGE = QColor(211, 217, 224)  # Cor de preenchimento das faixas das arestas
COL_LINE = QColor(110, 120, 135)  # Cor da linha de contorno (a "moldura" em si)
COL_TEXT = QColor(45, 52, 64)     # Cor do texto
COL_HOVER = QColor(70, 150, 235)
COL_ICON = QColor(105, 115, 130)

# Cores do Compasso
COL_COMPASS_RING = QColor(211, 217, 224, 90)
COL_COMPASS_TEXT = QColor(123, 126, 134, 220)

COMPASS_Z = -1.0
COMPASS_R_OUTER = 2.0
COMPASS_R_INNER = 1.6
COMPASS_R_LABEL = 1.8

# N (+Y) -> Back, S (-Y) -> Front, E (+X) -> Right, W (-X) -> Left
COMPASS_CARDINALS = (
    ("N", (0.0, COMPASS_R_LABEL), (0, 1, 0), "back"),
    ("S", (0.0, -COMPASS_R_LABEL), (0, -1, 0), "front"),
    ("E", (COMPASS_R_LABEL, 0.0), (1, 0, 0), "right"),
    ("W", (-COMPASS_R_LABEL, 0.0), (-1, 0, 0), "left"),
)

ARROW_STEPS = {"up": (0, 90), "down": (0, -90), "left": (-90, 0), "right": (90, 0)}


class NavCubeOverlay(QWidget):
    """The cube lives in its own frameless, translucent tool window that follows
    the visible viewport. It never paints inside the viewport (GL) widget, so it
    cannot leave artifacts there, and it survives tab / document switches."""

    def __init__(self, host, settings):
        owner = host.main_window()
        super().__init__(owner)
        self._host = host
        self._s = settings
        self._frame = nm.frame_for_direction((0, -1, 0))
        self._hover = None
        self._inside = False
        self._press = None
        self._busy = False                # animating or dragging: ignore polling
        self._target = None
        self._camera_ok = True
        self._active = False
        self._vp = None
        self._vp_checked = 0.0
        self._owner = owner

        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_X11DoNotAcceptFocus)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._anim.finished.connect(self._on_anim_done)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

        if owner is not None:
            owner.installEventFilter(self)
        self.apply_settings()

    # ------------------------------------------------------------ lifecycle
    def set_active(self, on):
        self._active = bool(on)
        if on:
            self._poll()
            self._sync()
            self._timer.start()
        else:
            self._timer.stop()
            self._anim.stop()
            self.hide()

    def apply_settings(self):
        side = self._s.size + 2 * PAD
        self.setFixedSize(side, side)
        self._update_mask()
        self._sync()
        self.update()

    def eventFilter(self, obj, event):
        if obj is self._owner and event.type() in (
                QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide,
                QEvent.WindowStateChange):
            self._sync()
        return False

    # -------------------------------------------- follow the visible viewport
    def _viewport(self):
        vp = self._vp
        stale = vp is None or not _valid(vp) or not vp.isVisible()
        now = time.monotonic()
        if stale or now - self._vp_checked > 1.0:      # re-resolve: tabs, new documents
            self._vp_checked = now
            cand = self._host.viewport_widget()
            self._vp = cand if (cand is not None and _valid(cand) and cand.isVisible()) else None
        return self._vp

    def _attach_to_viewport(self, vp):
        if vp is not None and self.parentWidget() is not vp:
            was_vis = self.isVisible()
            self.setParent(vp)
            self.setAttribute(Qt.WA_NoSystemBackground, True)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setMouseTracking(True)
            if was_vis:
                self.show()

    def _target_pos(self, vp):
        c = self._s.corner
        if self.parentWidget() is vp:
            x = MARGIN if c.endswith("left") else vp.width() - self.width() - MARGIN
            y = MARGIN if c.startswith("top") else vp.height() - self.height() - MARGIN
        else:
            origin = vp.mapToGlobal(QPoint(0, 0))
            x = origin.x() + (MARGIN if c.endswith("left") else vp.width() - self.width() - MARGIN)
            y = origin.y() + (MARGIN if c.startswith("top") else vp.height() - self.height() - MARGIN)
        return QPoint(int(x), int(y))

    def _sync(self):
        if not self._active:
            return
        win = self._host.main_window()
        vp = self._viewport()
        ok = (vp is not None and (win is None or not win.isMinimized())
              and vp.width() > self.width() + 2 * MARGIN
              and vp.height() > self.height() + 2 * MARGIN)
        if not ok:
            if self.isVisible():
                self.hide()
            return
        self._attach_to_viewport(vp)
        new_pos = self._target_pos(vp)
        if self.pos() != new_pos:
            self.move(new_pos)
        if not self.isVisible():
            self.show()
            self.raise_()

    def _tick(self):
        win = self._host.main_window()
        if win is None or win.isMinimized():
            if self.isVisible():
                self.hide()
            return
        vp = self._viewport()
        if vp is None:
            if self.isVisible():
                self.hide()
            return
        self._attach_to_viewport(vp)
        new_pos = self._target_pos(vp)
        if self.pos() != new_pos:
            self.move(new_pos)
        if not self.isVisible() and self._active:
            self.show()
            self.raise_()
        self._poll()
        
    # --------------------------------------------------------------- camera
    def _poll(self):
        if self._busy or not self._camera_ok:
            return
        try:
            toward, up = self._host.get_camera()
            frame = nm.frame_from_view(toward, up)
        except Exception as exc:
            self._camera_ok = False
            print(exc)
            return
        if frame != self._frame:
            self._set_frame(frame)

    def _set_frame(self, frame):
        self._frame = frame
        self._update_mask()
        self.update()

    def _apply_frame(self, frame):
        self._set_frame(frame)
        try:
            self._host.set_camera(frame[2], frame[1])
        except Exception as exc:
            self._anim.stop()
            print(exc)

    def _go_to(self, frame):
        self._anim.stop()
        self._target = frame
        if not self._s.animate:
            self._apply_frame(frame)
            return
        self._q0 = nm.frame_to_quat(self._frame)
        self._q1 = nm.frame_to_quat(frame)
        angle = nm.quat_angle(self._q0, self._q1)
        if angle < 1e-3:
            return
        self._busy = True

        # Oculta o overlay durante a animação para evitar tiles pretos
        self._was_visible_before_anim = self.isVisible()
        self.hide()

        self._anim.setDuration(int(160 + 220 * angle / math.pi))
        self._anim.start()

    def _on_anim(self, k):
        self._apply_frame(nm.quat_to_frame(nm.slerp(self._q0, self._q1, float(k))))

    def _on_anim_done(self):
        if self._target is not None:
            self._apply_frame(self._target)
        self._busy = False

        # Reexibe o overlay após a animação
        if getattr(self, "_was_visible_before_anim", False):
            self._was_visible_before_anim = False
            self._sync()

    def _update_mask(self):
        # Não usar setMask para evitar quadros pretos no OpenGL
        self.clearMask()

    # ------------------------------------------------------------- geometry
    def _geom(self):
        return self.width() / 2.0, self.height() / 2.0, self._s.size / 3.9

    def _home_rect(self):
        return QRectF(23, 3, 18, 18)

    def _arrow_polys(self):
        w, h, p = self.width(), self.height(), PAD / 2.0
        cx, cy = w / 2.0, h / 2.0
        P = QPointF
        return {
            "up": QPolygonF([P(cx - 8, p + 5), P(cx + 8, p + 5), P(cx, p - 5)]),
            "down": QPolygonF([P(cx - 8, h - p - 5), P(cx + 8, h - p - 5), P(cx, h - p + 5)]),
            "left": QPolygonF([P(p - 5, cy), P(p + 5, cy - 8), P(p + 5, cy + 8)]),
            "right": QPolygonF([P(w - p + 5, cy), P(w - p - 5, cy - 8), P(w - p - 5, cy + 8)]),
        }

    def _compass_ring_paths(self, cx, cy, sc):
        """Retorna (path_anel, poly_externo, poly_interno) no plano do compasso."""
        poly_outer = QPolygonF()
        poly_inner = QPolygonF()
        for i in range(72):
            ang = math.radians(i * 5)
            ca, sa = math.cos(ang), math.sin(ang)
            ox, oy = COMPASS_R_OUTER * ca, COMPASS_R_OUTER * sa
            ix, iy = COMPASS_R_INNER * ca, COMPASS_R_INNER * sa
            poly_outer.append(QPointF(*nm.project((ox, oy, COMPASS_Z), self._frame, cx, cy, sc)))
            poly_inner.append(QPointF(*nm.project((ix, iy, COMPASS_Z), self._frame, cx, cy, sc)))

        path_outer = QPainterPath()
        path_outer.addPolygon(poly_outer)
        path_outer.closeSubpath()

        path_inner = QPainterPath()
        path_inner.addPolygon(poly_inner)
        path_inner.closeSubpath()

        return path_outer.subtracted(path_inner), poly_outer, poly_inner

    def _hit(self, pos):
        if self._home_rect().contains(pos):
            return ("home",)
        if self._s.show_arrows:
            for name, poly in self._arrow_polys().items():
                if poly.boundingRect().adjusted(-4, -4, 4, 4).contains(pos):
                    return ("arrow", name)

        cx, cy, sc = self._geom()
        for cell in nm.visible_cells(self._frame, cx, cy, sc):
            poly = QPolygonF([QPointF(*q) for q in cell.quad])
            if poly.containsPoint(pos, Qt.OddEvenFill):
                return ("cell", cell.key)

        if getattr(self._s, "show_compass", True):
            # 1) Prioriza clique/hover nas letras N, S, E, W
            for letter, (wx, wy), direction, face_name in COMPASS_CARDINALS:
                px, py = nm.project((wx, wy, COMPASS_Z), self._frame, cx, cy, sc)
                if (QPointF(px, py) - pos).manhattanLength() < 15:
                    return ("compass_dir", direction, face_name, letter)

            # 2) Verifica o anel do compasso (arraste para orbitar em Z)
            _, poly_outer, poly_inner = self._compass_ring_paths(cx, cy, sc)
            if (poly_outer.containsPoint(pos, Qt.OddEvenFill)
                    and not poly_inner.containsPoint(pos, Qt.OddEvenFill)):
                return ("compass_ring",)

        return None

    def _tooltip_for(self, hit):
        if hit is None:
            return ""
        if hit[0] == "home":
            return tr("navcube.view.home")
        if hit[0] == "arrow":
            return tr(f"navcube.arrow.{hit[1]}")
        if hit[0] == "compass_ring":
            return tr("navcube.compass.orbit_z") if tr("navcube.compass.orbit_z") != "navcube.compass.orbit_z" else "Orbitar eixo Z"
        if hit[0] == "compass_dir":
            face_name = hit[2]
            label = tr(f"navcube.face.{face_name}")
            return label if label != f"navcube.face.{face_name}" else face_name.capitalize()
        return " / ".join(tr(f"navcube.face.{f}") for f in nm.key_faces(hit[1]))

    # --------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            e.ignore()
            return
        hit = self._hit(e.position())
        if hit is None:
            e.ignore()
            return
        self._press = {
            "hit": hit,
            "start": e.position(),
            "last": e.position(),
            "dragging": False,
        }
        e.accept()

    def mouseMoveEvent(self, e):
        pos = e.position()
        pr = self._press
        if pr is not None:
            can_drag = pr["hit"][0] in ("cell", "compass_ring")
            if (not pr["dragging"] and can_drag
                    and (pos - pr["start"]).manhattanLength() > DRAG_THRESHOLD_PX):
                pr["dragging"] = True
                self._anim.stop()
                self._busy = True
            if pr["dragging"]:
                d = pos - pr["last"]
                pr["last"] = pos
                if pr["hit"][0] == "compass_ring":
                    # Orbit exclusivo em torno do eixo Z (yaw apenas)
                    self._apply_frame(nm.orbit(self._frame,
                                               -d.x() * DRAG_DEG_PER_PX,
                                               0.0))
                else:
                    self._apply_frame(nm.orbit(self._frame,
                                               -d.x() * DRAG_DEG_PER_PX,
                                               d.y() * DRAG_DEG_PER_PX))
            e.accept()
            return
        hit = self._hit(pos)
        if hit != self._hover:
            self._hover = hit
            self.setToolTip(self._tooltip_for(hit))
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()
            e.accept()
            return
        e.ignore()

    def mouseReleaseEvent(self, e):
        pr, self._press = self._press, None
        if pr is None:
            e.ignore()
            return
        if pr["dragging"]:
            self._busy = False
        else:
            self._activate(pr["hit"])
        e.accept()

    def wheelEvent(self, e):
        vp = self._viewport()
        if vp is None:
            e.ignore()
            return
        g = e.globalPosition()
        ev = QWheelEvent(QPointF(vp.mapFromGlobal(g.toPoint())), g, e.pixelDelta(),
                         e.angleDelta(), e.buttons(), e.modifiers(), e.phase(),
                         e.inverted(), e.source())
        QApplication.sendEvent(vp, ev)
        e.accept()

    def enterEvent(self, e):
        self._inside = True
        self.update()

    def leaveEvent(self, e):
        self._inside = False
        self._hover = None
        self.update()

    def _activate(self, hit):
        if hit[0] == "home":
            self._go_to(nm.frame_for_direction(nm.HOME_DIRECTION))
        elif hit[0] == "arrow":
            yaw, pitch = ARROW_STEPS[hit[1]]
            self._go_to(nm.orbit(self._frame, yaw, pitch))
        elif hit[0] == "compass_dir":
            self._go_to(nm.frame_for_direction(hit[1]))
        elif hit[0] == "compass_ring":
            return
        else:
            self._go_to(nm.frame_for_direction(hit[1]))

    # --------------------------------------------------------------- paint
    def _opacity(self):
        if self._s.hover_opaque and (self._inside or self._press):
            return 1.0
        return self._s.opacity / 100.0

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        p.setOpacity(self._opacity())
        cx, cy, sc = self._geom()

        # Desenha o compasso de fundo, se ativado nas configurações
        if getattr(self._s, "show_compass", True):
            self._draw_compass(p, cx, cy, sc)

        hover_key = self._hover[1] if self._hover and self._hover[0] == "cell" else None
        p.setPen(QPen(COL_LINE, 0.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for cell in nm.visible_cells(self._frame, cx, cy, sc):
            if cell.key == hover_key:
                p.setBrush(COL_HOVER)
            else:
                p.setBrush(COL_FACE if cell.kind == "face" else COL_EDGE)
            p.drawPolygon(QPolygonF([QPointF(*q) for q in cell.quad]))

        self._draw_labels(p, cx, cy, sc)
        self._draw_controls(p)
        p.end()

    def _draw_compass(self, p, cx, cy, sc):
        p.save()

        path_ring, _, _ = self._compass_ring_paths(cx, cy, sc)
        ring_hovered = (
            (self._hover is not None and self._hover[0] == "compass_ring")
            or (self._press is not None and self._press["hit"][0] == "compass_ring"
                and self._press["dragging"])
        )

        p.setBrush(QBrush(QColor(70, 150, 235, 75) if ring_hovered else QColor(140, 170, 200, 40)))
        p.setPen(QPen(COL_HOVER if ring_hovered else QColor(140, 170, 200, 150), 1.5, Qt.SolidLine))
        p.drawPath(path_ring)

        # Desenha as letras N, S, E, W com escala proporcional ao cubo
        c_base, u_base, v_base = nm.face_basis("bottom", self._frame, cx, cy, sc)
        face_scale = 0.008  # fator constante; u_base/v_base já contêm a escala do cubo

        font = QFont("Arial")
        font.setBold(True)
        font.setPixelSize(100)
        p.setFont(font)

        for letter, (wx, wy), _, _ in COMPASS_CARDINALS:
            c = nm.project((wx, wy, COMPASS_Z), self._frame, cx, cy, sc)
            letter_hovered = (
                self._hover is not None
                and self._hover[0] == "compass_dir"
                and self._hover[3] == letter
            )

            p.save()
            invert_v = 1.0 if self._frame[2][2] < 0 else -1.0
            matrix = QTransform(u_base[0], u_base[1],
                                -v_base[0] * invert_v, -v_base[1] * invert_v,
                                c[0], c[1])
            p.setTransform(matrix, True)
            p.scale(face_scale, face_scale)

            p.setPen(QPen(COL_HOVER if letter_hovered else QColor(100, 120, 140), 2))
            rect = QRectF(-100, -100, 200, 200)
            p.drawText(rect, Qt.AlignCenter, letter)
            p.restore()

        p.restore()

    def _draw_labels(self, p, cx, cy, sc):
        for name in nm.visible_faces(self._frame):
            n = nm.FACES[name][0]
            if nm.dot(n, self._frame[2]) < 0.35:
                continue
            c, u2, v2 = nm.face_basis(name, self._frame, cx, cy, sc)
            text = tr(f"navcube.face.{name}")
            if text == f"navcube.face.{name}":
                text = name.upper()
            p.save()
            p.setTransform(QTransform(u2[0], u2[1], -v2[0], -v2[1], c[0], c[1]), True)
            p.scale(0.01, 0.01)
            font = QFont()
            font.setBold(True)
            font.setPixelSize(34)
            width = QFontMetricsF(font).horizontalAdvance(text)
            font.setPixelSize(max(6, int(34 * min(1.0, 105.0 / max(width, 1.0)))))
            p.setFont(font)
            p.setPen(COL_TEXT)
            p.drawText(QRectF(-60, -30, 120, 60), Qt.AlignCenter, text)
            p.restore()

    def _draw_controls(self, p):
        hv = self._hover
        r = self._home_rect()
        col = COL_HOVER if hv == ("home",) else COL_ICON
        p.setPen(QPen(col, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)

        x, y, w, h = r.x(), r.y(), r.width(), r.height()

        p.drawPolygon(QPolygonF([
            QPointF(x + w / 2, y),              # Topo do telhado
            QPointF(x + w, y + h * 0.5),        # Ponta direita do telhado
            QPointF(x + w * 0.86, y + h * 0.5), # Recuo parede direita
            QPointF(x + w * 0.86, y + h),       # Base direita
            QPointF(x + w * 0.60, y + h),       # Início direito da porta
            QPointF(x + w * 0.60, y + h * 0.66),# Topo direito da porta
            QPointF(x + w * 0.40, y + h * 0.66),# Topo esquerdo da porta
            QPointF(x + w * 0.40, y + h),       # Fim esquerdo da porta
            QPointF(x + w * 0.14, y + h),       # Base esquerda
            QPointF(x + w * 0.14, y + h * 0.5), # Recuo parede esquerda
            QPointF(x, y + h * 0.5)             # Ponta esquerda do telhado
        ]))

        if self._s.show_arrows:
            p.setPen(Qt.NoPen)
            for name, poly in self._arrow_polys().items():
                p.setBrush(COL_HOVER if hv == ("arrow", name) else COL_ICON)
                p.drawPolygon(poly)
