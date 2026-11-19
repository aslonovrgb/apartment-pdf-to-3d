"""Input checks (FR02) and furniture checks (FR04).

Errors block the build; warnings are reported and written to the workbook.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional, Tuple

from . import geometry as g
from .issues import Issue
from .layout import door_swings, wall_footprint
from .model import (OPENING_TYPES, SUPPORTED_SCHEMA, VALUE_SOURCES, WALL_KINDS, ZONE_KINDS,
                    Plan, parse_plan, read_json)

# --------------------------------------------------------------------------- structure


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_pt(v: Any) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == 2 and all(_is_num(c) for c in v)


class _Checker:
    def __init__(self) -> None:
        self.issues: List[Issue] = []

    def err(self, ref: str, msg: str) -> None:
        self.issues.append(Issue("error", ref, msg))

    def warn(self, ref: str, msg: str) -> None:
        self.issues.append(Issue("warning", ref, msg))

    def need(self, obj: Dict[str, Any], key: str, ref: str, kind: str) -> bool:
        if key not in obj:
            self.err(ref, f"нет поля «{key}»")
            return False
        v = obj[key]
        ok = {
            "str": isinstance(v, str) and v != "",
            "num": _is_num(v),
            "pos": _is_num(v) and v > 0,
            "nonneg": _is_num(v) and v >= 0,
            "pt": _is_pt(v),
            "list": isinstance(v, list),
            "dict": isinstance(v, dict),
        }[kind]
        if not ok:
            expected = {"str": "непустая строка", "num": "число", "pos": "число > 0",
                        "nonneg": "число ≥ 0", "pt": "точка [x, y] в мм", "list": "список",
                        "dict": "объект"}[kind]
            self.err(ref, f"поле «{key}» должно быть: {expected}")
        return ok

    def enum(self, obj: Dict[str, Any], key: str, ref: str, allowed, required: bool = True) -> None:
        if key not in obj:
            if required:
                self.err(ref, f"нет поля «{key}» (допустимо: {', '.join(map(str, allowed))})")
            return
        if obj[key] not in allowed:
            self.err(ref, f"«{key}» = {obj[key]!r}, допустимо: {', '.join(map(str, allowed))}")


def check_structure(raw: Any) -> List[Issue]:
    c = _Checker()
    if not isinstance(raw, dict):
        c.err("plan", "корень plan.json должен быть объектом")
        return c.issues

    if raw.get("schema_version") not in SUPPORTED_SCHEMA:
        c.err("schema_version", f"неподдерживаемая версия схемы {raw.get('schema_version')!r}, "
                                f"ожидается {sorted(SUPPORTED_SCHEMA)}")

    src = raw.get("source")
    if not isinstance(src, dict):
        c.err("source", "нет блока source")
    else:
        c.need(src, "file", "source", "str")
        c.need(src, "page", "source", "pos")
        if src.get("units") != "mm":
            c.err("source", "units должны быть \"mm\"")
        scale = src.get("scale")
        if not isinstance(scale, dict) or not _is_num(scale.get("pt_per_m")) or scale.get("pt_per_m", 0) <= 0:
            c.err("source.scale", "нужен scale.pt_per_m > 0")
        origin = src.get("origin")
        if not isinstance(origin, dict) or not _is_pt(origin.get("pdf_pt")):
            c.err("source.origin", "нужен origin.pdf_pt = [x, y] в пунктах PDF")

    for key in ("zones", "walls", "openings"):
        if not isinstance(raw.get(key), list):
            c.err(key, "должен быть списком")
    if isinstance(raw.get("zones"), list) and not raw["zones"]:
        c.err("zones", "нет ни одной зоны")

    seen: Dict[str, str] = {}

    def register(item: Any, coll: str, i: int) -> Optional[str]:
        if not isinstance(item, dict):
            c.err(f"{coll}[{i}]", "элемент должен быть объектом")
            return None
        iid = item.get("id")
        if not isinstance(iid, str) or not iid:
            c.err(f"{coll}[{i}]", "нет id")
            return None
        if iid in seen:
            c.err(iid, f"ID не уникален (уже есть в {seen[iid]})")
        else:
            seen[iid] = coll
        return iid

    for i, z in enumerate(raw.get("zones") or []):
        ref = register(z, "zones", i)
        if ref is None:
            continue
        c.need(z, "name", ref, "str")
        c.enum(z, "kind", ref, ZONE_KINDS)
        c.enum(z, "source", ref, VALUE_SOURCES)
        if "ceiling_height_mm" in z:
            c.need(z, "ceiling_height_mm", ref, "pos")
        c.enum(z, "height_source", ref, VALUE_SOURCES, required=False)
        poly = z.get("polygon")
        if not isinstance(poly, list) or not all(_is_pt(p) for p in poly):
            c.err(ref, "polygon должен быть списком точек [x, y]")
        elif len(g.strip_closing_point(poly)) < 3:
            c.err(ref, "контур должен иметь не меньше 3 вершин")
        regions = z.get("ceiling_regions", [])
        if not isinstance(regions, list):
            c.err(ref, "ceiling_regions должен быть списком")
            regions = []
        for k, r in enumerate(regions):
            rref = f"{ref}.ceiling_regions[{k}]"
            if not isinstance(r, dict):
                c.err(rref, "должен быть объектом")
                continue
            c.need(r, "height_mm", rref, "pos")
            c.enum(r, "source", rref, VALUE_SOURCES)
            rp = r.get("polygon")
            if not isinstance(rp, list) or not all(_is_pt(p) for p in rp) or len(g.strip_closing_point(rp)) < 3:
                c.err(rref, "polygon должен быть списком из ≥ 3 точек [x, y]")
            elif not g.is_convex(g.strip_closing_point(rp)):
                c.err(rref, "контур участка потолка должен быть выпуклым (разбейте на прямоугольники)")

    for i, w in enumerate(raw.get("walls") or []):
        ref = register(w, "walls", i)
        if ref is None:
            continue
        c.need(w, "start", ref, "pt")
        c.need(w, "end", ref, "pt")
        c.need(w, "thickness_mm", ref, "pos")
        if "height_mm" in w:
            c.need(w, "height_mm", ref, "pos")
        c.enum(w, "kind", ref, WALL_KINDS)
        c.enum(w, "source", ref, VALUE_SOURCES)

    for i, o in enumerate(raw.get("openings") or []):
        ref = register(o, "openings", i)
        if ref is None:
            continue
        c.enum(o, "type", ref, OPENING_TYPES)
        c.need(o, "wall", ref, "str")
        c.need(o, "offset_mm", ref, "nonneg")
        c.need(o, "width_mm", ref, "pos")
        c.need(o, "head_mm", ref, "pos")
        if "sill_mm" in o:
            c.need(o, "sill_mm", ref, "nonneg")
        c.enum(o, "source", ref, VALUE_SOURCES)
        if o.get("type") == "door":
            c.enum(o, "leaves", ref, (1, 2), required=False)
            if o.get("leaves", 1) == 1:
                c.enum(o, "hinge", ref, ("start", "end"))
            c.enum(o, "swing", ref, ("left", "right"))

    for i, f in enumerate(raw.get("furniture") or []):
        ref = register(f, "furniture", i)
        if ref is None:
            continue
        c.need(f, "type", ref, "str")
        c.need(f, "zone", ref, "str")
        c.need(f, "center", ref, "pt")
        size = f.get("size_mm")
        if not (isinstance(size, list) and len(size) == 3 and all(_is_num(v) and v > 0 for v in size)):
            c.err(ref, "size_mm должен быть [ширина, глубина, высота] > 0")
        if "rotation_deg" in f and not _is_num(f["rotation_deg"]):
            c.err(ref, "rotation_deg должен быть числом")

    for i, k in enumerate(raw.get("controls") or []):
        ref = register(k, "controls", i)
        if ref is None:
            continue
        c.enum(k, "axis", ref, ("x", "y"))
        c.need(k, "expected_mm", ref, "pos")
        for end in ("from", "to"):
            r = k.get(end)
            if not isinstance(r, dict) or not isinstance(r.get("wall"), str):
                c.err(ref, f"«{end}» должен быть {{\"wall\": ID, \"side\": min|max|center}}")
            else:
                c.enum(r, "side", ref, ("min", "max", "center"), required=False)

    return c.issues


# --------------------------------------------------------------------------- geometry


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_source(plan: Plan) -> List[Issue]:
    out: List[Issue] = []
    path = plan.source_path()
    if path and not os.path.exists(path):
        out.append(Issue("warning", "source", f"файл источника не найден: {path} — наложение на PDF не будет построено"))
    elif path and plan.source.get("sha256"):
        actual = _sha256(path)
        if actual != plan.source["sha256"]:
            out.append(Issue("error", "source", "sha256 PDF не совпадает с зафиксированным в plan.json — "
                                                "это другая версия чертежа"))
    scale = plan.source.get("scale", {})
    declared = float(scale.get("pt_per_m", 0))
    for cal in scale.get("calibration", []) or []:
        try:
            measured = g.dist(cal["pt_a"], cal["pt_b"]) / (float(cal["mm"]) / 1000.0)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            out.append(Issue("error", "source.scale", f"калибровка {cal!r} заполнена неверно"))
            continue
        dev = abs(measured - declared) / declared * 100.0
        if dev > 0.3:
            out.append(Issue("warning", "source.scale",
                             f"размер {cal.get('label', cal['mm'])}: {measured:.3f} pt/м отличается от "
                             f"принятого {declared:.3f} на {dev:.2f}%"))
    return out


def check_geometry(plan: Plan) -> List[Issue]:
    out: List[Issue] = []
    E = lambda ref, msg: out.append(Issue("error", ref, msg))  # noqa: E731
    W = lambda ref, msg: out.append(Issue("warning", ref, msg))  # noqa: E731

    for z in plan.zones:
        bad = g.polygon_self_intersections(z.polygon)
        if bad:
            pairs = ", ".join(f"{i}×{j}" for i, j in bad[:5])
            E(z.id, f"контур самопересекается (рёбра {pairs})")
        elif g.polygon_area(z.polygon) < 1.0:
            E(z.id, "контур нулевой площади")
    for z in plan.zones:
        for k, r in enumerate(z.ceiling_regions):
            if g.polygon_area(g.clip_convex(z.polygon, r.polygon)) < 1.0:
                W(f"{z.id}.ceiling_regions[{k}]", "участок потолка не пересекается с контуром зоны")
    zones = sorted(plan.zones, key=lambda z: z.id)
    for i, a in enumerate(zones):
        for b in zones[i + 1:]:
            crossing = any(g.segments_properly_cross(p1, p2, q1, q2)
                           for p1, p2 in g.edges(a.polygon) for q1, q2 in g.edges(b.polygon))
            inside = any(g.point_in_polygon(p, b.polygon) and not g.point_on_boundary(p, b.polygon, 1.0)
                         for p in a.polygon) or \
                any(g.point_in_polygon(p, a.polygon) and not g.point_on_boundary(p, a.polygon, 1.0)
                    for p in b.polygon)
            if crossing or inside:
                E(a.id, f"контур перекрывается с зоной {b.id}")

    walls = plan.walls_by_id
    for w in plan.walls:
        if w.length < 1.0:
            E(w.id, "стена нулевой длины")

    by_wall: Dict[str, List] = {}
    for o in plan.openings:
        w = walls.get(o.wall_id)
        if w is None:
            E(o.id, f"ссылка на несуществующую стену {o.wall_id}")
            continue
        if w.length < 1.0:
            continue
        if o.offset + o.width > w.length + 0.5:
            E(o.id, f"проём не помещается в стену {w.id}: смещение {o.offset:.0f} + ширина {o.width:.0f} = "
                    f"{o.offset + o.width:.0f} мм > длины {w.length:.0f} мм")
        if o.head <= o.sill:
            E(o.id, f"верх проёма {o.head:.0f} мм не выше низа {o.sill:.0f} мм")
        if o.head > w.height + 0.5:
            E(o.id, f"верх проёма {o.head:.0f} мм выше стены {w.id} ({w.height:.0f} мм)")
        by_wall.setdefault(w.id, []).append(o)
    for wid, ops in by_wall.items():
        ops = sorted(ops, key=lambda o: (o.offset, o.id))
        for a, b in zip(ops, ops[1:]):
            if b.offset < a.offset + a.width - 0.5:
                E(b.id, f"проём перекрывается с {a.id} в стене {wid}")

    for c in plan.controls:
        for r in (c.ref_from, c.ref_to):
            w = walls.get(r["wall"])
            if w is None:
                E(c.id, f"ссылка на несуществующую стену {r['wall']}")
                continue
            i = 0 if c.axis == "x" else 1
            if abs(w.direction[i]) > 0.01:
                E(c.id, f"стена {w.id} не перпендикулярна оси {c.axis} — контрольный размер не определён")

    out.extend(check_furniture(plan))
    return out


def check_furniture(plan: Plan) -> List[Issue]:
    out: List[Issue] = []
    zones = plan.zones_by_id
    tol = plan.tol("collision_mm")
    passage = plan.tol("passage_mm")
    wall_polys = [(w.id, wall_footprint(w)) for w in plan.walls if w.length >= 1.0]
    swings: List[Tuple[str, g.Polygon]] = []
    walls = plan.walls_by_id
    for o in plan.openings:
        if o.type == "door" and o.wall_id in walls:
            for sw in door_swings(walls[o.wall_id], o):
                swings.append((o.id, sw.sector))

    items = sorted(plan.furniture, key=lambda f: f.id)
    feet = {f.id: f.footprint() for f in items}
    for f in items:
        fp = feet[f.id]
        z = zones.get(f.zone_id)
        if z is None:
            out.append(Issue("error", f.id, f"ссылка на несуществующую зону {f.zone_id}"))
        else:
            outside = [p for p in fp if not (g.point_in_polygon(p, z.polygon)
                                             or g.point_on_boundary(p, z.polygon, tol))]
            if outside:
                out.append(Issue("error", f.id, f"предмет выходит за контур зоны {z.id}"))
        for wid, wp in wall_polys:
            depth = g.convex_overlap_depth(fp, wp)
            if depth > tol:
                out.append(Issue("error", f.id, f"пересекается со стеной {wid} на {depth:.0f} мм"))
        for did, sp in swings:
            depth = g.convex_overlap_depth(fp, sp)
            if depth > tol:
                out.append(Issue("error", f.id, f"стоит в зоне открывания двери {did} ({depth:.0f} мм)"))

    for i, a in enumerate(items):
        for b in items[i + 1:]:
            same_group = a.group is not None and a.group == b.group
            depth = g.convex_overlap_depth(feet[a.id], feet[b.id])
            if depth > tol and not same_group:
                out.append(Issue("error", a.id, f"пересекается с {b.id} на {depth:.0f} мм"))
            elif depth <= 0 and not same_group and a.zone_id == b.zone_id:
                gap = g.polygon_gap(feet[a.id], feet[b.id])
                if tol < gap < passage:
                    out.append(Issue("warning", a.id, f"проход до {b.id} {gap:.0f} мм < {passage:.0f} мм"))
    return out


# --------------------------------------------------------------------------- entry point


def load_and_validate(path: str) -> Tuple[Optional[Plan], List[Issue]]:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return None, [Issue("error", "plan", f"файл не найден: {path}")]
    except ValueError as exc:
        return None, [Issue("error", "plan", f"plan.json не читается как JSON: {exc}")]
    return validate_raw(raw, os.path.dirname(os.path.abspath(path)))


def validate_raw(raw: Any, base_dir: str) -> Tuple[Optional[Plan], List[Issue]]:
    issues = check_structure(raw)
    if any(i.level == "error" for i in issues):
        return None, issues
    plan = parse_plan(raw, base_dir)
    issues += check_source(plan)
    issues += check_geometry(plan)
    return plan, issues
