"""Safe, deterministic rule condition evaluator.

Replaces the previous ``eval()``-based implementation.

Security rationale
------------------
``eval()`` with ``__builtins__: {}`` is not a sandbox in CPython: class-hierarchy
traversal (``''.__class__.__mro__[1].__subclasses__()``) bypasses it trivially.
This module replaces ``eval()`` with an explicit ``ast.NodeVisitor`` that raises
``ValueError`` for any AST node type not in a strict whitelist.  Only the following
constructs are permitted inside a rule condition:

  * ``Compare``          — e.g. ``kwh > 100``
  * ``BoolOp``           — ``and`` / ``or``
  * ``UnaryOp``          — ``not``
  * ``BinOp``            — ``+``, ``-``, ``*``, ``/``
  * ``Name``             — bare names resolved from the context dict
  * ``Attribute``        — dot-access (``building.occupancy_schedule``)
  * ``Constant``         — numeric / string / bool literals
  * ``Call`` to ``within`` — the only callable permitted by name

Any other node type (``Import``, ``FunctionDef``, ``Lambda``, subscript tricks, …)
raises ``ValueError`` at parse time and the rule evaluates to ``False``.
"""

from __future__ import annotations

import ast
import datetime
import re
from typing import Any

# ---------------------------------------------------------------------------
# Schedule helper (unchanged public API)
# ---------------------------------------------------------------------------


def within(schedule: dict[str, Any] | None, ts: datetime.datetime) -> bool:
    """Return True if *ts* falls within the declared occupancy *schedule*.

    Schedule format::

        {
            "days":  [1, 2, 3, 4, 5],   # ISO weekday: 1 = Mon, 7 = Sun
            "start": "08:00",
            "end":   "18:00",
        }
    """
    if not schedule:
        return False
    try:
        day_of_week = ts.isoweekday()
        if day_of_week not in schedule.get("days", []):
            return False
        start_time = datetime.datetime.strptime(schedule.get("start", "00:00"), "%H:%M").time()
        end_time = datetime.datetime.strptime(schedule.get("end", "23:59"), "%H:%M").time()
        return start_time <= ts.time() <= end_time
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Whitelist AST visitor
# ---------------------------------------------------------------------------

_ALLOWED_OPS = (
    # BoolOp operands
    ast.And,
    ast.Or,
    # UnaryOp operators
    ast.Not,
    # BinOp operators
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.FloorDiv,
    # Compare operators
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
)


class _SafeEvalVisitor(ast.NodeVisitor):
    """Walk an AST and raise ValueError if any disallowed node is encountered."""

    _ALLOWED_NODES = frozenset(
        {
            ast.Expression,
            ast.BoolOp,
            ast.BinOp,
            ast.UnaryOp,
            ast.Compare,
            ast.Name,
            ast.Attribute,
            ast.Constant,
            ast.Call,
            ast.Tuple,
            ast.List,  # needed for ``in (6, 7)`` syntax
            ast.Load,
        }
        | set(_ALLOWED_OPS)
    )

    def generic_visit(self, node: ast.AST) -> None:
        if type(node) not in self._ALLOWED_NODES:
            raise ValueError(
                f"Disallowed AST node '{type(node).__name__}' in rule condition. "
                "Only comparisons, boolean logic, arithmetic, attribute access, "
                "constants, and the within() call are permitted."
            )
        super().generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Only `within(...)` and `.isoweekday()` are allowed as function calls.
        is_within = isinstance(node.func, ast.Name) and node.func.id == "within"
        is_isoweekday = isinstance(node.func, ast.Attribute) and node.func.attr == "isoweekday"
        if not (is_within or is_isoweekday):
            raise ValueError(
                f"Disallowed function call '{ast.dump(node.func)}' in rule condition. "
                "Only within() and .isoweekday() are permitted."
            )
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Context resolver
# ---------------------------------------------------------------------------


class _ContextResolver(ast.NodeVisitor):
    """Evaluate a whitelisted AST against a flat context dict.

    Names are resolved from *context*; attribute access walks nested objects/dicts.
    """

    def __init__(self, context: dict[str, Any]) -> None:
        self._ctx = context

    def eval(self, node: ast.AST) -> Any:  # noqa: A003
        method = "eval_" + type(node).__name__
        handler = getattr(self, method, None)
        if handler is None:
            raise ValueError(f"No eval handler for node type '{type(node).__name__}'")
        return handler(node)

    # -- Leaf nodes ----------------------------------------------------------

    def eval_Constant(self, node: ast.Constant) -> Any:  # noqa: N802
        return node.value

    def eval_Name(self, node: ast.Name) -> Any:  # noqa: N802
        if node.id not in self._ctx:
            raise ValueError(f"Name '{node.id}' not found in evaluation context")
        return self._ctx[node.id]

    def eval_Attribute(self, node: ast.Attribute) -> Any:  # noqa: N802
        obj = self.eval(node.value)
        attr = node.attr
        # Support both dict-like and object-like containers
        if isinstance(obj, dict):
            if attr not in obj:
                raise ValueError(f"Attribute '{attr}' not found in dict context object")
            return obj[attr]
        if hasattr(obj, attr):
            return getattr(obj, attr)
        raise ValueError(f"Attribute '{attr}' not found on object of type {type(obj)}")

    # -- Collection nodes (for `in (6, 7)`) ----------------------------------

    def eval_Tuple(self, node: ast.Tuple) -> tuple[Any, ...]:  # noqa: N802
        return tuple(self.eval(e) for e in node.elts)

    def eval_List(self, node: ast.List) -> list[Any]:  # noqa: N802
        return [self.eval(e) for e in node.elts]

    # -- Operator nodes ------------------------------------------------------

    def eval_BoolOp(self, node: ast.BoolOp) -> bool:  # noqa: N802
        if isinstance(node.op, ast.And):
            return all(self.eval(v) for v in node.values)
        if isinstance(node.op, ast.Or):
            return any(self.eval(v) for v in node.values)
        raise ValueError(f"Unknown BoolOp: {type(node.op).__name__}")

    def eval_UnaryOp(self, node: ast.UnaryOp) -> Any:  # noqa: N802
        if isinstance(node.op, ast.Not):
            return not self.eval(node.operand)
        raise ValueError(f"Unknown UnaryOp: {type(node.op).__name__}")

    def eval_BinOp(self, node: ast.BinOp) -> Any:  # noqa: N802
        left = self.eval(node.left)
        right = self.eval(node.right)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.Mod):
            return left % right
        if isinstance(op, ast.Pow):
            return left**right
        if isinstance(op, ast.FloorDiv):
            return left // right
        raise ValueError(f"Unknown BinOp: {type(op).__name__}")

    def eval_Compare(self, node: ast.Compare) -> bool:  # noqa: N802
        left = self.eval(node.left)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = self.eval(comparator)
            if isinstance(op, ast.Eq):
                result = left == right
            elif isinstance(op, ast.NotEq):
                result = left != right
            elif isinstance(op, ast.Lt):
                result = left < right
            elif isinstance(op, ast.LtE):
                result = left <= right
            elif isinstance(op, ast.Gt):
                result = left > right
            elif isinstance(op, ast.GtE):
                result = left >= right
            elif isinstance(op, ast.In):
                result = left in right
            elif isinstance(op, ast.NotIn):
                result = left not in right
            else:
                raise ValueError(f"Unknown comparison op: {type(op).__name__}")
            if not result:
                return False
            left = right
        return True

    def eval_Call(self, node: ast.Call) -> Any:  # noqa: N802
        if isinstance(node.func, ast.Name) and node.func.id == "within":
            args = [self.eval(a) for a in node.args]
            return within(*args)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "isoweekday":
            obj = self.eval(node.func.value)
            return obj.isoweekday()
        raise ValueError(f"Disallowed function call: {ast.dump(node)}")

    def eval_Expression(self, node: ast.Expression) -> Any:  # noqa: N802
        return self.eval(node.body)


# ---------------------------------------------------------------------------
# Public API (unchanged from previous implementation)
# ---------------------------------------------------------------------------


def _normalize_condition(condition: str) -> str:
    """Convert SQL-style boolean operators to Python keywords.

    E.g. ``AND`` → ``and``, ``OR`` → ``or``, ``NOT`` → ``not``.
    """
    condition = re.sub(r"\bAND\b", "and", condition)
    condition = re.sub(r"\bOR\b", "or", condition)
    condition = re.sub(r"\bNOT\b", "not", condition)
    return condition


def evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
    """Evaluate a rule *condition* string against *context* without using ``eval()``.

    Returns ``True`` if the condition is satisfied, ``False`` otherwise (including
    on any parse or evaluation error).

    The *context* dict must contain all names referenced in the condition.  Dot
    notation (``building.occupancy_schedule``) is resolved by walking nested dicts
    or object attributes.  The helper ``within(schedule, ts)`` is the only callable
    permitted inside a condition.

    Raises nothing — errors are caught and return ``False`` so a broken rule never
    crashes the pipeline.  Callers should log errors separately.
    """
    normalized = _normalize_condition(condition.strip())

    # Step 1: Parse.
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError:
        return False

    # Step 2: Whitelist check — raises ValueError for any disallowed node.
    try:
        _SafeEvalVisitor().visit(tree)
    except ValueError:
        return False

    # Step 3: Evaluate against context.
    try:
        resolver = _ContextResolver(context)
        result = resolver.eval(tree)
        return bool(result)
    except Exception:  # noqa: BLE001
        return False
