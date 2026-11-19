import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def room_raw():
    return load_fixture("room_4x3.json")


@pytest.fixture
def two_rooms_raw():
    return load_fixture("two_rooms.json")


def build(raw):
    """Validate + compute; fails the test on blocking errors."""
    from aptplan.issues import errors
    from aptplan.quantities import compute
    from aptplan.validate import validate_raw

    plan, issues = validate_raw(copy.deepcopy(raw), FIXTURES)
    errs = errors(issues)
    assert not errs, "\n".join(map(str, errs))
    return plan, compute(plan)
