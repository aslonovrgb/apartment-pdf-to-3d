"""2D geometry helpers in pure Python.

No third-party dependencies on purpose: this module is imported both by the
regular Python pipeline and by the Blender script (Blender's bundled Python
does not see the project's virtualenv).

Units are whatever the caller uses (the pipeline works in millimetres).
"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

Point = Tuple[float, float]
Polygon = List[Point]

EPS = 1e-9


# --------------------------------------------------------------------------- vectors

def sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def mul(a: Point, k: float) -> Point:
    return (a[0] * k, a[1] * k)


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def norm(a: Point) -> float:
    return math.hypot(a[0], a[1])


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def unit(a: Point) -> Point:
    n = norm(a)
    if n < EPS:
        raise ValueError("zero-length vector")
    return (a[0] / n, a[1] / n)


def left_normal(a: Point) -> Point:
    """Vector rotated +90 degrees (counter-clockwise)."""
    return (-a[1], a[0])


def rotate(p: Point, angle_deg: float) -> Point:
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


# --------------------------------------------------------------------------- polygons

def edges(poly: Sequence[Point]) -> List[Tuple[Point, Point]]:
    n = len(poly)
    return [(poly[i], poly[(i + 1) % n]) for i in range(n)]


def signed_area(poly: Sequence[Point]) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in edges(poly):
        s += x1 * y2 - x2 * y1
    return s / 2.0


def polygon_area(poly: Sequence[Point]) -> float:
    return abs(signed_area(poly))


def perimeter(poly: Sequence[Point]) -> float:
    return sum(dist(a, b) for a, b in edges(poly))


def ensure_ccw(poly: Sequence[Point]) -> Polygon:
    pts = [tuple(p) for p in poly]
    return pts if signed_area(pts) >= 0 else pts[::-1]


def strip_closing_point(poly: Sequence[Point]) -> Polygon:
    pts = [(float(p[0]), float(p[1])) for p in poly]
    if len(pts) > 1 and dist(pts[0], pts[-1]) < EPS:
        pts = pts[:-1]
    return pts


def centroid(poly: Sequence[Point]) -> Point:
    a = signed_area(poly)
    if abs(a) < EPS:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    cx = cy = 0.0
    for (x1, y1), (x2, y2) in edges(poly):
        f = x1 * y2 - x2 * y1
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    return (cx / (6 * a), cy / (6 * a))


def bbox(points: Sequence[Point]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------------------- segments

def _orient(a: Point, b: Point, c: Point) -> float:
    return cross(sub(b, a), sub(c, a))


def _on_segment(a: Point, b: Point, p: Point, tol: float = 1e-7) -> bool:
    return (min(a[0], b[0]) - tol <= p[0] <= max(a[0], b[0]) + tol
            and min(a[1], b[1]) - tol <= p[1] <= max(a[1], b[1]) + tol)


def segments_intersect(p1: Point, p2: Point, q1: Point, q2: Point, tol: float = 1e-7) -> bool:
    """True if closed segments share at least one point."""
    d1 = _orient(q1, q2, p1)
    d2 = _orient(q1, q2, p2)
    d3 = _orient(p1, p2, q1)
    d4 = _orient(p1, p2, q2)
    if ((d1 > tol and d2 < -tol) or (d1 < -tol and d2 > tol)) and \
       ((d3 > tol and d4 < -tol) or (d3 < -tol and d4 > tol)):
        return True
    if abs(d1) <= tol and _on_segment(q1, q2, p1, tol):
        return True
    if abs(d2) <= tol and _on_segment(q1, q2, p2, tol):
        return True
    if abs(d3) <= tol and _on_segment(p1, p2, q1, tol):
        return True
    if abs(d4) <= tol and _on_segment(p1, p2, q2, tol):
        return True
    return False


def segments_properly_cross(p1: Point, p2: Point, q1: Point, q2: Point, tol: float = 1e-6) -> bool:
    """True only if the segments cross at a single interior point of both."""
    d1 = _orient(q1, q2, p1)
    d2 = _orient(q1, q2, p2)
    d3 = _orient(p1, p2, q1)
    d4 = _orient(p1, p2, q2)
    return (((d1 > tol and d2 < -tol) or (d1 < -tol and d2 > tol))
            and ((d3 > tol and d4 < -tol) or (d3 < -tol and d4 > tol)))


def point_segment_distance(p: Point, a: Point, b: Point) -> float:
    ab = sub(b, a)
    L2 = dot(ab, ab)
    if L2 < EPS:
        return dist(p, a)
    t = max(0.0, min(1.0, dot(sub(p, a), ab) / L2))
    return dist(p, add(a, mul(ab, t)))


def polygon_self_intersections(poly: Sequence[Point]) -> List[Tuple[int, int]]:
    """Pairs of edge indices that intersect illegally.

    Adjacent edges may only share their common vertex; non-adjacent edges must
    not touch at all.
    """
    n = len(poly)
    es = edges(poly)
    bad: List[Tuple[int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            a1, a2 = es[i]
            b1, b2 = es[j]
            adjacent = (j == i + 1) or (i == 0 and j == n - 1)
            if adjacent:
                # collinear overlap or fold-back of neighbouring edges
                shared = a2 if j == i + 1 else a1
                other_a = a1 if j == i + 1 else a2
                other_b = b2 if j == i + 1 else b1
                if abs(_orient(other_a, shared, other_b)) < 1e-6 and \
                        dot(sub(other_a, shared), sub(other_b, shared)) > 0:
                    bad.append((i, j))
                continue
            if segments_intersect(a1, a2, b1, b2):
                bad.append((i, j))
    return bad


def point_on_boundary(p: Point, poly: Sequence[Point], tol: float) -> bool:
    return any(point_segment_distance(p, a, b) <= tol for a, b in edges(poly))


def point_in_polygon(p: Point, poly: Sequence[Point]) -> bool:
    """Ray casting; points exactly on the boundary are undefined (use point_on_boundary)."""
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in edges(poly):
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                inside = not inside
    return inside


def label_point(poly: Sequence[Point], samples: int = 40) -> Point:
    """A point well inside the polygon (deterministic grid search)."""
    c = centroid(poly)
    best, best_d = None, -1.0
    if point_in_polygon(c, poly):
        best, best_d = c, min(point_segment_distance(c, a, b) for a, b in edges(poly))
    x0, y0, x1, y1 = bbox(poly)
    for i in range(1, samples):
        for j in range(1, samples):
            p = (x0 + (x1 - x0) * i / samples, y0 + (y1 - y0) * j / samples)
            if not point_in_polygon(p, poly):
                continue
            d = min(point_segment_distance(p, a, b) for a, b in edges(poly))
            if d > best_d * 1.25:  # prefer the centroid unless clearly better
                best, best_d = p, d
    return best if best is not None else c


# --------------------------------------------------------------------------- shapes

def rect_polygon(center: Point, width: float, depth: float, rotation_deg: float = 0.0) -> Polygon:
    """Rectangle centred at `center`; width along local x, depth along local y. CCW."""
    hw, hd = width / 2.0, depth / 2.0
    local = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    return [add(center, rotate(p, rotation_deg)) for p in local]


def segment_rect(a: Point, b: Point, thickness: float, ext_a: float = 0.0, ext_b: float = 0.0) -> Polygon:
    """Rectangle around segment a-b (optionally extended at both ends). CCW."""
    d = unit(sub(b, a))
    n = left_normal(d)
    h = thickness / 2.0
    a2 = sub(a, mul(d, ext_a))
    b2 = add(b, mul(d, ext_b))
    return [add(a2, mul(n, -h)), add(b2, mul(n, -h)), add(b2, mul(n, h)), add(a2, mul(n, h))]


def sector_polygon(center: Point, radius: float, start_deg: float, end_deg: float, steps: int = 12) -> Polygon:
    """Circular sector (pie slice) as a polygon, CCW from start to end angle."""
    pts = [center]
    for k in range(steps + 1):
        a = math.radians(start_deg + (end_deg - start_deg) * k / steps)
        pts.append((center[0] + radius * math.cos(a), center[1] + radius * math.sin(a)))
    return ensure_ccw(pts)


# --------------------------------------------------------------------------- convex tests

def _project(poly: Sequence[Point], axis: Point) -> Tuple[float, float]:
    vals = [dot(p, axis) for p in poly]
    return min(vals), max(vals)


def convex_overlap_depth(a: Sequence[Point], b: Sequence[Point]) -> float:
    """Separating-axis test for two convex polygons.

    Returns the minimal penetration depth (> 0 means the interiors overlap,
    <= 0 means separated or only touching; the magnitude is the gap along the
    best separating axis, which is a lower bound of the true distance).
    """
    best = math.inf
    for poly in (a, b):
        for p, q in edges(poly):
            e = sub(q, p)
            if norm(e) < EPS:
                continue
            axis = unit(left_normal(e))
            a0, a1 = _project(a, axis)
            b0, b1 = _project(b, axis)
            overlap = min(a1, b1) - max(a0, b0)
            best = min(best, overlap)
    return best


def polygon_gap(a: Sequence[Point], b: Sequence[Point]) -> float:
    """Minimum distance between the boundaries of two non-overlapping polygons."""
    best = math.inf
    for p in a:
        for s, t in edges(b):
            best = min(best, point_segment_distance(p, s, t))
    for p in b:
        for s, t in edges(a):
            best = min(best, point_segment_distance(p, s, t))
    return best


# --------------------------------------------------------------------------- intervals

def interval_union(intervals: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for s, e in sorted((min(a, b), max(a, b)) for a, b in intervals):
        if out and s <= out[-1][1] + EPS:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def interval_subtract(base: Tuple[float, float], cuts: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Parts of `base` not covered by `cuts`."""
    parts = [base]
    for c0, c1 in interval_union(cuts):
        nxt = []
        for s, e in parts:
            if c1 <= s or c0 >= e:
                nxt.append((s, e))
                continue
            if c0 > s:
                nxt.append((s, c0))
            if c1 < e:
                nxt.append((c1, e))
        parts = nxt
    return [(s, e) for s, e in parts if e - s > EPS]


def overlap_length(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(max(a0, a1), max(b0, b1)) - max(min(a0, a1), min(b0, b1)))


# --------------------------------------------------------------------------- convex clipping

def is_convex(poly: Sequence[Point], tol: float = 1e-6) -> bool:
    """True for a convex polygon (collinear vertices allowed)."""
    n = len(poly)
    if n < 3:
        return False
    sign = 0
    for i in range(n):
        c = _orient(poly[i], poly[(i + 1) % n], poly[(i + 2) % n])
        if abs(c) <= tol:
            continue
        s = 1 if c > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return sign != 0


def clip_convex(subject: Sequence[Point], clip: Sequence[Point]) -> Polygon:
    """Sutherland-Hodgman: part of `subject` inside the convex CCW polygon `clip`.

    The subject may be concave; the result can then contain zero-width bridges,
    which do not change its area (only the area of the result is used).
    """
    out: Polygon = list(subject)
    for a, b in edges(clip):
        if not out:
            break
        inp, out = out, []
        for i, p in enumerate(inp):
            q = inp[(i + 1) % len(inp)]
            p_in = _orient(a, b, p) >= -1e-9
            q_in = _orient(a, b, q) >= -1e-9
            if p_in:
                out.append(p)
            if p_in != q_in:
                d1, d2 = _orient(a, b, p), _orient(a, b, q)
                t = d1 / (d1 - d2)
                out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def segment_crossings(a: Point, b: Point, poly: Sequence[Point]) -> List[float]:
    """Parameters t in (0, 1) where segment a->b crosses the edges of `poly`."""
    ts: List[float] = []
    r = sub(b, a)
    for p, q in edges(poly):
        s = sub(q, p)
        den = cross(r, s)
        if abs(den) < 1e-12:
            continue
        t = cross(sub(p, a), s) / den
        u = cross(sub(p, a), r) / den
        if 1e-9 < t < 1 - 1e-9 and -1e-9 <= u <= 1 + 1e-9:
            ts.append(t)
    return sorted(ts)
