"""Pure form engine — no DB, no HTTP dependency.

Three core functions:

* :func:`validate_definition` — structurally validate a form definition (list of
  ``FormFieldDef``) against the config schema (unique keys, promoted fields numeric).
  Per-field schema is already guaranteed by ``FormFieldDef``.
* :func:`effective_form` — merge type fields + pot extra fields into sectioned parts.
  The pot section appears only when the application is assigned to a pot.
* :func:`validate_answers` — validate answer data against all field types (required,
  ``visibleIf`` → visible ⇒ required, ``compute`` → derived fields). Collects all field
  errors (no fail-fast) → ``AnswerValidationError``.

`visibleIf`/`compute` use the JsonLogic-subset evaluator. Its ``and``/``or`` do not
short-circuit — all operands are evaluated. A ``visibleIf`` like
``{"and":[{"var":"x"},{">":[{"var":"y"},0]}]}`` may therefore raise a ``JsonLogicError``
on missing ``y`` instead of stopping at ``x``. During visibility evaluation such an
error is treated conservatively as visible (the field is validated rather than silently
skipped), see :func:`_is_visible`.
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

# Field types whose value is numeric (for promoted extraction + min/max).
_NUMERIC_TYPES = frozenset({"number", "currency"})
_TEXT_TYPES = frozenset({"text", "textarea", "markdown"})

# ReDoS hardening: an admin-defined ``validation.pattern`` (raw regex) runs against
# applicant input; a catastrophically backtracking expression would otherwise block the
# single-replica event loop. Two independent bounds:
#   1. Hard input length cap → bounds the worst case unconditionally (holds even if the
#      timeout is not killable). Longer values count as "no match".
#   2. Wall-clock timeout in a thread: the match runs in a worker thread; if it does not
#      finish within the budget the caller (event loop) regains control and treats the
#      field as invalid. The thread cannot be hard-killed — the length cap ensures it
#      terminates in bounded time.
_PATTERN_MAX_INPUT_LEN = 4096
_PATTERN_MATCH_TIMEOUT_SECONDS = 1.0
# Shared, small executor — pattern matches are rare and short.
_PATTERN_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="form-regex")


class _PatternMatchError(Exception):
    """Pattern match failed technically (broken regex or timeout)."""


def _pattern_matches(pattern: str, value: str) -> bool:
    """``re.fullmatch`` against ``value`` — length-bounded + wall-clock timeout (ReDoS).

    Raises :class:`_PatternMatchError` on a broken pattern or timeout; the caller then
    flags the field invalid. Values over :data:`_PATTERN_MAX_INPUT_LEN` count
    unconditionally as "no match" (no match attempt)."""
    if len(value) > _PATTERN_MAX_INPUT_LEN:
        return False
    future = _PATTERN_EXECUTOR.submit(_full_match, pattern, value)
    try:
        return future.result(timeout=_PATTERN_MATCH_TIMEOUT_SECONDS)
    except FutureTimeout as exc:
        # Thread keeps running bounded (length cap); we hand control back.
        raise _PatternMatchError("pattern match timed out") from exc
    except re.error as exc:
        raise _PatternMatchError("invalid pattern") from exc


def _full_match(pattern: str, value: str) -> bool:
    return re.fullmatch(pattern, value) is not None


# Reserved key of the system title field: every application MUST have a title. The
# server prepends it to every effective form (not editable in the builder).
SYSTEM_TITLE_KEY = "title"


def system_title_field() -> FormFieldDef:
    """Required title field the server prepends to every effective form."""
    return FormFieldDef.model_validate(
        {
            "key": SYSTEM_TITLE_KEY,
            "type": "text",
            "label": {"de": "Titel", "en": "Title"},
            "required": True,
        }
    )


class FormDefinitionError(Exception):
    """Form definition violates a structural rule (save gate)."""


@dataclass(frozen=True)
class FieldError:
    """A validation error for a concrete answer field."""

    field: str
    msg: str


class AnswerValidationError(Exception):
    """Answer data is invalid; carries all collected field errors (→ 422)."""

    def __init__(self, errors: Sequence[FieldError]) -> None:
        self.errors: list[FieldError] = list(errors)
        super().__init__(f"{len(self.errors)} field error(s)")


@dataclass(frozen=True)
class FormSection:
    """A section of the effective form (``main`` = type, ``budget`` = pot extra).

    ``label`` is set when the section comes from a ``section`` marker in the form
    (multi-step forms); otherwise ``None`` (the service resolves the default labels
    ``main``/``budget``)."""

    key: str
    fields: list[FormFieldDef]
    label: dict[str, str] | None = None


# --- validate_definition ---
def validate_definition(fields: Sequence[FormFieldDef]) -> None:
    """Structurally validate a form definition. Raises ``FormDefinitionError``.

    Rules: no duplicate field keys; promoted fields must be numeric
    (``number``/``currency``) since the target (e.g. ``amount``) is ``numeric``;
    ``visibleIf``/``compute`` only with whitelist operators; a set ``pattern`` must be a
    compilable regex (else 500 at answer runtime).
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


# --- effective_form ---
def effective_form(
    type_fields: Sequence[FormFieldDef],
    pot_fields: Sequence[FormFieldDef] | None = None,
) -> list[FormSection]:
    """Merge type fields + pot extra fields into sections.

    ``main`` always contains the type fields, prefixed by the system-required ``title``
    field (every application MUST have a title) unless the type defines one with that
    key itself. ``budget`` appears only when ``pot_fields`` are assigned and non-empty.
    """
    sections = _split_sections(list(type_fields))
    # Prepend the system title field to the FIRST section (after the split, so a leading
    # marker does not create a title-only step) unless it is defined already.
    if not any(f.key == SYSTEM_TITLE_KEY for s in sections for f in s.fields):
        sections[0].fields.insert(0, system_title_field())
    if pot_fields:
        sections.append(FormSection(key="budget", fields=list(pot_fields)))
    return sections


def _split_sections(fields: Sequence[FormFieldDef]) -> list[FormSection]:
    """Split fields at ``section`` markers into several sections (= wizard steps). The
    marker itself carries only the section label and does not appear as a field. Without
    markers exactly one ``main`` section results (backward compatibility)."""
    sections: list[FormSection] = []
    cur_key = "main"
    cur_label: dict[str, str] | None = None
    cur_fields: list[FormFieldDef] = []

    for f in fields:
        if f.type == "section":
            # Close the current section if it has fields; otherwise just take the new
            # marker's label (leading/consecutive markers).
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


# --- validate_answers ---
def validate_answers(
    fields: Sequence[FormFieldDef],
    data: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate answer data + compute derived (``computed``) fields.

    ``context`` supplies non-field variables for ``visibleIf`` (e.g. ``has_budget``).
    Returns ``data`` plus computed ``computed`` values. On errors →
    ``AnswerValidationError`` (all errors collected).
    """
    errors: list[FieldError] = []
    result: dict[str, Any] = dict(data)

    # 1. compute computed fields (in field order; may use other fields).
    base_ctx: dict[str, Any] = {**(context or {}), **result}
    for f in fields:
        if f.type == "computed" and f.compute is not None:
            try:
                result[f.key] = eval_jsonlogic(f.compute, base_ctx)
                base_ctx[f.key] = result[f.key]
            except JsonLogicError as exc:
                errors.append(FieldError(field=f.key, msg=f"compute failed: {exc}"))

    eval_ctx: dict[str, Any] = {**(context or {}), **result}

    # 2. per field: visibility → required → type validation.
    for f in fields:
        if f.type in ("computed", "section"):
            continue  # derived or a pure structural marker — no answer value
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
    """A value counts as present if not ``None`` and not empty (string/list)."""
    if value is None:
        return False
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return True


def _is_visible(field: FormFieldDef, ctx: Mapping[str, Any]) -> bool:
    """Evaluate ``visibleIf``. No expression ⇒ visible. Eval error ⇒ conservatively
    visible (non-short-circuiting ``and``/``or`` → field is validated, not silently
    skipped)."""
    if field.visible_if is None:
        return True
    try:
        return bool(eval_jsonlogic(field.visible_if, dict(ctx)))
    except JsonLogicError:
        return True


# --- per-field type validation ---
def _validate_value(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    """Validate a present value against its field type; append errors."""
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
            # Broken stored pattern OR ReDoS timeout: defense-in-depth (invalid patterns
            # are already rejected at save time) — never 500/hang at runtime, surface it
            # as a field error instead.
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
        # NaN/Infinity: comparing with min/max would raise decimal.InvalidOperation
        # -> 422 instead of 500.
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
    # FieldOption.value is declared as str; only strings can be valid options. The
    # isinstance guard enforces the domain and avoids a TypeError on the membership
    # test with unhashable values.
    if not isinstance(value, str) or value not in _option_values(field):
        _err(errors, field.key, "is not a valid option")


def _validate_multiselect(
    field: FormFieldDef, value: Any, errors: list[FieldError]
) -> None:
    if not isinstance(value, list):
        _err(errors, field.key, "must be a list")
        return
    allowed = _option_values(field)
    # Check each element is a str before testing it against the (str) option set —
    # otherwise an unhashable element (dict/list) raises a TypeError -> 500.
    invalid = [v for v in value if not isinstance(v, str) or v not in allowed]
    if invalid:
        _err(errors, field.key, f"contains invalid options: {invalid}")


def _validate_uuid_ref(
    field: FormFieldDef, value: Any, errors: list[FieldError], label: str
) -> None:
    """Dynamic picker field (`gremium_select`/`budget_select`): the value must be a
    well-formed UUID.

    The server injects the options only at render time (``effective_form``) from the
    current committees resp. budget tree; the pure (DB-free) answer validation has no
    access to them — hence only the UUID form here. A value that names no real entity
    finds no transition in the flow (fail-closed)."""
    if not isinstance(value, str) or not value:
        _err(errors, field.key, f"must be a {label}")
        return
    try:
        UUID(value)
    except ValueError:
        _err(errors, field.key, f"is not a valid {label}")


# Conservative e-mail pattern (one ``@``, no whitespace, a dot in the domain) —
# mirrors the QSM/VSM form pattern without needing to hand-maintain it.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    if not isinstance(value, str) or not _EMAIL_RE.match(value):
        _err(errors, field.key, "is not a valid e-mail address")


def _iban_mod97_ok(iban: str) -> bool:
    """IBAN form + ISO-7064 mod-97 checksum. Spaces are ignored.

    (Kept standalone — the bank module has its own internal variant for statements;
    no cross-module dependency on a private function here.)"""
    s = iban.replace(" ", "").upper()
    if not (15 <= len(s) <= 34) or not s.isalnum() or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    # First four chars to the end; letters -> digits (A->10 … Z->35, ``int(ch, 36)``).
    rearranged = s[4:] + s[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


def _validate_iban(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    """Check IBAN: form + ISO-7064 mod-97 checksum (not just a regex)."""
    if not isinstance(value, str) or not _iban_mod97_ok(value):
        _err(errors, field.key, "is not a valid IBAN")


def _validate_daterange(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    """`daterange`: ``{"from": ISO, "to": ISO}`` with ``from <= to``."""
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
    # Answer value = attachment reference(s); content/size/MIME are checked by the upload.
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
    # Engine cap: no falsy-`or` — an explicitly configured maxRows=0 (max_rows has ge=0,
    # 0 is valid) MUST be preserved and reject every row. Also clamp to the engine cap so
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


# Default minimum comparison offers per position when the builder sets none.
_DEFAULT_MIN_OFFERS = 3
_DEFAULT_MIN_POSITIONS = 1

# Engine caps: upper bounds for positions/offers/table rows that apply even WITHOUT a
# builder value, independent of the body cap. Stops a raised body cap or an
# authenticated write path from pushing unbounded positions/offers through
# `_validate_positions`/`positions_total`/JSONB persistence.
_DEFAULT_MAX_POSITIONS = 200
_DEFAULT_MAX_OFFERS = 50
_DEFAULT_MAX_ROWS = 1000


def _offer_value(offer: Mapping[str, Any]) -> Decimal | None:
    """Pull the numeric offer value as ``Decimal`` (invalid -> ``None``)."""
    raw = offer.get("value")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        num = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return num if num.is_finite() else None


def _validate_positions(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    """Validate cost positions: >= minPositions positions, each >= minOffers offers,
    exactly one preferred offer, all values finite numbers > 0 (position 0-indexed).

    A position may opt out of comparison offers (``noOffers: true`` + mandatory
    ``noOffersReason``) when the field allows it (``allowNoOffers``, default on) —
    it then needs exactly one offer instead of ``minOffers``."""
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
    # Engine cap: max_positions/max_offers are ge=1 (0 impossible), but a form.configure
    # admin could set a value above the default cap and reopen unbounded growth. So clamp
    # the configured value to the engine cap (min) instead of only using it as a default.
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
    """Sum of the preferred offer values across all positions (= position total).

    ``None`` when there is no valid preferred position (e.g. an empty list).
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


# --------------------------------------------------------------------------- #
# Promoted extraction
# --------------------------------------------------------------------------- #
def extract_promoted(
    fields: Sequence[FormFieldDef], data: Mapping[str, Any]
) -> dict[str, Any]:
    """Pull promoted field values from ``data`` -> ``{promote_target: value}``.

    Numeric promoted fields (``amount``) are normalized to ``Decimal``.
    """
    out: dict[str, Any] = {}
    for f in fields:
        # `positions` implicitly promotes the position total into `amount` (sum of
        # preferred offers) — without an isPromoted flag; additive across several.
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
            # Never pass NaN/Infinity through as amount (would crash downstream).
            if not num.is_finite():
                continue
            out[f.promote_target] = num
        else:
            out[f.promote_target] = value
    return out
