"""Reine Form-Engine (T-11) — keine DB, keine HTTP-Abhängigkeit.

Drei Kernfunktionen (Akzeptanzkriterien T-11):

* :func:`validate_definition` — eine Form-Definition (Liste ``FormFieldDef``)
  strukturell gegen das Config-Schema prüfen (eindeutige Keys, promoted-Felder
  numerisch). Pro-Feld-Schema ist bereits durch ``FormFieldDef`` (T-05) gesichert.
* :func:`effective_form` — Typ-Felder + Topf-Extra-Felder zu sektionierten
  Abschnitten mergen (data-model §5.7). Die Topf-Sektion erscheint nur, wenn der
  Antrag einem Topf zugeordnet ist.
* :func:`validate_answers` — Antwortdaten gegen alle Feldtypen validieren
  (required, ``visibleIf`` → sichtbar⇒Pflicht, ``compute`` → abgeleitete Felder).
  Sammelt **alle** Feldfehler (kein Fail-Fast) → ``AnswerValidationError``.

`visibleIf`/`compute` nutzen den JsonLogic-Subset-Evaluator aus T-05. **Hinweis
(T-05):** dessen ``and``/``or`` werten *nicht* kurzschließend aus — alle Operanden
werden evaluiert. Ein ``visibleIf`` wie ``{"and":[{"var":"x"},{">":[{"var":"y"},0]}]}``
kann daher bei fehlendem ``y`` einen ``JsonLogicError`` werfen, statt auf ``x``
abzubrechen. Bei der Sichtbarkeits-Auswertung wird ein solcher Fehler **konservativ
als sichtbar** behandelt (Feld wird validiert statt still übersprungen), siehe
:func:`_is_visible`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.shared.config_schemas import FormFieldDef
from app.shared.jsonlogic import JsonLogicError, eval_jsonlogic, validate_jsonlogic

# Feldtypen, deren Wert numerisch ist (für promoted-Extraktion + min/max).
_NUMERIC_TYPES = frozenset({"number", "currency"})
_TEXT_TYPES = frozenset({"text", "textarea", "markdown"})


class FormDefinitionError(Exception):
    """Form-Definition verletzt eine Struktur-Regel (Speicher-Gate, T-11)."""


@dataclass(frozen=True)
class FieldError:
    """Ein Validierungsfehler für ein konkretes Antwortfeld (api.md §2 ``errors[]``)."""

    field: str
    msg: str


class AnswerValidationError(Exception):
    """Antwortdaten sind ungültig; trägt alle gesammelten Feldfehler (→ 422)."""

    def __init__(self, errors: Sequence[FieldError]) -> None:
        self.errors: list[FieldError] = list(errors)
        super().__init__(f"{len(self.errors)} field error(s)")


@dataclass(frozen=True)
class FormSection:
    """Ein Abschnitt der effektiven Form (``main`` = Typ, ``budget`` = Topf-Extra)."""

    key: str
    fields: list[FormFieldDef]


# --------------------------------------------------------------------------- #
# validate_definition
# --------------------------------------------------------------------------- #
def validate_definition(fields: Sequence[FormFieldDef]) -> None:
    """Form-Definition strukturell prüfen. Wirft ``FormDefinitionError``.

    Regeln: keine doppelten Feld-Keys; promoted-Felder müssen numerisch sein
    (``number``/``currency``), da das Ziel (z. B. ``amount``) ``numeric`` ist;
    ``visibleIf``/``compute`` nur mit Whitelist-Operatoren (T-05); ein gesetztes
    ``pattern`` muss eine kompilierbare Regex sein (sonst 500 zur Antwort-Laufzeit).
    """
    keys = [f.key for f in fields]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        raise FormDefinitionError(f"duplicate field keys: {duplicates}")

    for f in fields:
        if f.is_promoted and f.type not in _NUMERIC_TYPES:
            raise FormDefinitionError(
                f"promoted field {f.key!r} must be numeric (number/currency), got {f.type!r}"
            )
        for expr in (f.visible_if, f.compute):
            if expr is not None:
                try:
                    validate_jsonlogic(expr)
                except JsonLogicError as exc:
                    raise FormDefinitionError(
                        f"field {f.key!r} has an invalid expression: {exc}"
                    ) from exc
        if f.validation is not None and f.validation.pattern is not None:
            try:
                re.compile(f.validation.pattern)
            except re.error as exc:
                raise FormDefinitionError(
                    f"field {f.key!r} has an invalid validation pattern: {exc}"
                ) from exc


# --------------------------------------------------------------------------- #
# effective_form
# --------------------------------------------------------------------------- #
def effective_form(
    type_fields: Sequence[FormFieldDef],
    pot_fields: Sequence[FormFieldDef] | None = None,
) -> list[FormSection]:
    """Typ-Felder + Topf-Extra-Felder zu Abschnitten mergen (data-model §5.7).

    ``main`` enthält immer die Typ-Felder. ``budget`` erscheint **nur**, wenn
    ``pot_fields`` zugeordnet und nicht leer sind (Topf-Zuordnung).
    """
    sections = [FormSection(key="main", fields=list(type_fields))]
    if pot_fields:
        sections.append(FormSection(key="budget", fields=list(pot_fields)))
    return sections


# --------------------------------------------------------------------------- #
# validate_answers
# --------------------------------------------------------------------------- #
def validate_answers(
    fields: Sequence[FormFieldDef],
    data: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Antwortdaten validieren + abgeleitete (``computed``) Felder berechnen.

    ``context`` liefert Nicht-Feld-Variablen für ``visibleIf`` (z. B.
    ``has_budget``). Rückgabe = ``data`` plus berechnete ``computed``-Werte.
    Bei Fehlern → ``AnswerValidationError`` (alle Fehler gesammelt).
    """
    errors: list[FieldError] = []
    result: dict[str, Any] = dict(data)

    # 1. computed-Felder berechnen (in Feld-Reihenfolge; dürfen andere Felder nutzen).
    base_ctx: dict[str, Any] = {**(context or {}), **result}
    for f in fields:
        if f.type == "computed" and f.compute is not None:
            try:
                result[f.key] = eval_jsonlogic(f.compute, base_ctx)
                base_ctx[f.key] = result[f.key]
            except JsonLogicError as exc:
                errors.append(FieldError(field=f.key, msg=f"compute failed: {exc}"))

    eval_ctx: dict[str, Any] = {**(context or {}), **result}

    # 2. Pro-Feld: Sichtbarkeit → required → Typ-Validierung.
    for f in fields:
        if f.type == "computed":
            continue  # abgeleitet, nicht vom Antragsteller geliefert
        if not _is_visible(f, eval_ctx):
            continue
        value = data.get(f.key)
        if not _is_present(value):
            if f.required:
                errors.append(FieldError(field=f.key, msg="required"))
            continue
        _validate_value(f, value, errors)

    if errors:
        raise AnswerValidationError(errors)
    return result


def _is_present(value: Any) -> bool:
    """Wert gilt als vorhanden, wenn nicht ``None`` und nicht leer (String/Liste)."""
    if value is None:
        return False
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return True


def _is_visible(field: FormFieldDef, ctx: Mapping[str, Any]) -> bool:
    """``visibleIf`` auswerten. Kein Ausdruck ⇒ sichtbar. Eval-Fehler ⇒ konservativ
    sichtbar (T-05 ``and``/``or`` ohne Kurzschluss → Feld wird validiert, nicht still
    übersprungen)."""
    if field.visible_if is None:
        return True
    try:
        return bool(eval_jsonlogic(field.visible_if, dict(ctx)))
    except JsonLogicError:
        return True


# --------------------------------------------------------------------------- #
# Typ-Validierung pro Feld
# --------------------------------------------------------------------------- #
def _validate_value(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    """Einen vorhandenen Wert gegen seinen Feldtyp prüfen; Fehler anhängen."""
    t = field.type
    if t in _TEXT_TYPES:
        _validate_text(field, value, errors)
    elif t == "number" or t == "currency":
        _validate_number(field, value, errors)
    elif t == "date":
        _validate_date(field, value, errors)
    elif t == "select":
        _validate_select(field, value, errors)
    elif t == "multiselect":
        _validate_multiselect(field, value, errors)
    elif t == "checkbox":
        _validate_checkbox(field, value, errors)
    elif t == "file":
        _validate_file(field, value, errors)
    elif t == "table":
        _validate_table(field, value, errors)
    else:  # pragma: no cover via FormFieldDef.type (Literal) — defensiv geprüft im Test
        errors.append(FieldError(field=field.key, msg=f"unknown field type: {t!r}"))


def _err(errors: list[FieldError], key: str, msg: str) -> None:
    errors.append(FieldError(field=key, msg=msg))


def _validate_text(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    if not isinstance(value, str):
        _err(errors, field.key, "must be a string")
        return
    v = field.validation
    if v is None:
        return
    if v.min_len is not None and len(value) < v.min_len:
        _err(errors, field.key, f"shorter than minimum length {v.min_len}")
    if v.max_len is not None and len(value) > v.max_len:
        _err(errors, field.key, f"longer than maximum length {v.max_len}")
    if v.pattern is not None:
        try:
            matched = re.fullmatch(v.pattern, value) is not None
        except re.error:
            # Defekt gespeichertes Pattern: defense-in-depth (validate_definition
            # lehnt das schon beim Anlegen ab) — niemals 500 zur Laufzeit.
            _err(errors, field.key, "field has an invalid validation pattern")
            return
        if not matched:
            _err(errors, field.key, "does not match required pattern")


def _validate_number(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        _err(errors, field.key, "must be a number")
        return
    try:
        num = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _err(errors, field.key, "must be a number")
        return
    if not num.is_finite():
        # NaN/Infinity (z. B. JSON "NaN"/Infinity): Vergleich mit min/max würde
        # decimal.InvalidOperation werfen → 422 statt 500.
        _err(errors, field.key, "must be a finite number")
        return
    v = field.validation
    if v is None:
        return
    if v.min is not None and num < Decimal(str(v.min)):
        _err(errors, field.key, f"less than minimum {v.min}")
    if v.max is not None and num > Decimal(str(v.max)):
        _err(errors, field.key, f"greater than maximum {v.max}")


def _validate_date(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    if not isinstance(value, str):
        _err(errors, field.key, "must be an ISO date string")
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        _err(errors, field.key, "must be an ISO date (YYYY-MM-DD)")


def _option_values(field: FormFieldDef) -> set[str]:
    return {o.value for o in field.options or []}


def _validate_select(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    if value not in _option_values(field):
        _err(errors, field.key, "is not a valid option")


def _validate_multiselect(
    field: FormFieldDef, value: Any, errors: list[FieldError]
) -> None:
    if not isinstance(value, list):
        _err(errors, field.key, "must be a list")
        return
    allowed = _option_values(field)
    invalid = [v for v in value if v not in allowed]
    if invalid:
        _err(errors, field.key, f"contains invalid options: {invalid}")


def _validate_checkbox(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    if not isinstance(value, bool):
        _err(errors, field.key, "must be a boolean")


def _validate_file(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    # Antwortwert = Attachment-Referenz(en); Inhalt/Größe/MIME prüft der Upload.
    if isinstance(value, str):
        return
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return
    _err(errors, field.key, "must be an attachment reference (string or list of strings)")


def _validate_table(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    if not isinstance(value, list):
        _err(errors, field.key, "must be a list of rows")
        return
    v = field.validation
    if v is not None and v.max_rows is not None and len(value) > v.max_rows:
        _err(errors, field.key, f"has more than {v.max_rows} rows")
    for i, row in enumerate(value):
        if not isinstance(row, dict):
            _err(errors, field.key, f"row {i} must be an object")


# --------------------------------------------------------------------------- #
# Promoted-Extraktion (für T-12/T-17)
# --------------------------------------------------------------------------- #
def extract_promoted(
    fields: Sequence[FormFieldDef], data: Mapping[str, Any]
) -> dict[str, Any]:
    """Promoted-Feldwerte aus ``data`` ziehen → ``{promote_target: value}``.

    Numerische Promoted-Felder (``amount``) werden zu ``Decimal`` normalisiert.
    """
    out: dict[str, Any] = {}
    for f in fields:
        if not (f.is_promoted and f.promote_target):
            continue
        value = data.get(f.key)
        if value is None:
            continue
        if f.type in _NUMERIC_TYPES:
            try:
                num = Decimal(str(value))
            except (InvalidOperation, ValueError):
                continue
            # NaN/Infinity nie als amount weiterreichen (kracht sonst in T-12/T-17).
            if not num.is_finite():
                continue
            out[f.promote_target] = num
        else:
            out[f.promote_target] = value
    return out
