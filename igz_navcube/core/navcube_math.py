"""Pure-Python math for the NavCube (no Qt dependency).

Conventions
-----------
* World is Z-up, right-handed. FRONT looks toward +Y (eye at -Y), RIGHT is +X.
* A camera *frame* is the tuple (right, up, toward) of world-space unit vectors,
  where ``toward`` points from the target to the eye and right x up = toward.
"""
import math
from dataclasses import dataclass

PERSPECTIVE = 7.0          # eye distance in cube half-sizes (0 = orthographic)
EDGE_RATIO = 0.7           # half-width of the central face cell (rest = edge/corner)
HOME_DIRECTION = (1.0, -1.0, 1.0)

# name: (normal, u axis (text right), v axis (text up)); u x v == normal
FACES = {
    "top":    ((0, 0, 1),  (1, 0, 0),  (0, 1, 0)),
    "bottom": ((0, 0, -1), (1, 0, 0),  (0, -1, 0)),
    "front":  ((0, -1, 0), (1, 0, 0),  (0, 0, 1)),
    "back":   ((0, 1, 0),  (-1, 0, 0), (0, 0, 1)),
    "right":  ((1, 0, 0),  (0, 1, 0),  (0, 0, 1)),
    "left":   ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
}


# ---------------------------------------------------------------- vectors
def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def normalize(a):
    n = math.sqrt(dot(a, a))
    if n < 1e-12:
        raise ValueError("zero-length vector")
    return (a[0] / n, a[1] / n, a[2] / n)


def rotate_about_axis(v, axis, angle):
    """Rodrigues rotation of v around the unit vector axis."""
    c, s = math.cos(angle), math.sin(angle)
    kxv = cross(axis, v)
    kdv = dot(axis, v) * (1.0 - c)
    return (v[0] * c + kxv[0] * s + axis[0] * kdv,
            v[1] * c + kxv[1] * s + axis[1] * kdv,
            v[2] * c + kxv[2] * s + axis[2] * kdv)


# ---------------------------------------------------------------- frames
def frame_from_view(toward, up=(0, 0, 1)):
    """Build an orthonormal frame (right, up, toward) from a view direction."""
    t = normalize(toward)
    r = cross(up, t)
    if dot(r, r) < 1e-12:                      # up parallel to toward
        r = cross((0, 1, 0), t) if abs(t[1]) < 0.9 else cross((1, 0, 0), t)
    r = normalize(r)
    u = cross(t, r)
    return (r, u, t)


def up_for_direction(d):
    """Up vector used when snapping to a standard direction."""
    d = normalize(d)
    if d[2] > 0.999:
        return (0, 1, 0)       # TOP: front edge at the bottom of the screen
    if d[2] < -0.999:
        return (0, -1, 0)      # BOTTOM: X still points right
    return (0, 0, 1)


def frame_for_direction(d):
    return frame_from_view(d, up_for_direction(d))


def orbit(frame, yaw_deg, pitch_deg):
    """Orbit the eye: +yaw moves it right (about world Z), +pitch moves it up."""
    z = (0, 0, 1)
    ya = math.radians(yaw_deg)
    r, u, t = (rotate_about_axis(v, z, ya) for v in frame)
    pa = math.radians(-pitch_deg)
    t, u = rotate_about_axis(t, r, pa), rotate_about_axis(u, r, pa)
    return frame_from_view(t, u)


# ------------------------------------------------------------ quaternions
def frame_to_quat(frame):
    r, u, t = frame
    m00, m10, m20 = r
    m01, m11, m21 = u
    m02, m12, m22 = t
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = (0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s)
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        q = ((m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s)
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        q = ((m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s)
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        q = ((m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s)
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def quat_to_frame(q):
    w, x, y, z = q
    r = (1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y))
    u = (2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x))
    t = (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y))
    return (r, u, t)


def slerp(q0, q1, k):
    d = sum(a * b for a, b in zip(q0, q1))
    if d < 0:
        q1, d = tuple(-c for c in q1), -d
    if d > 0.9995:
        q = tuple(a + k * (b - a) for a, b in zip(q0, q1))
    else:
        th = math.acos(d)
        s0 = math.sin((1 - k) * th) / math.sin(th)
        s1 = math.sin(k * th) / math.sin(th)
        q = tuple(s0 * a + s1 * b for a, b in zip(q0, q1))
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def quat_angle(q0, q1):
    d = min(1.0, abs(sum(a * b for a, b in zip(q0, q1))))
    return 2.0 * math.acos(d)


# -------------------------------------------------------------- projection
def project(p, frame, cx, cy, scale):
    r, u, t = frame
    x, y, z = dot(p, r), dot(p, u), dot(p, t)
    k = PERSPECTIVE / (PERSPECTIVE - z) if PERSPECTIVE > 0 else 1.0
    return (cx + x * k * scale, cy - y * k * scale)


def _visible_threshold():
    return 1.0 / PERSPECTIVE if PERSPECTIVE > 0 else 0.0


def visible_faces(frame):
    th = _visible_threshold()
    return [n for n, (nv, _, _) in FACES.items() if dot(nv, frame[2]) > th]


@dataclass(frozen=True)
class Cell:
    face: str
    key: tuple      # direction toward the viewer when clicked, e.g. (1, -1, 1)
    kind: str       # "face" | "edge" | "corner"
    quad: tuple     # four (x, y) screen points


def _span(i):
    b = EDGE_RATIO
    return {-1: (-1.0, -b), 0: (-b, b), 1: (b, 1.0)}[i]


def visible_cells(frame, cx, cy, scale):
    """3x3 cells (face / edges / corners) of every front-facing face."""
    out = []
    for name in visible_faces(frame):
        n, u, v = FACES[name]
        for i in (-1, 0, 1):
            a0, a1 = _span(i)
            for j in (-1, 0, 1):
                c0, c1 = _span(j)
                pts = [add(n, add(mul(u, a), mul(v, c)))
                       for a, c in ((a0, c0), (a1, c0), (a1, c1), (a0, c1))]
                quad = tuple(project(p, frame, cx, cy, scale) for p in pts)
                key = tuple(int(n[k] + i * u[k] + j * v[k]) for k in range(3))
                kind = ("face", "edge", "corner")[sum(1 for c in key if c) - 1]
                out.append(Cell(name, key, kind, quad))
    return out


def face_basis(name, frame, cx, cy, scale):
    """Screen-space (center, u vector, v vector) of a face, for drawing labels."""
    n, u, v = FACES[name]
    c = project(n, frame, cx, cy, scale)
    pu = project(add(n, u), frame, cx, cy, scale)
    pv = project(add(n, v), frame, cx, cy, scale)
    return c, (pu[0] - c[0], pu[1] - c[1]), (pv[0] - c[0], pv[1] - c[1])


def key_faces(key):
    """Face names touched by a direction key, e.g. (1,-1,1) -> right, front, top."""
    names = []
    if key[0]:
        names.append("right" if key[0] > 0 else "left")
    if key[1]:
        names.append("back" if key[1] > 0 else "front")
    if key[2]:
        names.append("top" if key[2] > 0 else "bottom")
    return names
