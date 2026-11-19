"""Quantity take-off from the plan model.

Rules (FR05):
* floor area = area of the zone contour; perimeter = sum of its edges;
* ceiling area = horizontal projection (= floor area); height steps are listed,
  vertical faces between ceiling levels are NOT added;
* walls = finished inner faces of the zone. Every zone edge is matched against
  wall faces (wall centre line +- thickness/2) and against the end faces of free
  wall ends (short returns, partition ends). Only the matched part of an edge
  is a finished face: open boundaries between zones (no partition) are not walls;
* face gross = sum over the face of length x local ceiling height (zone height or
  the ceiling region the face runs under, capped by the wall height);
* every opening is deducted from every finished face it pierces (a door between
  two rooms reduces both faces); doors/windows are counted once by unique ID.

All internal values are millimetres / mm^2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import geometry as g
from .issues import Issue
from .layout import wall_end_extensions
from .model import Opening, Plan, Wall, Zone

PARALLEL_SIN = 0.01  # ~0.57 degrees
INSIDE_PROBE_MM = 10.0  # how far inside the zone the ceiling height of a face is sampled


@dataclass
class Deduction:
    opening_id: str
    opening_type: str
    width: float
    height: float

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass
class Face:
    zone_id: str
    edge_index: int
    wall_id: str
    s0: float
    s1: float
    pieces: List[Tuple[float, float, float]]  # (s0, s1, height) along the zone edge
    deductions: List[Deduction] = field(default_factory=list)
    end_face: bool = False  # True: the edge runs along the end of a free wall end

    @property
    def length(self) -> float:
        return self.s1 - self.s0

    @property
    def heights(self) -> List[float]:
        return sorted({h for _, _, h in self.pieces})

    @property
    def height(self) -> float:
        """Length-weighted mean height (equals the height when the face has one)."""
        return self.gross / self.length if self.length > 0 else 0.0

    @property
    def gross(self) -> float:
        return sum((b - a) * h for a, b, h in self.pieces)

    @property
    def openings_area(self) -> float:
        return sum(d.area for d in self.deductions)

    @property
    def net(self) -> float:
        return self.gross - self.openings_area

    @property
    def key(self) -> str:
        return f"{self.zone_id}/e{self.edge_index}/{self.wall_id}"


@dataclass
class OpenSpan:
    zone_id: str
    edge_index: int
    s0: float
    s1: float
    neighbour: Optional[str]

    @property
    def length(self) -> float:
        return self.s1 - self.s0


@dataclass
class ZoneQuantities:
    zone: Zone
    floor_area: float
    perimeter: float
    faces: List[Face]
    open_spans: List[OpenSpan]
    ceiling_parts: List[Tuple[float, float, str]] = field(default_factory=list)  # (height, area, label)

    @property
    def ceiling_area(self) -> float:
        return self.floor_area

    @property
    def wall_gross(self) -> float:
        return sum(f.gross for f in self.faces)

    @property
    def openings_area(self) -> float:
        return sum(f.openings_area for f in self.faces)

    @property
    def wall_net(self) -> float:
        return self.wall_gross - self.openings_area


@dataclass
class Quantities:
    zones: List[ZoneQuantities]
    doors: List[str]
    windows: List[str]
    doorways: List[str]
    opening_faces: Dict[str, List[str]]
    issues: List[Issue]

    def by_zone(self, zone_id: str) -> ZoneQuantities:
        for zq in self.zones:
            if zq.zone.id == zone_id:
                return zq
        raise KeyError(zone_id)

    @property
    def interior(self) -> List[ZoneQuantities]:
        return [z for z in self.zones if z.zone.kind == "interior"]

    @property
    def balcony(self) -> List[ZoneQuantities]:
        return [z for z in self.zones if z.zone.kind == "balcony"]

    def face(self, key: str) -> Face:
        for zq in self.zones:
            for f in zq.faces:
                if f.key == key:
                    return f
        raise KeyError(key)


def m2(v_mm2: float) -> float:
    return v_mm2 / 1e6


def m(v_mm: float) -> float:
    return v_mm / 1000.0


# --------------------------------------------------------------------------- matching

def wall_cover_on_edge(p: g.Point, q: g.Point, wall: Wall, tol: float,
                       ext: Tuple[float, float] = (0.0, 0.0)) -> Optional[Tuple[float, float]]:
    """Interval [s0, s1] (mm from p along p->q) where the edge lies on a long face of `wall`.

    The face runs between the wall's ends after joint extensions: at an L-corner the
    outer face of the extended wall reaches the outer face of the other wall.
    """
    L = g.dist(p, q)
    if L < 1.0 or wall.length < 1.0:
        return None
    u = g.unit(g.sub(q, p))
    if abs(g.cross(u, wall.direction)) > PARALLEL_SIN:
        return None
    a_pt = g.add(wall.start, g.mul(wall.direction, -ext[0]))
    b_pt = g.add(wall.end, g.mul(wall.direction, ext[1]))
    sa = g.dot(g.sub(a_pt, p), u)
    sb = g.dot(g.sub(b_pt, p), u)
    s0, s1 = max(0.0, min(sa, sb)), min(L, max(sa, sb))
    if s1 - s0 <= 1.0:
        return None
    half = wall.thickness / 2.0
    for s in (s0, s1):
        pt = g.add(p, g.mul(u, s))
        d = abs(g.cross(wall.direction, g.sub(pt, wall.start)))
        if abs(d - half) > tol:
            return None
    return (s0, s1)


def wall_end_cover_on_edge(p: g.Point, q: g.Point, wall: Wall, ext: Tuple[float, float],
                           tol: float) -> Optional[Tuple[float, float]]:
    """Interval where the edge runs along an exposed end face of the wall.

    Exposed: a free end (short returns, partition ends) or the outer end of the wall
    that was extended through an L-corner. Trimmed ends (T-joints, the other wall of
    an L-corner) are buried in the neighbouring wall and never match.
    """
    L = g.dist(p, q)
    if L < 1.0 or wall.length < 1.0:
        return None
    u = g.unit(g.sub(q, p))
    if abs(g.dot(u, wall.direction)) > PARALLEL_SIN:
        return None
    half = wall.thickness / 2.0
    best = None
    ends = ((wall.start, -1.0, ext[0]), (wall.end, 1.0, ext[1]))
    for e0, sign, x in ends:
        if x < -1e-9:
            continue
        e = g.add(e0, g.mul(wall.direction, sign * x))
        if abs(g.dot(g.sub(p, e), wall.direction)) > tol:
            continue
        a = g.dot(g.sub(g.add(e, g.mul(wall.normal, half)), p), u)
        b = g.dot(g.sub(g.add(e, g.mul(wall.normal, -half)), p), u)
        s0, s1 = max(0.0, min(a, b)), min(L, max(a, b))
        if s1 - s0 > 1.0:
            best = (s0, s1)
    return best


def face_pieces(zone: Zone, p: g.Point, q: g.Point, s0: float, s1: float,
                cap: float) -> List[Tuple[float, float, float]]:
    """Split [s0, s1] of edge p->q by the ceiling regions it runs under: (s0, s1, height)."""
    u = g.unit(g.sub(q, p))
    inward = g.left_normal(u)  # zone polygons are CCW
    a = g.add(g.add(p, g.mul(u, s0)), g.mul(inward, INSIDE_PROBE_MM))
    b = g.add(g.add(p, g.mul(u, s1)), g.mul(inward, INSIDE_PROBE_MM))
    cuts = [0.0, 1.0]
    for r in zone.ceiling_regions:
        cuts += g.segment_crossings(a, b, r.polygon)
    cuts = sorted(set(cuts))
    pieces: List[Tuple[float, float, float]] = []
    for t0, t1 in zip(cuts, cuts[1:]):
        if (t1 - t0) * (s1 - s0) < 0.5:
            continue
        mid = g.add(a, g.mul(g.sub(b, a), (t0 + t1) / 2.0))
        h = min(zone.height_at(mid), cap)
        lo, hi = s0 + (s1 - s0) * t0, s0 + (s1 - s0) * t1
        if pieces and abs(pieces[-1][2] - h) < 1e-6:
            pieces[-1] = (pieces[-1][0], hi, h)
        else:
            pieces.append((lo, hi, h))
    return pieces


def ceiling_parts(zone: Zone) -> List[Tuple[float, float, str]]:
    """Horizontal ceiling area by height: (height, area mm2, label); regions take priority in order."""
    total = g.polygon_area(zone.polygon)
    parts: Dict[float, Tuple[float, str]] = {}
    used = 0.0
    taken: List[g.Polygon] = []
    for r in zone.ceiling_regions:
        piece = g.clip_convex(zone.polygon, r.polygon)
        area = g.polygon_area(piece) if len(piece) >= 3 else 0.0
        for prev in taken:  # earlier regions win where regions overlap
            ov = g.clip_convex(piece, prev) if len(piece) >= 3 else []
            area -= g.polygon_area(ov) if len(ov) >= 3 else 0.0
        taken.append(r.polygon)
        if area <= 0.5:
            continue
        a0, lbl = parts.get(r.height, (0.0, r.label))
        parts[r.height] = (a0 + area, lbl or r.label)
        used += area
    rest = total - used
    if rest > 0.5:
        a0, lbl = parts.get(zone.height, (0.0, ""))
        parts[zone.height] = (a0 + rest, lbl or "основная")
    return sorted(((h, a, lbl) for h, (a, lbl) in parts.items()), key=lambda t: t[0])


def _project_on_edge(p: g.Point, u: g.Point, pt: g.Point) -> float:
    return g.dot(g.sub(pt, p), u)


def compute(plan: Plan) -> Quantities:
    tol = plan.tol("face_match_mm")
    walls = sorted(plan.walls, key=lambda w: w.id)
    ext = wall_end_extensions(plan)
    openings_by_wall: Dict[str, List[Opening]] = {w.id: plan.openings_in(w.id) for w in walls}
    issues: List[Issue] = []
    opening_faces: Dict[str, List[str]] = {o.id: [] for o in plan.openings}

    zone_results: List[ZoneQuantities] = []
    for zone in sorted(plan.zones, key=lambda z: z.id):
        faces: List[Face] = []
        spans: List[OpenSpan] = []
        for idx, (p, q) in enumerate(g.edges(zone.polygon)):
            L = g.dist(p, q)
            u = g.unit(g.sub(q, p))
            covered: List[Tuple[float, float]] = []
            matches = [(w, wall_cover_on_edge(p, q, w, tol, ext[w.id]), False) for w in walls]
            matches += [(w, wall_end_cover_on_edge(p, q, w, ext[w.id], tol), True) for w in walls]
            for wall, cover, is_end in matches:
                if cover is None:
                    continue
                for s0, s1 in g.interval_subtract(cover, covered):
                    if s1 - s0 <= 1.0:
                        continue
                    pieces = face_pieces(zone, p, q, s0, s1, wall.height)
                    face = Face(zone.id, idx, wall.id, s0, s1, pieces, end_face=is_end)
                    for o in ([] if is_end else openings_by_wall[wall.id]):
                        t0 = _project_on_edge(p, u, wall.point_at(o.offset))
                        t1 = _project_on_edge(p, u, wall.point_at(o.offset + o.width))
                        width, area = 0.0, 0.0
                        for a, b, h in pieces:
                            ov = g.overlap_length(t0, t1, a, b)
                            vert = max(0.0, min(o.head, h) - max(o.sill, 0.0))
                            if ov > 0.5 and vert > 0.0:
                                width += ov
                                area += ov * vert
                        if width > 0.5:
                            face.deductions.append(Deduction(o.id, o.type, width, area / width))
                            opening_faces[o.id].append(face.key)
                    faces.append(face)
                covered = g.interval_union(covered + [cover])
            for s0, s1 in g.interval_subtract((0.0, L), covered):
                if s1 - s0 <= 1.0:
                    continue
                mid = g.add(p, g.mul(u, (s0 + s1) / 2.0))
                neighbour = None
                for other in sorted(plan.zones, key=lambda z: z.id):
                    if other.id != zone.id and g.point_on_boundary(mid, other.polygon, tol):
                        neighbour = other.id
                        break
                spans.append(OpenSpan(zone.id, idx, s0, s1, neighbour))
                if neighbour is None and zone.kind != "balcony":
                    issues.append(Issue(
                        "warning", zone.id,
                        f"ребро {idx}: {m(s1 - s0):.2f} м контура не лежит ни на грани стены, "
                        f"ни на границе соседней зоны — проверьте разметку"))
        zone_results.append(ZoneQuantities(
            zone=zone,
            floor_area=g.polygon_area(zone.polygon),
            perimeter=g.perimeter(zone.polygon),
            faces=faces,
            open_spans=spans,
            ceiling_parts=ceiling_parts(zone),
        ))

    for o in sorted(plan.openings, key=lambda o: o.id):
        if not opening_faces[o.id]:
            issues.append(Issue("warning", o.id, "проём не попал ни в одну отделываемую грань зон"))

    def ids(kind: str) -> List[str]:
        return sorted({o.id for o in plan.openings if o.type == kind})

    return Quantities(
        zones=zone_results,
        doors=ids("door"),
        windows=ids("window"),
        doorways=ids("doorway"),
        opening_faces=opening_faces,
        issues=issues,
    )


# --------------------------------------------------------------------------- controls

def control_coordinate(plan: Plan, ref: Dict[str, str], axis: str) -> float:
    """Coordinate of a wall face/centre line along `axis` (wall must be perpendicular to it)."""
    w = plan.walls_by_id[ref["wall"]]
    side = ref.get("side", "center")
    i = 0 if axis == "x" else 1
    c = (w.start[i] + w.end[i]) / 2.0
    half = w.thickness / 2.0
    if side == "min":
        return c - half
    if side == "max":
        return c + half
    return c


def control_measure(plan: Plan, c) -> float:
    return abs(control_coordinate(plan, c.ref_to, c.axis) - control_coordinate(plan, c.ref_from, c.axis))
