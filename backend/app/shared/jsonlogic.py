"""Pure JsonLogic-Subset-Evaluator (data-model §5.1, flows §9.2).

`visibleIf`/`compute` in Form-Feldern nutzen dieses Subset. **Kein `eval`/`exec`** —
deklarativer Baum, Whitelist-Operatoren. Unbekannter Operator → `JsonLogicError`
(nicht still ignoriert), damit Fehler beim Speichern auffallen, nicht zur Laufzeit.

Ausdruck:
- Literal (kein Dict): wird unverändert zurückgegeben (Zahl/String/Bool/None/Liste).
- Operation: Dict mit **genau einem** Schlüssel = Operator, Wert = Argument(e).

Whitelist: ``== != > >= < <= and or not var + - * / in``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Whitelist der erlaubten Operatoren (für Eval + Validierung beim Speichern).
JSONLOGIC_OPERATORS: frozenset[str] = frozenset(
    {"==", "!=", ">", ">=", "<", "<=", "and", "or", "not", "var", "+", "-", "*", "/", "in"}
)


class JsonLogicError(Exception):
    """Ungültiger JsonLogic-Ausdruck (unbekannter Operator, falsche Arität, …)."""


def _as_args(value: Any) -> list[Any]:
    """Operator-Argumente immer als Liste (JsonLogic erlaubt Skalar-Kurzform)."""
    return value if isinstance(value, list) else [value]


def _resolve_var(path: Any, ctx: dict[str, Any]) -> Any:
    """`var`: Punkt-Pfad in `ctx` auflösen; `[pfad, default]` oder fehlend → default."""
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


def _binary_compare(op: Callable[[float, float], bool]) -> Callable[[list[Any]], bool]:
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


def eval_jsonlogic(expr: Any, ctx: dict[str, Any] | None = None) -> Any:
    """Ausdruck gegen `ctx` auswerten. Pure, kein Seiteneffekt, kein `eval`."""
    ctx = ctx or {}
    if not isinstance(expr, dict):
        return expr
    if len(expr) != 1:
        raise JsonLogicError(f"operation must have exactly one operator, got {list(expr)}")
    op, raw = next(iter(expr.items()))
    if op not in JSONLOGIC_OPERATORS:
        raise JsonLogicError(f"unknown operator: {op!r}")

    if op == "var":
        return _resolve_var(raw, ctx)

    args = [eval_jsonlogic(a, ctx) for a in _as_args(raw)]

    if op == "==":
        return args[0] == args[1] if len(args) == 2 else _arity_err("==")
    if op == "!=":
        return args[0] != args[1] if len(args) == 2 else _arity_err("!=")
    if op == ">":
        return _binary_compare(lambda a, b: a > b)(args)
    if op == ">=":
        return _binary_compare(lambda a, b: a >= b)(args)
    if op == "<":
        return _binary_compare(lambda a, b: a < b)(args)
    if op == "<=":
        return _binary_compare(lambda a, b: a <= b)(args)
    if op == "and":
        return all(bool(a) for a in args)
    if op == "or":
        return any(bool(a) for a in args)
    if op == "not":
        if len(args) != 1:
            raise JsonLogicError("'not' requires exactly 1 operand")
        return not bool(args[0])
    if op == "+":
        if not args:
            raise JsonLogicError("'+' requires at least 1 operand")
        return sum(_num(a) for a in args)
    if op == "*":
        if not args:
            raise JsonLogicError("'*' requires at least 1 operand")
        product = 1.0
        for a in args:
            product *= _num(a)
        return product
    if op == "-":
        return _eval_subtract(args)
    if op == "/":
        return _eval_divide(args)
    if op == "in":
        return _eval_in(args)
    raise JsonLogicError(f"unhandled operator: {op!r}")  # pragma: no cover


def _arity_err(op: str) -> Any:
    raise JsonLogicError(f"'{op}' requires exactly 2 operands")


def validate_jsonlogic(expr: Any) -> None:
    """Statisch prüfen, dass nur Whitelist-Operatoren vorkommen (Speicher-Gate).

    Wirft `JsonLogicError` beim ersten unbekannten Operator / strukturellen Fehler.
    """
    if not isinstance(expr, dict):
        return
    if len(expr) != 1:
        raise JsonLogicError(f"operation must have exactly one operator, got {list(expr)}")
    op, raw = next(iter(expr.items()))
    if op not in JSONLOGIC_OPERATORS:
        raise JsonLogicError(f"unknown operator: {op!r}")
    if op == "var":
        return
    for arg in _as_args(raw):
        validate_jsonlogic(arg)
