"""Ceiling regions, wall end faces, double doors and the real plan (data/plan.json)."""
import copy
import os

import pytest

from conftest import ROOT, build
from aptplan.issues import errors, warnings
from aptplan.layout import door_swings
from aptplan.quantities import compute, m, m2
from aptplan.report import area_checks, control_checks
from aptplan.validate import load_and_validate

PLAN = os.path.join(ROOT, "data", "plan.json")


def test_ceiling_region_splits_face_height(room_raw):
    # lower ceiling (2.4 m) over the half of the room with y < 1500; main height 2.8 m
    raw = copy.deepcopy(room_raw)
    raw["openings"] = []
    raw["zones"][0]["ceiling_regions"] = [{
        "polygon": [[-500, -500], [4500, -500], [4500, 1500], [-500, 1500]],
        "height_mm": 2400, "source": "pdf_dimension", "label": "H2400"}]
    _, q = build(raw)
    z = q.by_zone("Z1")
    left = [f for f in z.faces if f.wall_id == "W4"][0]
    assert left.heights == [2400.0, 2800.0]
    assert m2(left.gross) == pytest.approx(1.5 * 2.4 + 1.5 * 2.8)
    # whole room: bottom wall 4 x 2.4, top wall 4 x 2.8, two side walls split in half
    assert m2(z.wall_gross) == pytest.approx(4 * 2.4 + 4 * 2.8 + 2 * (1.5 * 2.4 + 1.5 * 2.8))
    assert [(h, round(m2(a), 2)) for h, a, _ in z.ceiling_parts] == [(2400.0, 6.0), (2800.0, 6.0)]
    assert m2(z.ceiling_area) == pytest.approx(12.0)


def test_non_convex_ceiling_region_is_rejected(room_raw):
    from aptplan.validate import validate_raw
    raw = copy.deepcopy(room_raw)
    raw["zones"][0]["ceiling_regions"] = [{
        "polygon": [[0, 0], [4000, 0], [4000, 3000], [2000, 1000], [0, 3000]],
        "height_mm": 2400, "source": "pdf_dimension"}]
    _, issues = validate_raw(raw, ".")
    assert any("выпуклым" in i.message for i in errors(issues))


def test_free_wall_end_is_a_finished_face(room_raw):
    # a 1 m stub partition sticks into the room from the bottom wall: its free end (100 mm)
    # and both long faces are finished wall; the zone contour goes around it
    raw = copy.deepcopy(room_raw)
    raw["openings"] = []
    raw["walls"].append({"id": "W5", "start": [2000, -100], "end": [2000, 1000], "thickness_mm": 100,
                         "kind": "partition", "source": "assumption"})
    raw["zones"][0]["polygon"] = [[0, 0], [1950, 0], [1950, 1000], [2050, 1000], [2050, 0], [4000, 0],
                                  [4000, 3000], [0, 3000]]
    _, q = build(raw)
    z = q.by_zone("Z1")
    stub = [f for f in z.faces if f.wall_id == "W5"]
    assert sorted((round(m(f.length), 3), f.end_face) for f in stub) == [(0.1, True), (1.0, False), (1.0, False)]
    assert not z.open_spans
    # 14 m room perimeter - 0.1 m under the stub + 1.0 + 0.1 + 1.0 around it = 16.0 m
    assert m2(z.wall_gross) == pytest.approx(16.0 * 2.8)


def test_double_door_has_two_leaves(room_raw):
    raw = copy.deepcopy(room_raw)
    raw["openings"][0].update({"leaves": 2, "width_mm": 1600, "offset_mm": 800})
    raw["openings"][0].pop("hinge")
    plan, q = build(raw)
    w = plan.walls_by_id["W1"]
    leaves = door_swings(w, plan.openings[0])
    assert [round(s.radius) for s in leaves] == [800, 800]
    assert {round(s.hinge[0]) for s in leaves} == {700, 2300}
    assert q.doors == ["D1"]  # still one door


# --------------------------------------------------------------------------- real plan

@pytest.fixture(scope="module")
def real():
    plan, issues = load_and_validate(PLAN)
    assert plan is not None and not errors(issues), "\n".join(map(str, errors(issues)))
    return plan, issues, compute(plan)


def test_real_plan_is_clean(real):
    plan, issues, q = real
    assert not warnings(issues) and not q.issues
    # every contour edge is either a wall face or a boundary with a neighbouring zone (balcony aside)
    for zq in q.interior:
        assert all(s.neighbour for s in zq.open_spans), zq.zone.id


def test_real_plan_areas_match_drawing_labels(real):
    plan, _, q = real
    checks = {c.zone_id: c for c in area_checks(plan, q)}
    assert checks["Z1"].calc_m2 == pytest.approx(3.40)
    assert checks["Z2"].calc_m2 == pytest.approx(52.07)
    assert checks["Z4"].calc_m2 == pytest.approx(2.09)
    assert checks["Z3"].status == "совпадает"
    assert {c.status for c in checks.values()} <= {"совпадает", "проверить"}


def test_real_plan_control_dimensions(real):
    plan, _, _ = real
    bad = [c.id for c in control_checks(plan) if c.status != "OK"]
    # C20: 7590 is measured to the glazing frame; the wall line (7560) is the one the label 52.07 uses
    assert bad == ["C20"]


def test_real_plan_door_between_rooms_hits_both_faces(real):
    _, _, q = real
    assert sorted(q.opening_faces["D03"]) == ["Z2/e10/W21", "Z3/e9/W21"]
    assert sorted(q.opening_faces["D02"]) == ["Z1/e5/W18", "Z4/e1/W18"]
