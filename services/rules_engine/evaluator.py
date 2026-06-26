import datetime
import re
from typing import Any


def within(schedule: dict | None, ts: datetime.datetime) -> bool:
    """
    Evaluates if a given timestamp `ts` is within the declared occupancy `schedule`.
    Schedule format assumed:
    {
        "days": [1, 2, 3, 4, 5], # 1 = Monday, 7 = Sunday
        "start": "08:00",
        "end": "18:00"
    }
    """
    if not schedule:
        return False
        
    try:
        # iso weekday: 1 = Mon, 7 = Sun
        day_of_week = ts.isoweekday()
        if day_of_week not in schedule.get("days", []):
            return False
            
        start_time_str = schedule.get("start", "00:00")
        end_time_str = schedule.get("end", "23:59")
        
        start_time = datetime.datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.datetime.strptime(end_time_str, "%H:%M").time()
        
        ts_time = ts.time()
        return start_time <= ts_time <= end_time
    except Exception:
        return False


def _normalize_condition(condition: str) -> str:
    """
    Converts SQL-like / YAML-like boolean operators to Python operators.
    E.g. 'AND' -> 'and', 'OR' -> 'or', 'NOT' -> 'not'
    """
    # Replace whole words only
    condition = re.sub(r'\bAND\b', 'and', condition)
    condition = re.sub(r'\bOR\b', 'or', condition)
    condition = re.sub(r'\bNOT\b', 'not', condition)
    return condition


def evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
    """
    Evaluates a condition string safely with the given context.
    """
    normalized = _normalize_condition(condition)
    
    # Inject the helper functions into the context
    eval_context = {
        "within": within,
        "__builtins__": {}
    }
    eval_context.update(context)
    
    try:
        # safe eval using restricted globals/locals
        result = eval(normalized, eval_context)
        return bool(result)
    except Exception:
        # In production, we'd log this. For now, a failing rule returns False.
        return False
