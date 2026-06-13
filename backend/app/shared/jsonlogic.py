"""Pure JsonLogic-Subset-Evaluator (data-model §5.1, flows §9.2).

`visibleIf`/`compute` in Form-Feldern nutzen dieses Subset. **Kein `eval`/`exec`** —
deklarativer Baum, Whitelist-Operatoren. Unbekannter Operator → `JsonLogicError`
(nicht still ignoriert), damit Fehler beim Speichern auffallen, nicht zur Laufzeit.

Ausdruck:
- Literal (kein Dict): wird unverändert zurückgegeben (Zahl/String/Bool/None/Liste).
- Operation: Dict mit **genau einem** Schlüssel = Operator, Wert = Argument(e).

Whitelist: ``== != > >= < <= and or not var + - * / in`` — als deklarative
Operator→Funktions-Tabelle (:data:`_EVALUATORS`), aus der sich auch die
Whitelist :data:`JSONLOGIC_OPERATORS` ableitet (eine Quelle der Wahrheit).
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Any

# Maximale Verschachtelungstiefe eines Ausdrucks. Schützt Eval **und** Validierung
# vor `RecursionError` (= 500 / Worker-Crash) bei tief verschachtelten Eingaben;
# weit jenseits jedes realen `visibleIf`/`compute`.
_MAX_DEPTH = 64


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


def _arity(op: str, n: int) -> Callable[[Callable[[list[Any]], Any]], Callable[[list[Any]], Any]]:
    """Decorator: erzwingt genau ``n`` Operanden, sonst ``JsonLogicError``."""

    def wrap(fn: Callable[[list[Any]], Any]) -> Callable[[list[Any]], Any]:
        def run(args: list[Any]) -> Any:
            if len(args) != n:
                raise JsonLogicError(f"'{op}' requires exactly {n} operands")
            return fn(args)

        return run

    return wrap


def _compare(op: Callable[[float, float], bool]) -> Callable[[list[Any]], bool]:
    """Numerischer 2-stelliger Vergleich über :func:`_num`-koerzierte Operanden."""

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


# Operator → reine Auswertungsfunktion über die **bereits ausgewerteten** Argumente.
# ``var`` ist nicht hier (löst einen Pfad statt Argumente auszuwerten); ``and``/``or``
# werten NICHT kurzschließend aus (T-05: alle Operanden werden vorab evaluiert).
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

# Whitelist der erlaubten Operatoren (Eval + Validierung), abgeleitet aus der
# Dispatch-Tabelle + dem Sonderfall ``var`` — eine Quelle der Wahrheit.
JSONLOGIC_OPERATORS: frozenset[str] = frozenset(_EVALUATORS) | {"var"}


def eval_jsonlogic(expr: Any, ctx: dict[str, Any] | None = None, *, _depth: int = 0) -> Any:
    """Ausdruck gegen `ctx` auswerten. Pure, kein Seiteneffekt, kein `eval`."""
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
    """Statisch prüfen, dass nur Whitelist-Operatoren vorkommen (Speicher-Gate).

    Wirft `JsonLogicError` beim ersten unbekannten Operator / strukturellen Fehler /
    bei Überschreiten der maximalen Verschachtelungstiefe.
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
