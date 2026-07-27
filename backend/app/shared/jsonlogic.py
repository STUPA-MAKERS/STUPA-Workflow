"""Pure evaluator for the JsonLogic subset behind form `visibleIf` and `compute`.

The module never calls `eval` or `exec`. It walks a declarative tree of whitelisted
operators. An unknown operator raises `JsonLogicError`. The module never ignores such an
operator, so an error shows at save time and not at runtime.

Expression forms:
- A literal is any value that is not a dict, such as a number, string, bool, `None` or
  list. The evaluator returns it unchanged.
- An operation is a dict with exactly one key. The key is the operator and the value
  holds the arguments.

The whitelist `JSONLOGIC_OPERATORS` derives from the `_EVALUATORS` dispatch table plus
`var`. That keeps a single source of truth.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Any

# Maximum nesting depth of an expression. It protects the evaluator and the validator
# against a RecursionError on deeply nested input. The limit sits far above any real
# visibleIf or compute expression.
_MAX_DEPTH = 64


class JsonLogicError(Exception):
    """Invalid JsonLogic expression (unknown operator, wrong arity, ...)."""


def _as_args(value: Any) -> list[Any]:
    """Normalize operator arguments to a list (JsonLogic allows a scalar shorthand)."""
    return value if isinstance(value, list) else [value]


def _resolve_var(path: Any, ctx: dict[str, Any]) -> Any:
    """Resolve the `var` operator: a dotted path in `ctx`.

    The form `[path, default]` sets the fallback. A path that does not resolve returns
    that fallback, which is `None` when the caller gives none.
    """
    default: Any = None
    if isinstance(path, list):
        default = path[1] if len(path) > 1 else None
        path = path[0] if path else ""
    if path == "" or path is None:
        return ctx
    if not isinstance(path, str):
        raise JsonLogicError(f"var path must be a string, got {type(path).__name__}")
    current: Any = ctx
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return default
    return current


def _num(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JsonLogicError(f"expected a number, got {value!r}")
    return float(value)


def _arity(op: str, n: int) -> Callable[[Callable[[list[Any]], Any]], Callable[[list[Any]], Any]]:
    """Build a decorator that requires exactly `n` operands.

    The wrapped function raises `JsonLogicError` for any other operand count.
    """

    def wrap(fn: Callable[[list[Any]], Any]) -> Callable[[list[Any]], Any]:
        def run(args: list[Any]) -> Any:
            if len(args) != n:
                raise JsonLogicError(f"'{op}' requires exactly {n} operands")
            return fn(args)

        return run

    return wrap


def _compare(op: Callable[[float, float], bool]) -> Callable[[list[Any]], bool]:
    """Build a binary comparison over two operands that `_num` coerces to numbers."""

    def run(args: list[Any]) -> bool:
        if len(args) != 2:
            raise JsonLogicError("comparison requires exactly 2 operands")
        return op(_num(args[0]), _num(args[1]))

    return run


def _eval_subtract(args: list[Any]) -> float:
    if len(args) == 1:
        return -_num(args[0])
    if len(args) == 2:
        return _num(args[0]) - _num(args[1])
    raise JsonLogicError("'-' requires 1 (negate) or 2 operands")


def _eval_divide(args: list[Any]) -> float:
    if len(args) != 2:
        raise JsonLogicError("'/' requires exactly 2 operands")
    divisor = _num(args[1])
    if divisor == 0:
        raise JsonLogicError("division by zero")
    return _num(args[0]) / divisor


def _eval_in(args: list[Any]) -> bool:
    if len(args) != 2:
        raise JsonLogicError("'in' requires exactly 2 operands")
    needle, haystack = args[0], args[1]
    if isinstance(haystack, (list, str)):
        return needle in haystack
    raise JsonLogicError("'in' second operand must be a list or string")


def _eval_add(args: list[Any]) -> float:
    if not args:
        raise JsonLogicError("'+' requires at least 1 operand")
    return sum(_num(a) for a in args)


def _eval_multiply(args: list[Any]) -> float:
    if not args:
        raise JsonLogicError("'*' requires at least 1 operand")
    product = 1.0
    for a in args:
        product *= _num(a)
    return product


# Map an operator to a pure function over the already evaluated arguments. `var` is not
# here, because it resolves a path. `and` and `or` do not short-circuit. The evaluator
# evaluates every operand first.
_EVALUATORS: dict[str, Callable[[list[Any]], Any]] = {
    "==": _arity("==", 2)(lambda a: a[0] == a[1]),
    "!=": _arity("!=", 2)(lambda a: a[0] != a[1]),
    ">": _compare(operator.gt),
    ">=": _compare(operator.ge),
    "<": _compare(operator.lt),
    "<=": _compare(operator.le),
    "and": lambda a: all(bool(x) for x in a),
    "or": lambda a: any(bool(x) for x in a),
    "not": _arity("not", 1)(lambda a: not bool(a[0])),
    "+": _eval_add,
    "-": _eval_subtract,
    "*": _eval_multiply,
    "/": _eval_divide,
    "in": _eval_in,
}

# The whitelist that both the evaluator and the validator use.
JSONLOGIC_OPERATORS: frozenset[str] = frozenset(_EVALUATORS) | {"var"}


def eval_jsonlogic(expr: Any, ctx: dict[str, Any] | None = None, *, _depth: int = 0) -> Any:
    """Evaluate `expr` against `ctx`.

    The function is pure. It has no side effect and never calls `eval`.

    Raises:
        JsonLogicError: The expression uses an unknown operator, has a wrong structure,
            or nests deeper than the limit.
    """
    ctx = ctx or {}
    if not isinstance(expr, dict):
        return expr
    if _depth >= _MAX_DEPTH:
        raise JsonLogicError(f"expression nested too deeply (>{_MAX_DEPTH})")
    if len(expr) != 1:
        raise JsonLogicError(f"operation must have exactly one operator, got {list(expr)}")
    op, raw = next(iter(expr.items()))
    if op == "var":
        return _resolve_var(raw, ctx)
    evaluator = _EVALUATORS.get(op)
    if evaluator is None:
        raise JsonLogicError(f"unknown operator: {op!r}")
    args = [eval_jsonlogic(a, ctx, _depth=_depth + 1) for a in _as_args(raw)]
    return evaluator(args)


def validate_jsonlogic(expr: Any, *, _depth: int = 0) -> None:
    """Check that the expression uses only whitelisted operators.

    This is the save-time gate. It stops at the first error.

    Raises:
        JsonLogicError: The expression uses an unknown operator, has a wrong structure,
            or nests deeper than the limit.
    """
    if not isinstance(expr, dict):
        return
    if _depth >= _MAX_DEPTH:
        raise JsonLogicError(f"expression nested too deeply (>{_MAX_DEPTH})")
    if len(expr) != 1:
        raise JsonLogicError(f"operation must have exactly one operator, got {list(expr)}")
    op, raw = next(iter(expr.items()))
    if op not in JSONLOGIC_OPERATORS:
        raise JsonLogicError(f"unknown operator: {op!r}")
    if op == "var":
        return
    for arg in _as_args(raw):
        validate_jsonlogic(arg, _depth=_depth + 1)
