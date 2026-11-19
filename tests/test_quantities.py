"""Acceptance checks from the SRS (phase 3 and phase 4)."""
import copy

import pytest

from conftest import build
from aptplan.quantities import m, m2


def test_reference_room_4x3(room_raw):
    # SRS phase 3: room 4 x 3 m, H = 2.8 m, door 0.9 x 2.1 m
    _, q = build(room_raw)
    z = q.by_zone("Z1")
    assert m2(z.floor_area) == pytest.approx(12.00)
    assert m(z.perimeter) == pytest.approx(14.00)
    assert m2(z.ceiling_area) == pytest.approx(12.00)
    assert m2(z.wall_gross) == pytest.approx(39.20)
    assert m2(z.openings_area) == pytest.approx(1.89)
    assert m2(z.wall_net) == pytest.approx(37.31)
    assert q.doors == ["D1"]
    assert q.windows == []


def test_door_wider_by_100mm(room_raw):
    # SRS phase 4: +100 mm door width at 2.10 m height -> net -0.21 m2 per affected face
    _, before = build(room_raw)
    changed = copy.deepcopy(room_raw)
    changed["openings"][0]["width_mm"] += 100
    _, after = build(changed)

    zb, za = before.by_zone("Z1"), after.by_zone("Z1")
    assert m2(za.wall_net - zb.wall_net) == pytest.approx(-0.21)
    assert za.floor_area == zb.floor_area
    assert za.perimeter == zb.perimeter
    assert za.wall_gross == zb.wall_gross
    assert after.doors == before.doors


def test_door_between_rooms_deducted_from_both_faces(two_rooms_raw):
    _, q = build(two_rooms_raw)
    a, b = q.by_zone("A"), q.by_zone("B")
    door = 0.8 * 2.1
    window = 1.2 * 1.5
    assert m2(a.openings_area) == pytest.approx(door + window)
    assert m2(b.openings_area) == pytest.approx(door)
    assert sorted(q.opening_faces["D1"]) == ["A/e1/W5", "B/e3/W5"]
    # door and window counted once by unique ID
    assert q.doors == ["D1"] and q.windows == ["O1"]


def test_shared_door_change_hits_each_face(two_rooms_raw):
    _, before = build(two_rooms_raw)
    changed = copy.deepcopy(two_rooms_raw)
    changed["openings"][0]["width_mm"] += 100
    _, after = build(changed)
    for zid in ("A", "B"):
        assert m2(after.by_zone(zid).wall_net - before.by_zone(zid).wall_net) == pytest.approx(-0.21)
        assert after.by_zone(zid).floor_area == before.by_zone(zid).floor_area
        assert after.by_zone(zid).perimeter == before.by_zone(zid).perimeter


def test_open_boundary_is_not_a_wall(two_rooms_raw):
    # remove the partition: the boundary between A and B becomes an open span
    raw = copy.deepcopy(two_rooms_raw)
    raw["walls"] = [w for w in raw["walls"] if w["id"] != "W5"]
    raw["openings"] = [o for o in raw["openings"] if o["wall"] != "W5"]
    raw["zones"][1]["polygon"] = [[3000, 0], [6100, 0], [6100, 3000], [3000, 3000]]
    _, q = build(raw)
    a = q.by_zone("A")
    assert m2(a.wall_gross) == pytest.approx((3 + 3 + 3) * 2.7)  # three walled edges only
    assert [s.neighbour for s in a.open_spans] == ["B"]
    assert not [i for i in q.issues if i.ref == "A"]


def test_repeatable(room_raw):
    _, q1 = build(room_raw)
    _, q2 = build(room_raw)
    assert [(f.key, f.net) for z in q1.zones for f in z.faces] == \
           [(f.key, f.net) for z in q2.zones for f in z.faces]
