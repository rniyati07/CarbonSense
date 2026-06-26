import datetime
from services.rules_engine.evaluator import evaluate_condition, _normalize_condition, within

def test_normalize_condition():
    assert _normalize_condition("A AND B") == "A and B"
    assert _normalize_condition("NOT A OR B") == "not A or B"

def test_evaluate_condition():
    context = {
        "kwh": 100,
        "building": type("Obj", (), {"declared_unoccupied_baseline": 50})
    }
    # 100 > 50 * 1.4 -> 100 > 70 -> True
    assert evaluate_condition("kwh > building.declared_unoccupied_baseline * 1.4", context) is True

def test_within():
    schedule = {
        "days": [1, 2, 3, 4, 5],
        "start": "08:00",
        "end": "18:00"
    }
    
    # 2026-06-26 is a Friday
    dt_in = datetime.datetime(2026, 6, 26, 12, 0)
    assert within(schedule, dt_in) is True
    
    dt_out = datetime.datetime(2026, 6, 26, 19, 0)
    assert within(schedule, dt_out) is False
    
    # 2026-06-27 is a Saturday
    dt_weekend = datetime.datetime(2026, 6, 27, 12, 0)
    assert within(schedule, dt_weekend) is False
