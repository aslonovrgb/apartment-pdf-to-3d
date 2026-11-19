"""Typed view of plan.json.

`parse_plan` assumes the structure was already checked by
`aptplan.validate.check_structure`; geometric checks run on the parsed model.
Pure Python, importable from Blender.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import geometry as g

SUPPORTED_SCHEMA = {"1.0"}
VALUE_SOURCES = ("pdf_dimension", "scaled", "assumption")
OPENING_TYPES = ("door", "window", "doorway")
ZONE_KINDS = ("interior", "balcony")
WALL_KINDS = ("exterior", "interior", "partition")


@dataclass
class Wall:
    id: str
    start: g.Point
    end: g.Point
    thickness: float
    height: float
    kind: str
    source: str

    @property
    def length(self) -> float:
        return g.dist(self.start, self.end)

    @property
    def direction(self) -> g.Point:
        return g.unit(g.sub(self.end, self.start))

    @property
    def normal(self) -> g.Point:
        """Left normal of the start->end direction."""
        return g.left_normal(self.direction)

    def point_at(self, s: float) -> g.Point:
        return g.add(self.start, g.mul(self.direction, s))


@dataclass
class Opening:
    id: str
    type: str
    wall_id: str
    offset: float      # from wall start to the near jamb, along the centre line
    width: float
    sill: float        # bottom of the clear opening above finished floor
    head: float        # top of the clear opening above finished floor
    source: str
    hinge: str = "start"        # door only: jamb with the hinges ("start" | "end")
    swing: str = "left"         # door only: side of the wall the leaf opens to ("left" | "right")
    leaves: int = 1             # door only: 1 or 2 (double door: hinges on both jambs, hinge ignored)
    note: str = ""

    @property
    def height(self) -> float:
        return self.head - self.sill


@dataclass
class CeilingRegion:
    """Part of a zone with its own ceiling height (e.g. under a dropped plasterboard ceiling).

    The polygon must be convex; it may extend beyond the zone (it is clipped to the contour).
    """
    polygon: g.Polygon
    height: float
    source: str
    label: str = ""


@dataclass
class Zone:
    id: str
    name: str
    kind: str
    polygon: g.Polygon
    height: float
    height_source: str
    source: str
    plan_label: Optional[str] = None
    plan_area_m2: Optional[float] = None
    schedule_row: Optional[str] = None
    schedule_area_m2: Optional[float] = None
    note: str = ""
    ceiling_regions: List[CeilingRegion] = field(default_factory=list)

    def height_at(self, pt: g.Point) -> float:
        """Ceiling height at a point inside the zone: first matching region, else the zone height."""
        for r in self.ceiling_regions:
            if g.point_in_polygon(pt, r.polygon):
                return r.height
        return self.height


@dataclass
class Furniture:
    id: str
    type: str
    zone_id: str
    center: g.Point
    width: float
    depth: float
    height: float
    rotation: float = 0.0
    group: Optional[str] = None
    note: str = ""

    def footprint(self) -> g.Polygon:
        return g.rect_polygon(self.center, self.width, self.depth, self.rotation)


@dataclass
class ControlDimension:
    id: str
    description: str
    axis: str            # "x" | "y"
    expected_mm: float
    ref_from: Dict[str, str]
    ref_to: Dict[str, str]


@dataclass
class Plan:
    schema_version: str
    project: Dict[str, Any]
    source: Dict[str, Any]
    defaults: Dict[str, Any]
    zones: List[Zone]
    walls: List[Wall]
    openings: List[Opening]
    furniture: List[Furniture]
    controls: List[ControlDimension]
    assumptions: List[Dict[str, str]]
    tolerances: Dict[str, float]
    base_dir: str
    raw: Dict[str, Any] = field(repr=False, default_factory=dict)

    # ---- lookups
    @property
    def walls_by_id(self) -> Dict[str, Wall]:
        return {w.id: w for w in self.walls}

    @property
    def zones_by_id(self) -> Dict[str, Zone]:
        return {z.id: z for z in self.zones}

    def openings_in(self, wall_id: str) -> List[Opening]:
        return sorted((o for o in self.openings if o.wall_id == wall_id), key=lambda o: (o.offset, o.id))

    def source_path(self) -> Optional[str]:
        f = self.source.get("file")
        return os.path.normpath(os.path.join(self.base_dir, f)) if f else None

    def tol(self, key: str) -> float:
        return float(self.tolerances[key])


DEFAULT_TOLERANCES = {
    # max distance between a zone edge and a wall face to treat the edge as finished wall
    "face_match_mm": 25.0,
    # pilot reconciliation threshold for control dimensions (not a construction tolerance)
    "control_dimension_mm": 20.0,
    # furniture may touch walls/other items; deeper overlap is a collision
    "collision_mm": 5.0,
    # free passage between furniture groups (warning below this)
    "passage_mm": 600.0,
    # area reconciliation with labels on the drawing
    "area_ok_pct": 1.0,
    "area_check_pct": 3.0,
}


def _pt(v: Any) -> g.Point:
    return (float(v[0]), float(v[1]))


def parse_plan(raw: Dict[str, Any], base_dir: str) -> Plan:
    defaults = dict(raw.get("defaults", {}))
    default_h = float(defaults.get("ceiling_height_mm", 2700))
    default_h_src = defaults.get("ceiling_height_source", "assumption")
    default_wall_h = float(defaults.get("wall_height_mm", default_h))

    zones = []
    for z in raw.get("zones", []):
        ref = z.get("reference", {}) or {}
        zones.append(Zone(
            id=z["id"],
            name=z.get("name", z["id"]),
            kind=z.get("kind", "interior"),
            polygon=g.ensure_ccw(g.strip_closing_point(z["polygon"])),
            height=float(z.get("ceiling_height_mm", default_h)),
            height_source=z.get("height_source", default_h_src),
            source=z.get("source", "scaled"),
            plan_label=ref.get("plan_label"),
            plan_area_m2=ref.get("plan_area_m2"),
            schedule_row=ref.get("schedule_row"),
            schedule_area_m2=ref.get("schedule_area_m2"),
            note=z.get("note", ""),
            ceiling_regions=[CeilingRegion(
                polygon=g.ensure_ccw(g.strip_closing_point(r["polygon"])),
                height=float(r["height_mm"]),
                source=r.get("source", default_h_src),
                label=r.get("label", ""),
            ) for r in z.get("ceiling_regions", []) or []],
        ))

    walls = [Wall(
        id=w["id"],
        start=_pt(w["start"]),
        end=_pt(w["end"]),
        thickness=float(w["thickness_mm"]),
        height=float(w.get("height_mm", default_wall_h)),
        kind=w.get("kind", "interior"),
        source=w.get("source", "scaled"),
    ) for w in raw.get("walls", [])]

    openings = [Opening(
        id=o["id"],
        type=o["type"],
        wall_id=o["wall"],
        offset=float(o["offset_mm"]),
        width=float(o["width_mm"]),
        sill=float(o.get("sill_mm", 0.0)),
        head=float(o["head_mm"]),
        source=o.get("source", "scaled"),
        hinge=o.get("hinge", "start"),
        swing=o.get("swing", "left"),
        leaves=int(o.get("leaves", 1)),
        note=o.get("note", ""),
    ) for o in raw.get("openings", [])]

    furniture = [Furniture(
        id=f["id"],
        type=f["type"],
        zone_id=f["zone"],
        center=_pt(f["center"]),
        width=float(f["size_mm"][0]),
        depth=float(f["size_mm"][1]),
        height=float(f["size_mm"][2]),
        rotation=float(f.get("rotation_deg", 0.0)),
        group=f.get("group"),
        note=f.get("note", ""),
    ) for f in raw.get("furniture", [])]

    controls = [ControlDimension(
        id=c["id"],
        description=c.get("description", ""),
        axis=c["axis"],
        expected_mm=float(c["expected_mm"]),
        ref_from=c["from"],
        ref_to=c["to"],
    ) for c in raw.get("controls", [])]

    tolerances = dict(DEFAULT_TOLERANCES)
    tolerances.update({k: float(v) for k, v in (raw.get("tolerances") or {}).items()})

    return Plan(
        schema_version=str(raw.get("schema_version")),
        project=dict(raw.get("project", {})),
        source=dict(raw.get("source", {})),
        defaults=defaults,
        zones=zones,
        walls=walls,
        openings=openings,
        furniture=furniture,
        controls=controls,
        assumptions=list(raw.get("assumptions", [])),
        tolerances=tolerances,
        base_dir=base_dir,
        raw=raw,
    )


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_plan_unchecked(path: str) -> Plan:
    """Parse without validation (used by the Blender script after the pipeline validated it)."""
    return parse_plan(read_json(path), os.path.dirname(os.path.abspath(path)))
