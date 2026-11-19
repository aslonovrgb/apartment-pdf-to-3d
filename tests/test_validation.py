"""FR02 / FR04: blocking errors carry the element ID and the reason."""
import copy

from conftest import FIXTURES
from aptplan.issues import errors
from aptplan.validate import validate_raw


def errs_of(raw):
    _, issues = validate_raw(copy.deepcopy(raw), FIXTURES)
    return errors(issues)


def refs(raw):
    return {(e.ref, e.message.split(" ")[0]) for e in errs_of(raw)}


def test_valid_fixtures_have_no_errors(room_raw, two_rooms_raw):
    assert errs_of(room_raw) == []
    assert errs_of(two_rooms_raw) == []


def test_duplicate_id(room_raw):
    room_raw["walls"][1]["id"] = "W1"
    e = errs_of(room_raw)
    assert any(x.ref == "W1" and "не уникален" in x.message for x in e)


def test_self_intersecting_contour(room_raw):
    room_raw["zones"][0]["polygon"] = [[0, 0], [4000, 3000], [4000, 0], [0, 3000]]
    e = errs_of(room_raw)
    assert any(x.ref == "Z1" and "самопересекается" in x.message for x in e)


def test_missing_wall_reference(room_raw):
    room_raw["openings"][0]["wall"] = "W99"
    e = errs_of(room_raw)
    assert any(x.ref == "D1" and "W99" in x.message for x in e)


def test_opening_does_not_fit(room_raw):
    room_raw["openings"][0]["offset_mm"] = 3800
    e = errs_of(room_raw)
    assert any(x.ref == "D1" and "не помещается" in x.message for x in e)


def test_overlapping_openings(room_raw):
    extra = copy.deepcopy(room_raw["openings"][0])
    extra.update(id="D2", offset_mm=1500)
    room_raw["openings"].append(extra)
    e = errs_of(room_raw)
    assert any(x.ref == "D2" and "перекрывается" in x.message for x in e)


def test_value_source_required(room_raw):
    del room_raw["walls"][0]["source"]
    e = errs_of(room_raw)
    assert any(x.ref == "W1" and "source" in x.message for x in e)


def test_furniture_in_door_swing(room_raw):
    room_raw["furniture"] = [{"id": "F1", "type": "wardrobe", "zone": "Z1", "center": [1400, 300],
                              "size_mm": [800, 600, 2000]}]
    e = errs_of(room_raw)
    assert any(x.ref == "F1" and "открывания двери D1" in x.message for x in e)


def test_furniture_in_wall(room_raw):
    room_raw["furniture"] = [{"id": "F1", "type": "bed", "zone": "Z1", "center": [3500, 1500],
                              "size_mm": [1400, 2000, 450], "rotation_deg": 0}]
    e = errs_of(room_raw)
    assert any(x.ref == "F1" and "стеной W2" in x.message for x in e)


def test_furniture_against_wall_is_fine(room_raw):
    # flush with the inner face of W3 and W2: touching is not a collision
    room_raw["furniture"] = [{"id": "F1", "type": "bed", "zone": "Z1", "center": [3200, 2000],
                              "size_mm": [1600, 2000, 450], "rotation_deg": 0}]
    assert errs_of(room_raw) == []


def test_structure_error_stops_before_geometry(room_raw):
    room_raw["zones"][0]["polygon"] = "oops"
    plan, issues = validate_raw(room_raw, FIXTURES)
    assert plan is None
    assert any(i.ref == "Z1" for i in errors(issues))
