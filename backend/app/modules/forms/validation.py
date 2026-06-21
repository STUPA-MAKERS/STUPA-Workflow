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
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.shared.config_schemas import FormFieldDef
from app.shared.jsonlogic import JsonLogicError, eval_jsonlogic, validate_jsonlogic

# Feldtypen, deren Wert numerisch ist (für promoted-Extraktion + min/max).
_NUMERIC_TYPES = frozenset({"number", "currency"})
_TEXT_TYPES = frozenset({"text", "textarea", "markdown"})

# ReDoS-Härtung (security.md): ein admin-definiertes ``validation.pattern`` (Roh-Regex)
# läuft gegen Antragsteller-Eingaben. Ein katastrophal backtrackender Ausdruck würde
# sonst die Single-Replica-Event-Loop blockieren. Zwei voneinander unabhängige Grenzen:
#   1. **Harte Längenobergrenze** des zu prüfenden Werts → beschränkt die Eingabegröße
#      und damit den Worst-Case unbedingt (greift, auch wenn der Timeout nicht killbar
#      ist). Werte darüber gelten als »passt nicht«.
#   2. **Wand-Timeout** im Thread: der Match läuft in einem Worker-Thread; greift er
#      nicht innerhalb des Budgets, gibt der Aufrufer (Event-Loop) die Kontrolle zurück
#      und behandelt das Feld als ungültig. Der Thread kann nicht hart gekillt werden —
#      die Längenobergrenze sorgt aber dafür, dass er beschränkt terminiert.
_PATTERN_MAX_INPUT_LEN = 4096
_PATTERN_MATCH_TIMEOUT_SECONDS = 1.0
# Geteilter, klein gehaltener Executor — Pattern-Matches sind selten und kurz.
_PATTERN_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="form-regex")


class _PatternMatchError(Exception):
    """Pattern-Match scheiterte technisch (defekte Regex oder Zeitüberschreitung)."""


def _pattern_matches(pattern: str, value: str) -> bool:
    """``re.fullmatch`` gegen ``value`` — längenbeschränkt + Wand-Timeout (ReDoS).

    Wirft :class:`_PatternMatchError` bei defektem Pattern **oder** Timeout; ruft der
    Aufrufer dann ein Feld als ungültig aus. Werte über :data:`_PATTERN_MAX_INPUT_LEN`
    gelten unbedingt als »passt nicht« (kein Match-Versuch)."""
    if len(value) > _PATTERN_MAX_INPUT_LEN:
        return False
    future = _PATTERN_EXECUTOR.submit(_full_match, pattern, value)
    try:
        return future.result(timeout=_PATTERN_MATCH_TIMEOUT_SECONDS)
    except FutureTimeout as exc:
        # Thread läuft beschränkt (Längen-Cap) weiter; wir geben die Kontrolle zurück.
        raise _PatternMatchError("pattern match timed out") from exc
    except re.error as exc:
        raise _PatternMatchError("invalid pattern") from exc


def _full_match(pattern: str, value: str) -> bool:
    return re.fullmatch(pattern, value) is not None


# Reservierter Schlüssel des System-Titelfelds: jeder Antrag MUSS einen Titel haben.
# Der Server hängt es an jede effektive Form (nicht im Builder editierbar).
SYSTEM_TITLE_KEY = "title"


def system_title_field() -> FormFieldDef:
    """Pflicht-Titelfeld, das der Server jeder effektiven Form voranstellt."""
    return FormFieldDef.model_validate(
        {
            "key": SYSTEM_TITLE_KEY,
            "type": "text",
            "label": {"de": "Titel", "en": "Title"},
            "required": True,
        }
    )


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
    """Ein Abschnitt der effektiven Form (``main`` = Typ, ``budget`` = Topf-Extra).

    ``label`` ist gesetzt, wenn der Abschnitt von einem ``section``-Marker im
    Formular stammt (mehrstufige Formulare); sonst ``None`` (Standard-Labels
    ``main``/``budget`` löst der Service auf)."""

    key: str
    fields: list[FormFieldDef]
    label: dict[str, str] | None = None


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

    ``main`` enthält immer die Typ-Felder, denen das System-Pflichtfeld ``title``
    vorangestellt wird (jeder Antrag MUSS einen Titel haben), sofern der Typ nicht
    selbst eines mit diesem Schlüssel definiert. ``budget`` erscheint **nur**, wenn
    ``pot_fields`` zugeordnet und nicht leer sind (Topf-Zuordnung).
    """
    sections = _split_sections(list(type_fields))
    # System-Titelfeld dem ERSTEN Abschnitt voranstellen (nach dem Split, damit ein
    # führender Marker keinen Titel-only-Schritt erzeugt), sofern nicht selbst definiert.
    if not any(f.key == SYSTEM_TITLE_KEY for s in sections for f in s.fields):
        sections[0].fields.insert(0, system_title_field())
    if pot_fields:
        sections.append(FormSection(key="budget", fields=list(pot_fields)))
    return sections


def _split_sections(fields: Sequence[FormFieldDef]) -> list[FormSection]:
    """Felder an ``section``-Markern in mehrere Abschnitte (= Wizard-Schritte)
    aufteilen. Der Marker selbst trägt nur das Abschnitts-Label und erscheint
    **nicht** als Feld. Ohne Marker entsteht genau ein ``main``-Abschnitt
    (Rückwärtskompatibilität)."""
    sections: list[FormSection] = []
    cur_key = "main"
    cur_label: dict[str, str] | None = None
    cur_fields: list[FormFieldDef] = []

    for f in fields:
        if f.type == "section":
            # Aktuellen Abschnitt schließen, sofern er Felder hat; sonst nur das
            # Label des neuen Markers übernehmen (führende/aufeinanderfolgende Marker).
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
        if f.type in ("computed", "section"):
            continue  # abgeleitet bzw. reiner Struktur-Marker — kein Antwortwert
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
    elif t == "positions":
        _validate_positions(field, value, errors)
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
            matched = _pattern_matches(v.pattern, value)
        except _PatternMatchError:
            # Defekt gespeichertes Pattern ODER ReDoS-Timeout: defense-in-depth
            # (validate_definition lehnt invalide Pattern schon beim Anlegen ab) —
            # niemals 500/Hänger zur Laufzeit, sondern als Feldfehler ausweisen.
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
    # FieldOption.value ist als str deklariert; nur Strings können gültige
    # Optionen sein. Der isinstance-Guard erzwingt die Domäne und verhindert
    # zugleich einen TypeError beim Membership-Test mit unhashbaren Werten.
    if not isinstance(value, str) or value not in _option_values(field):
        _err(errors, field.key, "is not a valid option")


def _validate_multiselect(
    field: FormFieldDef, value: Any, errors: list[FieldError]
) -> None:
    if not isinstance(value, list):
        _err(errors, field.key, "must be a list")
        return
    allowed = _option_values(field)
    # Pro Element auf str prüfen, bevor wir gegen die (str-)Optionsmenge testen –
    # sonst löst ein unhashbares Element (dict/list) einen TypeError → 500 aus.
    invalid = [v for v in value if not isinstance(v, str) or v not in allowed]
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
    # Engine-Decke (AUD-047): kein falsy-`or` — ein explizit konfiguriertes maxRows=0
    # (FieldValidation.max_rows hat ge=0, 0 ist gültig) MUSS erhalten bleiben und jede
    # Zeile ablehnen. Zugleich auf die Engine-Decke kappen, sodass ein vom Builder
    # gesetzter höherer Wert die obere Schranke nicht aushebeln kann.
    configured = (
        v.max_rows if (v is not None and v.max_rows is not None) else _DEFAULT_MAX_ROWS
    )
    max_rows = min(configured, _DEFAULT_MAX_ROWS)
    if len(value) > max_rows:
        _err(errors, field.key, f"has more than {max_rows} rows")
    for i, row in enumerate(value):
        if not isinstance(row, dict):
            _err(errors, field.key, f"row {i} must be an object")


# Default-Mindestzahl Vergleichsangebote je Position, falls der Builder nichts setzt.
_DEFAULT_MIN_OFFERS = 3
_DEFAULT_MIN_POSITIONS = 1

# Engine-Decken (#sec-audit AUD-047): obere Schranken für Positionen/Angebote/Tabellen-
# Zeilen, die auch OHNE Builder-Wert greifen — unabhängig vom Body-Cap. Verhindert, dass
# ein gehobener Body-Cap oder ein authentifizierter Write-Pfad unbegrenzt viele Positionen/
# Angebote durch `_validate_positions`/`positions_total`/JSONB-Persistenz schleust.
_DEFAULT_MAX_POSITIONS = 200
_DEFAULT_MAX_OFFERS = 50
_DEFAULT_MAX_ROWS = 1000


def _offer_value(offer: Mapping[str, Any]) -> Decimal | None:
    """Numerischen Angebots-Wert als ``Decimal`` ziehen (ungültig → ``None``)."""
    raw = offer.get("value")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        num = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return num if num.is_finite() else None


def _validate_positions(field: FormFieldDef, value: Any, errors: list[FieldError]) -> None:
    """Kostenpositionen prüfen: ≥ minPositions Positionen, je ≥ minOffers Angebote,
    genau ein bevorzugtes Angebot, alle Werte endliche Zahlen > 0 (Position 0-indiziert)."""
    if not isinstance(value, list):
        _err(errors, field.key, "must be a list of positions")
        return
    v = field.validation
    min_offers = (v.min_offers if v and v.min_offers else None) or _DEFAULT_MIN_OFFERS
    min_positions = (
        v.min_positions if v and v.min_positions else None
    ) or _DEFAULT_MIN_POSITIONS
    # Engine-Decke (AUD-047): max_positions/max_offers sind ge=1 (0 unmöglich), aber ein
    # form.configure-Admin könnte einen Wert über der Default-Decke setzen und so erneut
    # unbeschränktes Wachstum öffnen. Daher den konfigurierten Wert auf die Engine-Decke
    # kappen (min), statt ihn nur als Default einzusetzen.
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
        offers = pos.get("offers")
        if not isinstance(offers, list):
            _err(errors, where, "offers must be a list")
            continue
        if len(offers) < min_offers:
            _err(errors, where, f"needs at least {min_offers} comparison offer(s)")
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
    """Σ der bevorzugten Angebots-Werte aller Positionen (= Positions-Gesamtbetrag).

    ``None`` wenn keine gültige bevorzugte Position vorliegt (z. B. leere Liste).
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
        # `positions` promotet implizit den Positions-Gesamtbetrag in `amount`
        # (Σ der bevorzugten Angebote) — ohne isPromoted-Flag; additiv bei mehreren.
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
            # NaN/Infinity nie als amount weiterreichen (kracht sonst in T-12/T-17).
            if not num.is_finite():
                continue
            out[f.promote_target] = num
        else:
            out[f.promote_target] = value
    return out
