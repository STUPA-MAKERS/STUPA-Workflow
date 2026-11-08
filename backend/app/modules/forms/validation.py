"""Pure form engine. It has no DB and no HTTP dependency.

Three core functions:

* `validate_definition` — check the structure of a form definition against the config
  schema. It rejects duplicate keys and non-numeric promoted fields. ``FormFieldDef``
  already guarantees the schema of a single field.
* `effective_form` — merge the type fields and the pot extra fields into sections. The
  pot section appears only when the application has a pot.
* `validate_answers` — validate the answer data against every field type. It applies
  ``required``, resolves ``visibleIf`` (a visible field stays required) and computes the
  ``compute`` fields. It collects all field errors and does not fail fast. It then raises
  ``AnswerValidationError``.

``visibleIf`` and ``compute`` use the JsonLogic-subset evaluator. Its ``and`` and ``or``
do not short-circuit, so the evaluator reads every operand. A ``visibleIf`` such as
``{"and":[{"var":"x"},{">":[{"var":"y"},0]}]}`` can therefore raise a ``JsonLogicError``
for a missing ``y`` instead of stopping at ``x``. During a visibility check the engine
treats such an error conservatively as visible. It validates the field instead of skipping
it. See `_is_visible`.

``validation.pattern`` is a raw regex from an admin, and it runs against applicant
input. An expression with catastrophic backtracking would block the single-replica event
loop. Two independent bounds stop this:

1. A hard input length cap (`_PATTERN_MAX_INPUT_LEN`) bounds the worst case at all
   times. It holds even when the timeout cannot kill the match. A longer value counts
   as "no match".
2. A wall-clock timeout in a worker thread. If the match does not finish inside the
   budget, the event loop gets control back and marks the field invalid. Nothing can
   hard-kill the thread, so the length cap makes it stop after a bounded time.

The engine caps (`_DEFAULT_MAX_POSITIONS`, `_DEFAULT_MAX_OFFERS`, `_DEFAULT_MAX_ROWS`)
bound positions, offers and table rows. They apply even without a builder value and do
not depend on the body cap. They stop a raised body cap or an authenticated write path
from pushing unbounded positions or offers through `_validate_positions`,
`positions_total` and the JSONB persistence. The engine clamps a configured value to the
cap, because an admin with ``form.configure`` can set a value above it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import reduce
from typing import Any
from uuid import UUID

from app.shared.config_schemas import FieldValidation, FormFieldDef
from app.shared.jsonlogic import JsonLogicError, eval_jsonlogic, validate_jsonlogic

#: Field types with a numeric value, used by the promoted extraction and by min and max.
_NUMERIC_TYPES = frozenset({"number", "currency"})

_PATTERN_MAX_INPUT_LEN = 4096
_PATTERN_MATCH_TIMEOUT_SECONDS = 1.0
#: One small shared executor. Pattern matches are rare and short.
_PATTERN_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="form-regex")


class _PatternMatchError(Exception):
    """The pattern match failed because of a broken regex or a timeout."""


def _pattern_matches(pattern: str, value: str) -> bool:
    """Run ``re.fullmatch`` on ``value`` with a length bound and a timeout (ReDoS).

    A value longer than `_PATTERN_MAX_INPUT_LEN` always counts as "no match". The
    function makes no match attempt for it.

    After a timeout the thread keeps running, bounded by the length cap. The caller gets
    control back at once.

    Raises:
        _PatternMatchError: The pattern is broken, or the match timed out. The caller
            then marks the field invalid.
    """
    if len(value) > _PATTERN_MAX_INPUT_LEN:
        return False
    future = _PATTERN_EXECUTOR.submit(_full_match, pattern, value)
    try:
        return future.result(timeout=_PATTERN_MATCH_TIMEOUT_SECONDS)
    except FutureTimeout as exc:
        raise _PatternMatchError("pattern match timed out") from exc
    except re.error as exc:
        raise _PatternMatchError("invalid pattern") from exc


def _full_match(pattern: str, value: str) -> bool:
    return re.fullmatch(pattern, value) is not None


#: Reserved key of the system title field. Every application MUST have a title. The server
#: prepends the field to every effective form. The builder cannot edit it.
SYSTEM_TITLE_KEY = "title"


def system_title_field() -> FormFieldDef:
    """Return the required title field that the server prepends to every form."""
    return FormFieldDef.model_validate(
        {
            "key": SYSTEM_TITLE_KEY,
            "type": "text",
            "label": {"de": "Titel", "en": "Title"},
            "required": True,
        }
    )


class FormDefinitionError(Exception):
    """The form definition breaks a structural rule at the save gate."""


@dataclass(frozen=True, slots=True)
class FieldError:
    """A validation error for a concrete answer field."""

    field: str
    msg: str


class AnswerValidationError(Exception):
    """The answer data is invalid.

    The exception carries every collected field error and maps to a 422 response.
    """

    def __init__(self, errors: Sequence[FieldError]) -> None:
        """Store the field errors."""
        self.errors: list[FieldError] = list(errors)
        super().__init__(f"{len(self.errors)} field error(s)")


@dataclass(frozen=True, slots=True)
class FormSection:
    """A section of the effective form.

    ``main`` holds the type fields. ``budget`` holds the pot extra fields. ``label`` is
    set when the section comes from a ``section`` marker in a multi-step form. Otherwise
    it is ``None`` and the service resolves the default ``main`` or ``budget`` label.
    """

    key: str
    fields: list[FormFieldDef]
    label: dict[str, str] | None = None


def validate_definition(fields: Sequence[FormFieldDef]) -> None:
    """Check the structure of a form definition.

    The definition must have unique field keys. A promoted field must be numeric
    (``number`` or ``currency``), because the promote target such as ``amount`` is a
    numeric column. ``visibleIf`` and ``compute`` may use whitelist operators only. A
    ``pattern`` must compile as a regex, because a broken pattern fails at answer runtime
    with a 500. A form has at most one ``funding`` field, and only beside a ``positions``
    field, because the funding is checked against the cost total and replaces it as the
    amount.

    Raises:
        FormDefinitionError: The definition breaks one of these rules.
    """
    keys = [f.key for f in fields]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        raise FormDefinitionError(f"duplicate field keys: {duplicates}")

    funding = [f.key for f in fields if f.type == "funding"]
    if len(funding) > 1:
        raise FormDefinitionError(f"a form has at most one funding field, got {funding}")
    if funding and not any(f.type == "positions" for f in fields):
        raise FormDefinitionError(
            f"funding field {funding[0]!r} needs a positions field in the same form"
        )

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


def effective_form(type_fields: Sequence[FormFieldDef]) -> list[FormSection]:
    """Split the type fields into sections.

    ``main`` always holds the type fields. The system ``title`` field comes first, because
    every application MUST have a title. A type that defines its own field with that key
    keeps its own field.

    The title field goes into the FIRST section after the split, so a leading marker does
    not create a title-only step.
    """
    sections = _split_sections(list(type_fields))
    has_title = any(f.key == SYSTEM_TITLE_KEY for s in sections for f in s.fields)
    first = sections[0]
    return (
        sections
        if has_title
        else [replace(first, fields=[system_title_field(), *first.fields]), *sections[1:]]
    )


@dataclass(frozen=True, slots=True)
class _SectionDraft:
    """The state of the section split: the closed sections and the open one."""

    closed: tuple[FormSection, ...]
    key: str
    label: dict[str, str] | None
    fields: tuple[FormFieldDef, ...]

    def section(self) -> FormSection:
        """Return the open section as a closed one."""
        return FormSection(key=self.key, fields=list(self.fields), label=self.label)


def _section_step(draft: _SectionDraft, field: FormFieldDef) -> _SectionDraft:
    """Add one field to the split, or open a new section at a marker.

    A marker closes the open section only when it has fields.
    """
    match field.type:
        case "section":
            return _SectionDraft(
                closed=(*draft.closed, draft.section()) if draft.fields else draft.closed,
                key=field.key,
                label=dict(field.label) if field.label else None,
                fields=(),
            )
        case _:
            return replace(draft, fields=(*draft.fields, field))


def _split_sections(fields: Sequence[FormFieldDef]) -> list[FormSection]:
    """Split the fields at the ``section`` markers into wizard steps.

    A marker carries the section label only. It does not appear as a field. Without a
    marker the function returns exactly one ``main`` section. That keeps backward
    compatibility.

    A marker closes the current section when it has fields. Otherwise the open section takes
    the label of the new marker (a leading or a consecutive marker).
    """
    start = _SectionDraft(closed=(), key="main", label=None, fields=())
    draft = reduce(_section_step, fields, start)
    return (
        [*draft.closed, draft.section()] if draft.fields or not draft.closed else list(draft.closed)
    )


@dataclass(frozen=True, slots=True)
class _Computed:
    """The values of the ``computed`` fields so far and the errors of their expressions."""

    values: Mapping[str, Any]
    errors: tuple[FieldError, ...]


def _compute_step(
    state: _Computed, key: str, expr: Mapping[str, Any], ctx: Mapping[str, Any]
) -> _Computed:
    """Evaluate one ``compute`` expression against ``ctx`` and the values computed so far."""
    try:
        value = eval_jsonlogic(expr, {**ctx, **state.values})
    except JsonLogicError as exc:
        error = FieldError(field=key, msg=f"compute failed: {exc}")
        return replace(state, errors=(*state.errors, error))
    return replace(state, values={**state.values, key: value})


def _answer_errors(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Return the errors of one visible answer: ``required`` or the type check."""
    return (
        _value_errors(field, value)
        if _is_present(value)
        else _err_if(field.required, field.key, "required")
    )


def validate_answers(
    fields: Sequence[FormFieldDef],
    data: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the answer data and compute the derived ``computed`` fields.

    ``context`` supplies the variables that are not form fields to ``visibleIf``, for
    example ``has_budget``.

    The steps run in this order. First the ``computed`` fields, in field order, because they
    may read other fields. Then, per field, visibility, required and type validation. A
    derived value and a structural marker have no answer value and get no check. Last, the
    requested funding must not exceed the cost total of the visible positions.

    Returns:
        ``data`` plus the values of the ``computed`` fields.

    Raises:
        AnswerValidationError: At least one field is invalid. The error carries every
            collected field error.
    """
    base_ctx = {**(context or {}), **data}
    computed = reduce(
        lambda state, pair: _compute_step(state, pair[0], pair[1], base_ctx),
        ((f.key, f.compute) for f in fields if f.type == "computed" and f.compute is not None),
        _Computed(values={}, errors=()),
    )
    result = {**data, **computed.values}
    eval_ctx = {**(context or {}), **result}
    checked = tuple(
        f for f in fields if f.type not in ("computed", "section") and _is_visible(f, eval_ctx)
    )
    field_errors = tuple(e for f in checked for e in _answer_errors(f, data.get(f.key)))
    collected = (*computed.errors, *field_errors)
    present = tuple((f, data.get(f.key)) for f in checked if _is_present(data.get(f.key)))
    cost_total = sum(
        (positions_total(value) or Decimal(0) for f, value in present if f.type == "positions"),
        Decimal(0),
    )
    fundings = tuple((f, value) for f, value in present if f.type == "funding")
    funding_errors = (
        _check_funding_total(fundings[-1][0], fundings[-1][1], cost_total, collected)
        if fundings
        else ()
    )
    errors = (*collected, *funding_errors)
    if errors:
        raise AnswerValidationError(errors)
    return result


def value_is_valid(field: FormFieldDef, value: object) -> bool:
    """Tell whether a present value passes the type check of its field.

    An absent value is not valid, because a prefill copies only a real answer.
    """
    return _is_present(value) and not _value_errors(field, value)


def _is_present(value: object) -> bool:
    """Report a value as present when it is not ``None`` and not empty.

    An empty string, list or dict counts as absent.
    """
    if value is None:
        return False
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return True


def _is_visible(field: FormFieldDef, ctx: Mapping[str, Any]) -> bool:
    """Evaluate ``visibleIf`` for a field.

    A field without an expression is visible. An evaluation error also counts as visible,
    because ``and`` and ``or`` do not short-circuit. The engine then validates the field.
    It does not skip the field in silence.
    """
    if field.visible_if is None:
        return True
    try:
        return bool(eval_jsonlogic(field.visible_if, dict(ctx)))
    except JsonLogicError:
        return True


def _value_errors(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Return the errors of a present value against its field type."""
    match field.type:
        case "text" | "textarea" | "markdown":
            return _validate_text(field, value)
        case "number" | "currency":
            return _validate_number(field, value)
        case "funding":
            return _validate_funding(field, value)
        case "date":
            return _validate_date(field, value)
        case "select":
            return _validate_select(field, value)
        case "multiselect":
            return _validate_multiselect(field, value)
        case "gremium_select":
            return _validate_uuid_ref(field, value, "gremium id")
        case "budget_select":
            return _validate_uuid_ref(field, value, "budget id")
        case "email":
            return _validate_email(field, value)
        case "iban":
            return _validate_iban(field, value)
        case "daterange":
            return _validate_daterange(field, value)
        case "checkbox":
            return _validate_checkbox(field, value)
        case "file":
            return _validate_file(field, value)
        case "table":
            return _validate_table(field, value)
        case "positions":
            return _validate_positions(field, value)
        case _:
            return _err(field.key, f"unknown field type: {field.type!r}")


def _validate_value(field: FormFieldDef, value: object, errors: list[FieldError]) -> None:
    """Validate a present value against its field type and append the errors."""
    errors.extend(_value_errors(field, value))


def _err(key: str, msg: str) -> tuple[FieldError, ...]:
    """Return one field error as a tuple, so the checks concatenate their results."""
    return (FieldError(field=key, msg=msg),)


def _err_if(condition: bool, key: str, msg: str) -> tuple[FieldError, ...]:
    """Return one field error when ``condition`` holds, else no error."""
    return _err(key, msg) if condition else ()


def _validate_text(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Validate a text value against its length bounds and its pattern.

    A broken stored pattern or a ReDoS timeout gives a field error, not a hang or a 500.
    This is defense in depth, because the save gate already rejects an invalid pattern.
    """
    if not isinstance(value, str):
        return _err(field.key, "must be a string")
    v = field.validation
    if v is None:
        return ()
    return (
        *_err_if(
            v.min_len is not None and len(value) < v.min_len,
            field.key,
            f"shorter than minimum length {v.min_len}",
        ),
        *_err_if(
            v.max_len is not None and len(value) > v.max_len,
            field.key,
            f"longer than maximum length {v.max_len}",
        ),
        *(_pattern_errors(field.key, v.pattern, value) if v.pattern is not None else ()),
    )


def _pattern_errors(key: str, pattern: str, value: str) -> tuple[FieldError, ...]:
    """Match ``value`` against an admin pattern; a broken pattern or a timeout is an error."""
    try:
        matched = _pattern_matches(pattern, value)
    except _PatternMatchError:
        return _err(key, "field has an invalid validation pattern")
    return _err_if(not matched, key, "does not match required pattern")


def _validate_number(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Validate a finite number against its bounds.

    A comparison of NaN or Infinity with min or max raises ``decimal.InvalidOperation``, so
    the function rejects such a value first and the request gets 422 instead of 500.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return _err(field.key, "must be a number")
    try:
        num = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return _err(field.key, "must be a number")
    if not num.is_finite():
        return _err(field.key, "must be a finite number")
    v = field.validation
    if v is None:
        return ()
    return (
        *_err_if(
            v.min is not None and num < Decimal(str(v.min)),
            field.key,
            f"less than minimum {v.min}",
        ),
        *_err_if(
            v.max is not None and num > Decimal(str(v.max)),
            field.key,
            f"greater than maximum {v.max}",
        ),
    )


def _validate_funding(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Validate the requested funding: a finite number of 0 or more.

    0 is valid, because an applicant can ask for an approval without money.

    The check against the cost total runs after all fields (`_check_funding_total`),
    because the positions can come after the funding field.
    """
    return _validate_number(field, value) or _err_if(
        Decimal(str(value)) < 0, field.key, "must not be negative"
    )


def _check_funding_total(
    field: FormFieldDef, value: object, cost_total: Decimal, errors: Sequence[FieldError]
) -> tuple[FieldError, ...]:
    """Report a requested funding above the cost total.

    The function skips a value that `_validate_funding` already rejected, so a bad
    value gives one error, not two.
    """
    return _err_if(
        not any(e.field == field.key for e in errors) and Decimal(str(value)) > cost_total,
        field.key,
        f"greater than the cost total {cost_total}",
    )


def _validate_date(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    if not isinstance(value, str):
        return _err(field.key, "must be an ISO date string")
    try:
        date.fromisoformat(value)
    except ValueError:
        return _err(field.key, "must be an ISO date (YYYY-MM-DD)")
    return ()


def _option_values(field: FormFieldDef) -> frozenset[str]:
    return frozenset(o.value for o in field.options or [])


def _validate_select(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Validate a single option value.

    ``FieldOption.value`` is a str, so only a string can be a valid option. The isinstance
    check also stops a TypeError when the membership test gets an unhashable value.
    """
    return _err_if(
        not isinstance(value, str) or value not in _option_values(field),
        field.key,
        "is not a valid option",
    )


def _validate_multiselect(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Validate a list of option values.

    Each element must be a str before the membership test, because an unhashable element
    such as a dict or a list raises a TypeError and gives a 500.
    """
    if not isinstance(value, list):
        return _err(field.key, "must be a list")
    allowed = _option_values(field)
    invalid = [v for v in value if not isinstance(v, str) or v not in allowed]
    return _err_if(bool(invalid), field.key, f"contains invalid options: {invalid}")


def _validate_uuid_ref(field: FormFieldDef, value: object, label: str) -> tuple[FieldError, ...]:
    """Check the value of a dynamic picker field as a well-formed UUID.

    The picker fields are `gremium_select` and `budget_select`. The server injects their
    options only at render time in ``effective_form``, from the current Gremien or from
    the budget tree. This answer validation is pure and has no DB access, so it checks the
    UUID form only. The consumers of the value check it against the DB and fail closed.
    For example, the flow action `assignBudgetFromField` skips a budget id that names no
    active cost center.
    """
    if not isinstance(value, str) or not value:
        return _err(field.key, f"must be a {label}")
    try:
        UUID(value)
    except ValueError:
        return _err(field.key, f"is not a valid {label}")
    return ()


#: Conservative e-mail pattern: one ``@``, no whitespace, a dot in the domain. It mirrors
#: the QSM/VSM form pattern, so nobody has to maintain that pattern by hand.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    return _err_if(
        not isinstance(value, str) or not _EMAIL_RE.match(value),
        field.key,
        "is not a valid e-mail address",
    )


def _iban_mod97_ok(iban: str) -> bool:
    """Check the IBAN form and the ISO-7064 mod-97 checksum.

    The function ignores spaces. It stays standalone. The bank module has its own
    internal variant for statements. This module must not depend on a private function
    of another module.

    The check moves the first four characters to the end and maps letters to digits with
    ``int(ch, 36)``, which gives A->10 up to Z->35.
    """
    s = iban.replace(" ", "").upper()
    if not (15 <= len(s) <= 34) or not s.isalnum() or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    rearranged = s[4:] + s[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


def _validate_iban(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Check the IBAN form and the ISO-7064 mod-97 checksum, not only a regex."""
    return _err_if(
        not isinstance(value, str) or not _iban_mod97_ok(value),
        field.key,
        "is not a valid IBAN",
    )


def _validate_daterange(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Check a `daterange` value ``{"from": ISO, "to": ISO}`` with ``from <= to``."""
    if not isinstance(value, dict):
        return _err(field.key, "must be an object with 'from' and 'to'")
    raw_from, raw_to = value.get("from"), value.get("to")
    if not isinstance(raw_from, str) or not isinstance(raw_to, str):
        return _err(field.key, "'from' and 'to' must be ISO date strings")
    try:
        d_from = date.fromisoformat(raw_from)
        d_to = date.fromisoformat(raw_to)
    except ValueError:
        return _err(field.key, "'from'/'to' must be ISO dates (YYYY-MM-DD)")
    return _err_if(d_from > d_to, field.key, "'from' must not be after 'to'")


def _validate_checkbox(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    return _err_if(not isinstance(value, bool), field.key, "must be a boolean")


def _validate_file(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Validate the attachment references of a file field.

    The upload checks content, size and MIME type, so this function checks only the shape.
    """
    is_reference = isinstance(value, str) or (
        isinstance(value, list) and all(isinstance(v, str) for v in value)
    )
    return _err_if(
        not is_reference,
        field.key,
        "must be an attachment reference (string or list of strings)",
    )


def _validate_table(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Validate the rows of a table field.

    The row cap does not use a falsy ``or``, because a configured ``maxRows=0`` is valid
    (``max_rows`` has ``ge=0``) and MUST reject every row. A builder value above the engine
    cap gets clamped to it.
    """
    if not isinstance(value, list):
        return _err(field.key, "must be a list of rows")
    v = field.validation
    configured = v.max_rows if (v is not None and v.max_rows is not None) else _DEFAULT_MAX_ROWS
    max_rows = min(configured, _DEFAULT_MAX_ROWS)
    return (
        *_err_if(len(value) > max_rows, field.key, f"has more than {max_rows} rows"),
        *(
            FieldError(field=field.key, msg=f"row {i} must be an object")
            for i, row in enumerate(value)
            if not isinstance(row, dict)
        ),
    )


#: Minimum offers when the builder sets none.
_DEFAULT_MIN_OFFERS = 3
_DEFAULT_MIN_POSITIONS = 1

_DEFAULT_MAX_POSITIONS = 200
_DEFAULT_MAX_OFFERS = 50
_DEFAULT_MAX_ROWS = 1000


def _offer_value(offer: Mapping[str, Any]) -> Decimal | None:
    """Return the numeric offer value as ``Decimal``.

    An invalid or non-finite value gives ``None``.
    """
    raw = offer.get("value")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        num = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return num if num.is_finite() else None


@dataclass(frozen=True, slots=True)
class _PositionRules:
    """The resolved limits of a ``positions`` field, clamped to the engine caps."""

    min_offers: int
    allow_no_offers: bool
    min_positions: int
    max_positions: int
    max_offers: int


def _position_rules(v: FieldValidation | None) -> _PositionRules:
    """Resolve the limits of a ``positions`` field from its builder values and the defaults."""
    configured_positions = (
        v.max_positions
        if (v is not None and v.max_positions is not None)
        else _DEFAULT_MAX_POSITIONS
    )
    configured_offers = (
        v.max_offers if (v is not None and v.max_offers is not None) else _DEFAULT_MAX_OFFERS
    )
    return _PositionRules(
        min_offers=(v.min_offers if v and v.min_offers else None) or _DEFAULT_MIN_OFFERS,
        allow_no_offers=(
            v.allow_no_offers if (v is not None and v.allow_no_offers is not None) else True
        ),
        min_positions=(v.min_positions if v and v.min_positions else None)
        or _DEFAULT_MIN_POSITIONS,
        max_positions=min(configured_positions, _DEFAULT_MAX_POSITIONS),
        max_offers=min(configured_offers, _DEFAULT_MAX_OFFERS),
    )


def _validate_positions(field: FormFieldDef, value: object) -> tuple[FieldError, ...]:
    """Validate the cost positions of a field.

    The list needs at least ``minPositions`` positions. Each position needs at least
    ``minOffers`` offers and exactly one preferred offer. Every offer value must be a
    finite number of 0 or more. The error keys use a 0-indexed position.

    A position can opt out of the comparison offers with ``noOffers: true`` and a
    mandatory ``noOffersReason``. The field must allow this through ``allowNoOffers``,
    which is on by default. Such a position needs exactly one offer instead of
    ``minOffers``.

    ``max_positions`` and ``max_offers`` are ``ge=1``, so 0 is impossible. The function
    clamps a configured value to the engine cap instead of using the cap only as a default,
    because a value above the cap would reopen unbounded growth.
    """
    if not isinstance(value, list):
        return _err(field.key, "must be a list of positions")
    rules = _position_rules(field.validation)
    return (
        *_err_if(
            len(value) < rules.min_positions,
            field.key,
            f"needs at least {rules.min_positions} position(s)",
        ),
        *_err_if(
            len(value) > rules.max_positions,
            field.key,
            f"has more than {rules.max_positions} position(s)",
        ),
        *(
            e
            for i, pos in enumerate(value)
            for e in _position_errors(f"{field.key}[{i}]", pos, rules)
        ),
    )


def _position_errors(where: str, pos: object, rules: _PositionRules) -> tuple[FieldError, ...]:
    """Return the errors of one position: its label, the opt-out and its offers."""
    if not isinstance(pos, dict):
        return _err(where, "must be an object")
    label = pos.get("label")
    no_offers = pos.get("noOffers") is True
    reason = pos.get("noOffersReason")
    offers = pos.get("offers")
    return (
        *_err_if(not isinstance(label, str) or not label.strip(), where, "position needs a label"),
        *_err_if(
            no_offers and not rules.allow_no_offers,
            where,
            "opting out of comparison offers is not allowed here",
        ),
        *_err_if(
            no_offers and (not isinstance(reason, str) or not reason.strip()),
            where,
            "opting out of comparison offers needs a reason",
        ),
        *(
            _offers_errors(where, offers, rules, no_offers)
            if isinstance(offers, list)
            else _err(where, "offers must be a list")
        ),
    )


def _offers_errors(
    where: str, offers: Sequence[object], rules: _PositionRules, no_offers: bool
) -> tuple[FieldError, ...]:
    """Return the errors of the offers of one position: count, each offer, the preferred one."""
    required_offers = 1 if no_offers else rules.min_offers
    preferred_count = sum(
        1 for offer in offers if isinstance(offer, dict) and offer.get("preferred") is True
    )
    return (
        *_err_if(
            len(offers) < required_offers,
            where,
            f"needs at least {required_offers} comparison offer(s)",
        ),
        *_err_if(
            len(offers) > rules.max_offers,
            where,
            f"has more than {rules.max_offers} comparison offer(s)",
        ),
        *(
            e
            for j, offer in enumerate(offers)
            for e in _offer_errors(f"{where}.offers[{j}]", offer)
        ),
        *_err_if(
            bool(offers) and preferred_count != 1,
            where,
            "exactly one offer must be marked preferred",
        ),
    )


def _offer_errors(where: str, offer: object) -> tuple[FieldError, ...]:
    """Return the errors of one comparison offer: its label and its value."""
    if not isinstance(offer, dict):
        return _err(where, "must be an object")
    label = offer.get("label")
    num = _offer_value(offer)
    return (
        *_err_if(not isinstance(label, str) or not label.strip(), where, "offer needs a label"),
        *(
            _err(where, "offer value must be a finite number")
            if num is None
            else _err_if(num < 0, where, "offer value must not be negative")
        ),
    )


def _preferred_value(pos: Mapping[str, Any]) -> Decimal | None:
    """Return the value of the first preferred offer of a position, if it is valid."""
    preferred = next(
        (
            offer
            for offer in pos.get("offers") or []
            if isinstance(offer, dict) and offer.get("preferred") is True
        ),
        None,
    )
    return _offer_value(preferred) if preferred is not None else None


def positions_total(value: object) -> Decimal | None:
    """Sum the preferred offer values of all positions.

    The result is the position total. It is ``None`` when no position has a valid
    preferred offer, for example for an empty list.
    """
    if not isinstance(value, list):
        return None
    preferred = tuple(_preferred_value(pos) for pos in value if isinstance(pos, dict))
    found = tuple(num for num in preferred if num is not None)
    return sum(found, Decimal(0)) if found else None


def _promote(out: dict[str, Any], field: FormFieldDef, data: Mapping[str, Any]) -> dict[str, Any]:
    """Add the promoted value of one field to ``out``.

    A ``positions`` field adds its total to ``amount``. A ``funding`` field adds nothing
    here, because `extract_promoted` sets it last.
    """
    match field.type:
        case "funding":
            return out
        case "positions":
            total = positions_total(data.get(field.key))
            return (
                out if total is None else {**out, "amount": out.get("amount", Decimal(0)) + total}
            )
        case _:
            return _promote_flagged(out, field, data.get(field.key))


def _promote_flagged(out: dict[str, Any], field: FormFieldDef, value: object) -> dict[str, Any]:
    """Add the value of an ``isPromoted`` field to ``out`` under its target.

    A numeric value must be a finite ``Decimal``; a bad one is left out.
    """
    target = field.promote_target
    if not (field.is_promoted and target) or value is None:
        return out
    promoted = _finite_decimal(value) if field.type in _NUMERIC_TYPES else value
    return out if promoted is None else {**out, target: promoted}


def extract_promoted(fields: Sequence[FormFieldDef], data: Mapping[str, Any]) -> dict[str, Any]:
    """Pull the promoted field values from ``data`` into ``{promote_target: value}``.

    The function normalizes a numeric promoted field such as ``amount`` to ``Decimal``.
    A filled-in ``funding`` field is the ``amount``; otherwise the cost total is.

    A filled-in `funding` field wins over every other source of `amount`. A `positions`
    field promotes the sum of its preferred offers into `amount` without an ``isPromoted``
    flag, and several `positions` fields add up. The amount is never NaN or Infinity,
    because such a value crashes a consumer.
    """
    start: dict[str, Any] = {}
    promoted = reduce(lambda out, f: _promote(out, f, data), fields, start)
    fundings = tuple(_finite_decimal(data.get(f.key)) for f in fields if f.type == "funding")
    funding = fundings[-1] if fundings else None
    return promoted if funding is None else {**promoted, "amount": funding}


def _finite_decimal(value: object) -> Decimal | None:
    """Return ``value`` as a finite ``Decimal``, or ``None`` for an absent or bad value."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        num = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return num if num.is_finite() else None
