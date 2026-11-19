"""Derived 2D layout shared by checks, the PDF overlay and the Blender script."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from . import geometry as g
from .model import Opening, Plan, Wall

JOINT_TOL_MM = 5.0


@dataclass
class DoorSwing:
    hinge: g.Point          # hinge point on the wall face of the swing side
    closed_dir: g.Point     # unit vector of the closed leaf (hinge -> other jamb)
    open_dir: g.Point       # unit vector of the leaf opened 90 degrees
    radius: float           # leaf length = clear width
    sector: g.Polygon
    start_deg: float = 0.0  # sector sweep, CCW from start to end
    end_deg: float = 90.0


def _leaf_swing(wall: Wall, o: Opening, hinge_side: str, leaf: float) -> DoorSwing:
    d = wall.direction
    sigma = 1.0 if o.swing == "left" else -1.0
    s_h = o.offset if hinge_side == "start" else o.offset + o.width
    hinge = g.add(wall.point_at(s_h), g.mul(wall.normal, sigma * wall.thickness / 2.0))
    closed = d if hinge_side == "start" else g.mul(d, -1.0)
    opened = g.mul(wall.normal, sigma)
    a_closed = math.degrees(math.atan2(closed[1], closed[0]))
    a_open = math.degrees(math.atan2(opened[1], opened[0]))
    if g.cross(closed, opened) > 0:
        start, end = a_closed, a_closed + 90.0
    else:
        start, end = a_open, a_open + 90.0
    return DoorSwing(hinge, closed, opened, leaf, g.sector_polygon(hinge, leaf, start, end, 16), start, end)


def door_swings(wall: Wall, o: Opening) -> List[DoorSwing]:
    """One swing per leaf. A double door has hinges on both jambs and leaves of width/2."""
    if o.leaves == 2:
        half = o.width / 2.0
        return [_leaf_swing(wall, o, "start", half), _leaf_swing(wall, o, "end", half)]
    return [_leaf_swing(wall, o, o.hinge, o.width)]


def door_swing(wall: Wall, o: Opening) -> DoorSwing:
    """Swing of a single-leaf door (first leaf of a double door)."""
    return door_swings(wall, o)[0]


def wall_end_extensions(plan: Plan) -> Dict[str, Tuple[float, float]]:
    """Signed change of each wall's length at (start, end) so 3D wall boxes meet without overlap.

    Wall ends are drawn to centre-line intersections. For solids that tile cleanly:
    * L-corner (two wall ends meet): the wall with the smaller ID is extended to the
      outer face of the other (+t/2), the other one is trimmed to the first one's face (-t/2);
    * T-joint (an end lies inside another wall): the abutting wall stops at the face (-t/2);
    * free ends are left as drawn.
    Only the 3D model uses this; quantities come from zone contours.
    """
    out: Dict[str, Tuple[float, float]] = {}
    for w in plan.walls:
        ext = [0.0, 0.0]
        for k, pt in enumerate((w.start, w.end)):
            for other in plan.walls:
                if other.id == w.id or other.length < 1.0 or w.length < 1.0:
                    continue
                if abs(g.cross(w.direction, other.direction)) < 0.01:
                    continue
                if g.point_segment_distance(pt, other.start, other.end) > JOINT_TOL_MM:
                    continue
                at_other_end = min(g.dist(pt, other.start), g.dist(pt, other.end)) <= JOINT_TOL_MM
                if at_other_end and w.id < other.id:
                    ext[k] = other.thickness / 2.0
                else:
                    ext[k] = -other.thickness / 2.0
                break
        out[w.id] = (ext[0], ext[1])
    return out


def wall_footprint(w: Wall, ext: Tuple[float, float] = (0.0, 0.0)) -> g.Polygon:
    return g.segment_rect(w.start, w.end, w.thickness, ext[0], ext[1])


def wall_pieces(plan: Plan, w: Wall, ext: Tuple[float, float]) -> List[Tuple[float, float, float, float]]:
    """Solid parts of a wall as (s0, s1, z0, z1) in mm along its centre line.

    Openings are left genuinely empty: full-height solid between openings,
    a lintel above each opening and a sill wall below each window.
    """
    H = w.height
    pieces: List[Tuple[float, float, float, float]] = []
    cursor = -ext[0]
    for o in plan.openings_in(w.id):
        a, b = o.offset, o.offset + o.width
        if a > cursor:
            pieces.append((cursor, a, 0.0, H))
        if o.sill > 0:
            pieces.append((a, b, 0.0, o.sill))
        if o.head < H:
            pieces.append((a, b, o.head, H))
        cursor = max(cursor, b)
    end = w.length + ext[1]
    if end > cursor:
        pieces.append((cursor, end, 0.0, H))
    return [p for p in pieces if p[1] - p[0] > 0.5 and p[3] - p[2] > 0.5]
