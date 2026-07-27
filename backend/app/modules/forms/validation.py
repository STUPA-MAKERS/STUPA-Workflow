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
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.shared.config_schemas import FormFieldDef
from app.shared.jsonlogic import JsonLogicError, eval_jsonlogic, validate_jsonlogic

# Field types with a numeric value, used by the promoted extraction and by min and max.
_NUMERIC_TYPES = frozenset({"number", "currency"})
_TEXT_TYPES = frozenset({"text", "textarea", "markdown"})

# ReDoS hardening: an admin defines ``validation.pattern`` as a raw regex, and it runs
# against applicant input. An expression with catastrophic backtracking would block the
# single-replica event loop. Two independent bounds stop this:
#   1. A hard input length cap bounds the worst case at all times. It holds even when the
#      timeout cannot kill the match. A longer value counts as "no match".
#   2. A wall-clock timeout in a thread. The match runs in a worker thread. If it does not
#      finish inside the budget, the event loop gets control back and marks the field
#      invalid. Nothing can hard-kill the thread. The length cap makes it stop after a
#      bounded time.
_PATTERN_MAX_INPUT_LEN = 4096
_PATTERN_MATCH_TIMEOUT_SECONDS = 1.0
# One small shared executor. Pattern matches are rare and short.
_PATTERN_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="form-regex")


class _PatternMatchError(Exception):
    """The pattern match failed because of a broken regex or a timeout."""


def _pattern_matches(pattern: str, value: str) -> bool:
    """Run ``re.fullmatch`` on ``value`` with a length bound and a timeout (ReDoS).

    A value longer than `_PATTERN_MAX_INPUT_LEN` always counts as "no match". The
    function makes no match attempt for it.

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
        # The thread keeps running, bounded by the length cap. The caller gets control back.
        raise _PatternMatchError("pattern match timed out") from exc
    except re.error as exc:
        raise _PatternMatchError("invalid pattern") from exc


def _full_match(pattern: str, value: str) -> bool:
    return re.fullmatch(pattern, value) is not None


# Reserved key of the system title field. Every application MUST have a title. The server
# prepends the field to every effective form. The builder cannot edit it.
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


@dataclass(frozen=True)
class FieldError:
    """A validation error for a concrete answer field."""

    field: str
    msg: str


class AnswerValidationError(Exception):
    """The answer data is invalid.

    The exception carries every collected field error and maps to a 422 response.
    """

    def __init__(self, errors: Sequence[FieldError]) -> None:
        self.errors: list[FieldError] = list(errors)
        super().__init__(f"{len(self.errors)} field error(s)")


@dataclass(frozen=True)
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
    with a 500.

    Raises:
        FormDefinitionError: The definition breaks one of these rules.
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


def effective_form(
    type_fields: Sequence[FormFieldDef],
    pot_fields: Sequence[FormFieldDef] | None = None,
) -> list[FormSection]:
    """Merge the type fields and the pot extra fields into sections.

    ``main`` always holds the type fields. The system ``title`` field comes first, because
    every application MUST have a title. A type that defines its own field with that key
    keeps its own field. ``budget`` appears only when the caller passes non-empty
    ``pot_fields``.
    """
    sections = _split_sections(list(type_fields))
    # Add the title field to the FIRST section after the split. A leading marker must not
    # create a title-only step.
    if not any(f.key == SYSTEM_TITLE_KEY for s in sections for f in s.fields):
        sections[0].fields.insert(0, system_title_field())
    if pot_fields:
        sections.append(FormSection(key="budget", fields=list(pot_fields)))
    return sections


def _split_sections(fields: Sequence[FormFieldDef]) -> list[FormSection]:
    """Split the fields at the ``section`` markers into wizard steps.

    A marker carries the section label only. It does not appear as a field. Without a
    marker the function returns exactly one ``main`` section. That keeps backward
    compatibility.
    """
    sections: list[FormSection] = []
    cur_key = "main"
    cur_label: dict[str, str] | None = None
    cur_fields: list[FormFieldDef] = []

    for f in fields:
        if f.type == "section":
            # Close the current section when it has fields. Otherwise take the label of
            # the new marker (a leading or a consecutive marker).
            if cur_fields:
                sections.append(FormSection(key=cur_key, fields=cur_fields, label=cur_label))
                cur_fields = []
            cur_key = f.key
            cur_label = dict(f.label) if f.label else None
            continue
        cur_fields.append(f)

    if cur_fields or not sections:
        sections.append(FormSection(key=cur_key, fields=cur_fields, label=cur_label))
    return sections


def validate_answers(
    fields: Sequence[FormFieldDef],
    data: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the answer data and compute the derived ``computed`` fields.

    ``context`` supplies the variables that are not form fields to ``visibleIf``, for
    example ``has_budget``.

    Returns:
        ``data`` plus the values of the ``computed`` fields.

    Raises:
        AnswerValidationError: At least one field is invalid. The error carries every
            collected field error.
    """
    errors: list[FieldError] = []
    result: dict[str, Any] = dict(data)

    # 1. Compute the computed fields in field order. They may read other fields.
    base_ctx: dict[str, Any] = {**(context or {}), **result}
    for f in fields:
        if f.type == "computed" and f.compute is not None:
            try:
                result[f.key] = eval_jsonlogic(f.compute, base_ctx)
                base_ctx[f.key] = result[f.key]
            except JsonLogicError as exc:
                errors.append(FieldError(field=f.key, msg=f"compute failed: {exc}"))

    eval_ctx: dict[str, Any] = {**(context or {}), **result}

    # 2. Per field, in this order: visibility, then required, then type validation.
    for f in fields:
        if f.type in ("computed", "section"):
            continue  # a derived value or a pure structural marker, no answer value
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


# Per-field type validation.
def _validate_value(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    """Validate a present value against its field type and append the errors."""
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
    elif t == "gremium_select":
        _validate_uuid_ref(field, value, errors, "gremium id")
    elif t == "budget_select":
        _validate_uuid_ref(field, value, errors, "budget id")
    elif t == "email":
        _validate_email(field, value, errors)
    elif t == "iban":
        _validate_iban(field, value, errors)
    elif t == "daterange":
        _validate_daterange(field, value, errors)
    elif t == "checkbox":
        _validate_checkbox(field, value, errors)
    elif t == "file":
        _validate_file(field, value, errors)
    elif t == "table":
        _validate_table(field, value, errors)
    elif t == "positions":
        _validate_positions(field, value, errors)
    else:  # pragma: no cover via FormFieldDef.type (Literal) — defensively checked in tests
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
            matched = _pattern_matches(v.pattern, value)
        except _PatternMatchError:
            # A broken stored pattern or a ReDoS timeout. This is defense in depth,
            # because the save gate already rejects an invalid pattern. The request must
            # never hang or give a 500, so report a field error instead.
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
        # A comparison of NaN or Infinity with min or max raises
        # decimal.InvalidOperation. Report 422 instead of 500.
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
    # FieldOption.value is a str, so only a string can be a valid option. The isinstance
    # guard holds that domain. It also stops a TypeError when the membership test gets an
    # unhashable value.
    if not isinstance(value, str) or value not in _option_values(field):
        _err(errors, field.key, "is not a valid option")


def _validate_multiselect(
    field: FormFieldDef, value: Any, errors: list[FieldError]
) -> None:
    if not isinstance(value, list):
        _err(errors, field.key, "must be a list")
        return
    allowed = _option_values(field)
    # Check that each element is a str before the test against the option set. An
    # unhashable element such as a dict or a list would raise a TypeError and give a 500.
    invalid = [v for v in value if not isinstance(v, str) or v not in allowed]
    if invalid:
        _err(errors, field.key, f"contains invalid options: {invalid}")


def _validate_uuid_ref(
    field: FormFieldDef, value: Any, errors: list[FieldError], label: str
) -> None:
    """Check the value of a dynamic picker field as a well-formed UUID.

    The picker fields are `gremium_select` and `budget_select`. The server injects their
    options only at render time in ``effective_form``, from the current Gremien or from
    the budget tree. This answer validation is pure and has no DB access, so it checks the
    UUID form only. A value that names no real entity finds no transition in the flow,
    which fails closed.
    """
    if not isinstance(value, str) or not value:
        _err(errors, field.key, f"must be a {label}")
        return
    try:
        UUID(value)
    except ValueError:
        _err(errors, field.key, f"is not a valid {label}")


# Conservative e-mail pattern: one ``@``, no whitespace, a dot in the domain. It mirrors
# the QSM/VSM form pattern, so nobody has to maintain that pattern by hand.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    if not isinstance(value, str) or not _EMAIL_RE.match(value):
        _err(errors, field.key, "is not a valid e-mail address")


def _iban_mod97_ok(iban: str) -> bool:
    """Check the IBAN form and the ISO-7064 mod-97 checksum.

    The function ignores spaces. It stays standalone. The bank module has its own
    internal variant for statements. This module must not depend on a private function
    of another module.
    """
    s = iban.replace(" ", "").upper()
    if not (15 <= len(s) <= 34) or not s.isalnum() or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    # Move the first four characters to the end. Map letters to digits with int(ch, 36),
    # which gives A->10 up to Z->35.
    rearranged = s[4:] + s[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


def _validate_iban(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    """Check the IBAN form and the ISO-7064 mod-97 checksum, not only a regex."""
    if not isinstance(value, str) or not _iban_mod97_ok(value):
        _err(errors, field.key, "is not a valid IBAN")


def _validate_daterange(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    """Check a `daterange` value ``{"from": ISO, "to": ISO}`` with ``from <= to``."""
    if not isinstance(value, dict):
        _err(errors, field.key, "must be an object with 'from' and 'to'")
        return
    raw_from, raw_to = value.get("from"), value.get("to")
    if not isinstance(raw_from, str) or not isinstance(raw_to, str):
        _err(errors, field.key, "'from' and 'to' must be ISO date strings")
        return
    try:
        d_from = date.fromisoformat(raw_from)
        d_to = date.fromisoformat(raw_to)
    except ValueError:
        _err(errors, field.key, "'from'/'to' must be ISO dates (YYYY-MM-DD)")
        return
    if d_from > d_to:
        _err(errors, field.key, "'from' must not be after 'to'")


def _validate_checkbox(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    if not isinstance(value, bool):
        _err(errors, field.key, "must be a boolean")


def _validate_file(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    # The answer value holds attachment references. The upload checks content, size and MIME.
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
    # Engine cap: do not use a falsy `or` here. A configured maxRows=0 is valid, because
    # max_rows has ge=0, and it MUST reject every row. Clamp to the engine cap as well, so
    # a higher builder value cannot lift the upper bound.
    configured = (
        v.max_rows if (v is not None and v.max_rows is not None) else _DEFAULT_MAX_ROWS
    )
    max_rows = min(configured, _DEFAULT_MAX_ROWS)
    if len(value) > max_rows:
        _err(errors, field.key, f"has more than {max_rows} rows")
    for i, row in enumerate(value):
        if not isinstance(row, dict):
            _err(errors, field.key, f"row {i} must be an object")


# Minimums that apply when the builder sets none.
_DEFAULT_MIN_OFFERS = 3
_DEFAULT_MIN_POSITIONS = 1

# Engine caps: upper bounds for positions, offers and table rows. They apply even without
# a builder value and do not depend on the body cap. They stop a raised body cap or an
# authenticated write path from pushing unbounded positions or offers through
# `_validate_positions`, `positions_total` and the JSONB persistence.
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


def _validate_positions(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    """Validate the cost positions of a field.

    The list needs at least ``minPositions`` positions. Each position needs at least
    ``minOffers`` offers and exactly one preferred offer. Every offer value must be a
    finite number above 0. The error keys use a 0-indexed position.

    A position can opt out of the comparison offers with ``noOffers: true`` and a
    mandatory ``noOffersReason``. The field must allow this through ``allowNoOffers``,
    which is on by default. Such a position needs exactly one offer instead of
    ``minOffers``.
    """
    if not isinstance(value, list):
        _err(errors, field.key, "must be a list of positions")
        return
    v = field.validation
    min_offers = (v.min_offers if v and v.min_offers else None) or _DEFAULT_MIN_OFFERS
    allow_no_offers = (
        v.allow_no_offers if (v is not None and v.allow_no_offers is not None) else True
    )
    min_positions = (
        v.min_positions if v and v.min_positions else None
    ) or _DEFAULT_MIN_POSITIONS
    # Engine cap: max_positions and max_offers are ge=1, so 0 is impossible. An admin can
    # still use form.configure to set a value above the default cap and reopen unbounded
    # growth. So clamp the configured value to the engine cap instead of using the cap as
    # a default only.
    configured_positions = (
        v.max_positions
        if (v is not None and v.max_positions is not None)
        else _DEFAULT_MAX_POSITIONS
    )
    max_positions = min(configured_positions, _DEFAULT_MAX_POSITIONS)
    configured_offers = (
        v.max_offers if (v is not None and v.max_offers is not None) else _DEFAULT_MAX_OFFERS
    )
    max_offers = min(configured_offers, _DEFAULT_MAX_OFFERS)

    if len(value) < min_positions:
        _err(errors, field.key, f"needs at least {min_positions} position(s)")
    if len(value) > max_positions:
        _err(errors, field.key, f"has more than {max_positions} position(s)")

    for i, pos in enumerate(value):
        where = f"{field.key}[{i}]"
        if not isinstance(pos, dict):
            _err(errors, where, "must be an object")
            continue
        if not isinstance(pos.get("label"), str) or not pos["label"].strip():
            _err(errors, where, "position needs a label")
        no_offers = pos.get("noOffers") is True
        if no_offers:
            if not allow_no_offers:
                _err(errors, where, "opting out of comparison offers is not allowed here")
            reason = pos.get("noOffersReason")
            if not isinstance(reason, str) or not reason.strip():
                _err(errors, where, "opting out of comparison offers needs a reason")
        offers = pos.get("offers")
        if not isinstance(offers, list):
            _err(errors, where, "offers must be a list")
            continue
        required_offers = 1 if no_offers else min_offers
        if len(offers) < required_offers:
            _err(errors, where, f"needs at least {required_offers} comparison offer(s)")
        if len(offers) > max_offers:
            _err(errors, where, f"has more than {max_offers} comparison offer(s)")
        preferred_count = 0
        for j, offer in enumerate(offers):
            owhere = f"{where}.offers[{j}]"
            if not isinstance(offer, dict):
                _err(errors, owhere, "must be an object")
                continue
            if not isinstance(offer.get("label"), str) or not offer["label"].strip():
                _err(errors, owhere, "offer needs a label")
            num = _offer_value(offer)
            if num is None:
                _err(errors, owhere, "offer value must be a finite number")
            elif num <= 0:
                _err(errors, owhere, "offer value must be greater than 0")
            if offer.get("preferred") is True:
                preferred_count += 1
        if offers and preferred_count != 1:
            _err(errors, where, "exactly one offer must be marked preferred")


def positions_total(value: Any) -> Decimal | None:
    """Sum the preferred offer values of all positions.

    The result is the position total. It is ``None`` when no position has a valid
    preferred offer, for example for an empty list.
    """
    if not isinstance(value, list):
        return None
    total = Decimal("0")
    found = False
    for pos in value:
        if not isinstance(pos, dict):
            continue
        for offer in pos.get("offers") or []:
            if isinstance(offer, dict) and offer.get("preferred") is True:
                num = _offer_value(offer)
                if num is not None:
                    total += num
                    found = True
                break
    return total if found else None


def extract_promoted(
    fields: Sequence[FormFieldDef], data: Mapping[str, Any]
) -> dict[str, Any]:
    """Pull the promoted field values from ``data`` into ``{promote_target: value}``.

    The function normalizes a numeric promoted field such as ``amount`` to ``Decimal``.
    """
    out: dict[str, Any] = {}
    for f in fields:
        # A `positions` field promotes the position total into `amount` without an
        # isPromoted flag. The total is the sum of the preferred offers. Several
        # `positions` fields add up.
        if f.type == "positions":
            total = positions_total(data.get(f.key))
            if total is not None:
                out["amount"] = out.get("amount", Decimal("0")) + total
            continue
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
            # Never pass NaN or Infinity through as amount. It would crash a consumer.
            if not num.is_finite():
                continue
            out[f.promote_target] = num
        else:
            out[f.promote_target] = value
    return out
