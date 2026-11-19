"""Reconciliation logic and a machine-readable summary (used by Excel, JSON and the demo)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .model import Plan
from .quantities import Quantities, control_measure, m, m2


@dataclass
class AreaCheck:
    zone_id: str
    name: str
    kind: str
    calc_m2: float
    plan_label: Optional[str]
    plan_m2: Optional[float]
    schedule_row: Optional[str]
    schedule_m2: Optional[float]
    status: str
    note: str

    @property
    def diff_m2(self) -> Optional[float]:
        return None if self.plan_m2 is None else self.calc_m2 - self.plan_m2

    @property
    def diff_pct(self) -> Optional[float]:
        return None if not self.plan_m2 else (self.calc_m2 - self.plan_m2) / self.plan_m2 * 100.0

    @property
    def schedule_diff_m2(self) -> Optional[float]:
        return None if self.schedule_m2 is None else self.calc_m2 - self.schedule_m2


def area_status(calc: float, ref: Optional[float], ok_pct: float, check_pct: float) -> str:
    if ref is None:
        return "нет подписи"
    if ref == 0:
        return "расхождение"
    pct = abs(calc - ref) / ref * 100.0
    if pct <= ok_pct:
        return "совпадает"
    if pct <= check_pct:
        return "проверить"
    return "расхождение"


def area_checks(plan: Plan, q: Quantities) -> List[AreaCheck]:
    out = []
    for zq in q.zones:
        z = zq.zone
        calc = round(m2(zq.floor_area), 2)
        status = area_status(calc, z.plan_area_m2, plan.tol("area_ok_pct"), plan.tol("area_check_pct"))
        note = z.note
        if z.schedule_area_m2 is not None and z.plan_area_m2 is not None and \
                area_status(z.plan_area_m2, z.schedule_area_m2, plan.tol("area_ok_pct"), plan.tol("area_check_pct")) != "совпадает":
            note = (note + " " if note else "") + "Подпись на плане и экспликация не совпадают; приоритет — геометрия чертежа."
        out.append(AreaCheck(z.id, z.name, z.kind, calc, z.plan_label, z.plan_area_m2,
                             z.schedule_row, z.schedule_area_m2, status, note))
    return out


@dataclass
class ControlCheck:
    id: str
    description: str
    expected_mm: float
    model_mm: float
    status: str

    @property
    def diff_mm(self) -> float:
        return self.model_mm - self.expected_mm


def control_checks(plan: Plan) -> List[ControlCheck]:
    out = []
    lim = plan.tol("control_dimension_mm")
    for c in plan.controls:
        val = control_measure(plan, c)
        status = "OK" if abs(val - c.expected_mm) <= lim else f"> {lim:.0f} мм"
        out.append(ControlCheck(c.id, c.description, c.expected_mm, round(val, 1), status))
    return out


def r2(v: float) -> float:
    return round(v + 0.0, 2)


def summary(plan: Plan, q: Quantities) -> Dict[str, Any]:
    """Rounded values, stable ordering — suitable for diffing two builds."""
    zones = []
    for zq in q.zones:
        zones.append({
            "id": zq.zone.id,
            "name": zq.zone.name,
            "kind": zq.zone.kind,
            "floor_m2": r2(m2(zq.floor_area)),
            "perimeter_m": r2(m(zq.perimeter)),
            "plinth_m": r2(m(zq.plinth)),
            "ceiling_m2": r2(m2(zq.ceiling_area)),
            "ceiling_height_m": r2(m(zq.zone.height)),
            "ceiling_by_height": [{"height_m": round(m(h), 3), "area_m2": r2(m2(a)), "label": lbl}
                                  for h, a, lbl in zq.ceiling_parts],
            "walls_gross_m2": r2(m2(zq.wall_gross)),
            "openings_m2": r2(m2(zq.openings_area)),
            "walls_net_m2": r2(m2(zq.wall_net)),
            "faces": [{
                "key": f.key, "length_m": r2(m(f.length)), "height_m": r2(m(f.height)),
                "heights_m": [round(m(h), 3) for h in f.heights], "end_face": f.end_face,
                "gross_m2": r2(m2(f.gross)), "openings_m2": r2(m2(f.openings_area)),
                "net_m2": r2(m2(f.net)), "plinth_m": r2(m(f.plinth)),
                "openings": [d.opening_id for d in f.deductions],
            } for f in zq.faces],
        })

    def total(zs, attr):
        return r2(sum(m2(getattr(z, attr)) for z in zs))

    return {
        "project": plan.project.get("name", ""),
        "zones": zones,
        "interior_total": {
            "floor_m2": total(q.interior, "floor_area"),
            "plinth_m": r2(sum(m(z.plinth) for z in q.interior)),
            "ceiling_m2": total(q.interior, "ceiling_area"),
            "walls_gross_m2": total(q.interior, "wall_gross"),
            "openings_m2": total(q.interior, "openings_area"),
            "walls_net_m2": total(q.interior, "wall_net"),
        },
        "balcony_total": {
            "floor_m2": total(q.balcony, "floor_area"),
            "walls_net_m2": total(q.balcony, "wall_net"),
        },
        "counts": {"doors": len(q.doors), "windows": len(q.windows), "doorways": len(q.doorways)},
        "door_ids": q.doors,
        "window_ids": q.windows,
    }
