"""Unit tests for the AST-based rule condition evaluator.

Tests cover:
  - Condition normalization (AND/OR/NOT → Python keywords)
  - Arithmetic comparisons
  - Attribute access (building.*)
  - ``within()`` schedule helper
  - Boolean operators (and / or / not)
  - Security: disallowed AST nodes are rejected
  - Edge cases: unknown names, bad syntax, empty conditions
"""

import datetime

import pytest

from services.rules_engine.evaluator import (
    _normalize_condition,
    evaluate_condition,
    within,
)


# ---------------------------------------------------------------------------
# _normalize_condition
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_normalize_and():
    assert _normalize_condition("A AND B") == "A and B"


@pytest.mark.unit
def test_normalize_or():
    assert _normalize_condition("A OR B") == "A or B"


@pytest.mark.unit
def test_normalize_not():
    assert _normalize_condition("NOT A") == "not A"


@pytest.mark.unit
def test_normalize_combined():
    assert _normalize_condition("NOT A OR B") == "not A or B"


@pytest.mark.unit
def test_normalize_no_change_for_lowercase():
    # Already lowercase → unchanged
    assert _normalize_condition("a and b or not c") == "a and b or not c"


# ---------------------------------------------------------------------------
# evaluate_condition — basic arithmetic comparisons
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_evaluate_gt_true():
    context = {"kwh": 100}
    assert evaluate_condition("kwh > 70", context) is True


@pytest.mark.unit
def test_evaluate_gt_false():
    context = {"kwh": 50}
    assert evaluate_condition("kwh > 70", context) is False


@pytest.mark.unit
def test_evaluate_gte():
    context = {"kwh": 70}
    assert evaluate_condition("kwh >= 70", context) is True


@pytest.mark.unit
def test_evaluate_multiplication():
    building = {"declared_unoccupied_baseline": 50}
    context = {"kwh": 100, "building": building}
    # 100 > 50 * 1.4 → 100 > 70 → True
    assert evaluate_condition("kwh > building.declared_unoccupied_baseline * 1.4", context) is True


@pytest.mark.unit
def test_evaluate_multiplication_false():
    building = {"declared_unoccupied_baseline": 80}
    context = {"kwh": 100, "building": building}
    # 100 > 80 * 1.4 → 100 > 112 → False
    assert evaluate_condition("kwh > building.declared_unoccupied_baseline * 1.4", context) is False


# ---------------------------------------------------------------------------
# evaluate_condition — boolean operators
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_evaluate_and_true():
    context = {"a": 10, "b": 20}
    assert evaluate_condition("a > 5 AND b > 10", context) is True


@pytest.mark.unit
def test_evaluate_and_false_left():
    context = {"a": 1, "b": 20}
    assert evaluate_condition("a > 5 AND b > 10", context) is False


@pytest.mark.unit
def test_evaluate_or_true():
    context = {"a": 1, "b": 20}
    assert evaluate_condition("a > 5 OR b > 10", context) is True


@pytest.mark.unit
def test_evaluate_not():
    context = {"a": 1}
    assert evaluate_condition("NOT a > 5", context) is True


@pytest.mark.unit
def test_evaluate_not_false():
    context = {"a": 10}
    assert evaluate_condition("NOT a > 5", context) is False


# ---------------------------------------------------------------------------
# evaluate_condition — in operator
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_evaluate_in_tuple():
    context = {"ts": datetime.datetime(2026, 6, 27, 12, 0)}  # Saturday = isoweekday 6
    # Use a helper attribute via method call on datetime — test the int literal
    context2 = {"day": 6}
    assert evaluate_condition("day in (6, 7)", context2) is True


@pytest.mark.unit
def test_evaluate_not_in_tuple():
    context = {"day": 3}
    assert evaluate_condition("day in (6, 7)", context) is False


# ---------------------------------------------------------------------------
# evaluate_condition — security: disallowed constructs return False
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_security_import_statement_rejected():
    # An ``import`` statement is not a valid expression; parse fails safely.
    assert evaluate_condition("__import__('os')", {}) is False


@pytest.mark.unit
def test_security_class_traversal_rejected():
    # Class-traversal that would escape a naive eval() sandbox.
    assert evaluate_condition(
        "''.__class__.__mro__[1].__subclasses__()", {}
    ) is False


@pytest.mark.unit
def test_security_lambda_rejected():
    # Lambda is a disallowed AST node.
    assert evaluate_condition("(lambda: None)()", {}) is False


@pytest.mark.unit
def test_security_arbitrary_function_call_rejected():
    # Only within() is permitted as a function call.
    assert evaluate_condition("print('hacked')", {}) is False


@pytest.mark.unit
def test_security_exec_rejected():
    assert evaluate_condition("exec('pass')", {}) is False


# ---------------------------------------------------------------------------
# evaluate_condition — error cases return False (never raise)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bad_syntax_returns_false():
    assert evaluate_condition("kwh >>> 100", {}) is False


@pytest.mark.unit
def test_unknown_name_returns_false():
    assert evaluate_condition("nonexistent_var > 0", {}) is False


@pytest.mark.unit
def test_empty_condition_returns_false():
    assert evaluate_condition("", {}) is False


# ---------------------------------------------------------------------------
# within() — schedule helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_within_inside_schedule():
    schedule = {"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "18:00"}
    # 2026-06-26 is a Friday (isoweekday=5), 12:00 is inside
    assert within(schedule, datetime.datetime(2026, 6, 26, 12, 0)) is True


@pytest.mark.unit
def test_within_outside_hours():
    schedule = {"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "18:00"}
    # 19:00 is outside
    assert within(schedule, datetime.datetime(2026, 6, 26, 19, 0)) is False


@pytest.mark.unit
def test_within_weekend():
    schedule = {"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "18:00"}
    # 2026-06-27 is Saturday (isoweekday=6)
    assert within(schedule, datetime.datetime(2026, 6, 27, 12, 0)) is False


@pytest.mark.unit
def test_within_none_schedule_returns_false():
    assert within(None, datetime.datetime(2026, 6, 26, 12, 0)) is False


@pytest.mark.unit
def test_within_empty_schedule_returns_false():
    assert within({}, datetime.datetime(2026, 6, 26, 12, 0)) is False


# ---------------------------------------------------------------------------
# evaluate_condition — within() inside a condition string
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_evaluate_with_within_inside():
    schedule = {"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "18:00"}
    ts = datetime.datetime(2026, 6, 26, 12, 0)  # Friday noon — inside
    context = {"within": within, "schedule": schedule, "ts": ts}
    assert evaluate_condition("within(schedule, ts)", context) is True


@pytest.mark.unit
def test_evaluate_not_within_inside():
    schedule = {"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "18:00"}
    ts = datetime.datetime(2026, 6, 27, 12, 0)  # Saturday — outside
    context = {"within": within, "schedule": schedule, "ts": ts}
    assert evaluate_condition("NOT within(schedule, ts)", context) is True
