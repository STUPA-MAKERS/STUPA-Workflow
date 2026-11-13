"""Build the Markdown of an Antrag PDF for the typst render service.

The function here is pure: the service collects the data, and this module turns it into
the Markdown with a YAML frontmatter that the render service prints in the protocol
design. The frontmatter key `typ: antrag` tells the render service that the document has
no title page and that the headings are form sections, so they get no "TOP n" number.

The whole Antrag is tables of two columns, label and value (spec 000881). Dates, the
version, an IBAN, amounts and the file names (one per line) are inline code, so they
print in the monospace font. Each row is a
field row of the render service, `> [!feld] Label` with the value as block Markdown in the
same quote; rows that follow each other form one table. The document holds, in this
order: the head data, one table per form section with the answers, the answers without
a field, the names of the attached files and the valid decision. It never holds comments
or the status history, because the PDF shows the Antrag as the Gremium reads it.

Three markers change an answer:

* A key in `hidden_keys` is a field that the reader may not read. The server removed
  its value, so the PDF prints `(nicht sichtbar)` instead.
* A key in `redacted_keys` is a field of the public protocol Anlage that carries
  personal data. The PDF prints the black bar `%%%%` of the render service instead.
* `redact_applicant` prints the black bar instead of the applicant.

Every answer is user text. A one-line answer is escaped, so a `*`, a `#` or a `[` prints
as text. A `textarea` answer stays Markdown and renders in its cell, as on the detail
page. Only the constructs that would act on the document are neutralized: a heading
prints as a bold line, because a heading inside a cell would break the section
structure; an image, a callout marker, a shortcode, a formula and a link to an embedded
PDF print as text. Every `%%` is broken, so an answer never turns into a black bar or
hides text.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Final

from app.shared.config_schemas import FormFieldDef
from app.shared.i18n import resolve_i18n
from app.shared.jsonlogic import JsonLogicError, eval_jsonlogic
from app.shared.money import format_money

LANG: Final = "de"
"""The language of the PDF: the protocol design is German."""

BAR: Final = "%%%%"
"""The empty blackout marker. The render service prints it as a black bar."""

NOT_VISIBLE: Final = "(nicht sichtbar)"
"""The text of an answer that the reader may not read."""

#: Field types that the PDF never shows as an answer: display text, step markers and
#: files. The files show by name in their own part.
_NOT_SHOWN: Final[frozenset[str]] = frozenset({"markdown", "section", "file"})

#: The keys that the head shows, so the answers leave them out.
_HEAD_KEYS: Final[frozenset[str]] = frozenset({"title"})

_ESCAPED: Final[re.Pattern[str]] = re.compile(r"([\\`*_\[\]{}()#+\-.!|<>~$])")
_HEADING: Final[re.Pattern[str]] = re.compile(
    r"^ {0,3}#{1,6}(?:[ \t]+(.*?))?[ \t#]*$", re.MULTILINE
)
_NEUTRAL: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"!\["), r"\\!["),
    (re.compile(r"\[!"), r"\\[!"),
    (re.compile(r"\$"), r"\\$"),
    (re.compile(r"\{\{"), "{\u2060{"),
    (re.compile(r"/api/media/documents/"), "/api/media/documents\u2060/"),
)
_MAIL: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+")
_ISO_DAY: Final[re.Pattern[str]] = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


@dataclass(frozen=True, slots=True)
class FormSection:
    """One section of the form: its label and its fields in form order."""

    label: str
    fields: Sequence[FormFieldDef]


@dataclass(frozen=True, slots=True)
class DecisionView:
    """The valid decision as the PDF prints it.

    Attributes:
        approved_amount: The approved amount, or `None` for "as requested".
        conditions: The conditions of the decision, in order.
        decided_at: When the decision was made.
        gremium_name: The Gremium whose vote made the decision. `None` for a decision
            without a vote. It is the only place where the PDF names a Gremium.
        result: The result of the vote as text ("Angenommen", "Abgelehnt"), or `None`
            for a decision without a vote.
        approved: The decision approves the Antrag, so it has an approved amount. A
            rejected vote has none.
    """

    approved_amount: Decimal | None
    conditions: Sequence[str]
    decided_at: datetime
    gremium_name: str | None = None
    result: str | None = None
    approved: bool = True


@dataclass(frozen=True, slots=True)
class ApplicationDoc:
    """Everything that the Antrag PDF prints.

    Attributes:
        title: The title of the Antrag (the system title of the form).
        type_name: The name of the Antragsart.
        gremium_name: The Gremium of the Antrag, for the design of the PDF. The PDF does
            not print it.
        cd_variant: The design key of the Gremium, for the logos.
        state_label: The current status, or `None` to leave it out (the protocol Anlage).
        received_on: The date of receipt.
        applicant: The name of the applicant, or `None` when it is unknown or the reader
            may not see it.
        applicant_email: The e-mail of the applicant, or `None` likewise. It prints on
            its own line below the name, in the monospace font.
        version: The version number of the answers.
        sections: The form sections with their fields.
        data: The answers.
        context: More variables for `visibleIf` and `compute`, for example `has_budget`.
        currency: The currency of the amounts.
        hidden_keys: Fields that the reader may not read.
        redacted_keys: Fields that print as a black bar.
        redact_applicant: The applicant prints as a black bar.
        files: The names of the attached files.
        decision: The valid decision, or `None`.
        signatures: The PDF ends with the signature section (spec 000888).
    """

    title: str
    type_name: str | None
    gremium_name: str | None
    cd_variant: str | None
    state_label: str | None
    received_on: date | None
    applicant: str | None
    version: int
    sections: Sequence[FormSection]
    data: Mapping[str, object]
    context: Mapping[str, object] = field(default_factory=dict[str, object])
    currency: str = "EUR"
    applicant_email: str | None = None
    hidden_keys: frozenset[str] = frozenset()
    redacted_keys: frozenset[str] = frozenset()
    redact_applicant: bool = False
    files: Sequence[str] = ()
    decision: DecisionView | None = None
    signatures: bool = False


def _yaml_scalar(value: str) -> str:
    """Quote a value as a double-quoted YAML scalar."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + " ".join(escaped.split()) + '"'


def _unbar(text: str) -> str:
    """Break every `%%`, so user text never forms a blackout marker."""
    return text.replace("%%", "%⁠%")


def escape(text: str) -> str:
    """Escape user text for an inline Markdown run: one line, no markup, no marker."""
    return _unbar(_ESCAPED.sub(r"\\\1", " ".join(text.split())))


def _bold_heading(match: re.Match[str]) -> str:
    """Write a heading line as a bold line; an empty heading drops."""
    title = (match[1] or "").strip()
    return f"**{title}**" if title else ""


def code(text: str) -> str:
    """Write a value as inline code, in the monospace font: one line, no backtick."""
    return _unbar("`" + " ".join(text.replace("`", "'").split()) + "`")


def mail_link(address: str) -> str:
    """Write an e-mail address in the monospace font, as a `mailto:` link.

    An address with a character that could end the link target prints without the link.
    """
    plain = address.strip()
    return f"[{code(plain)}](mailto:{plain})" if _MAIL.fullmatch(plain) else code(plain)


def _lines(values: Sequence[str]) -> list[str]:
    """Join values one per line: each line but the last ends with a hard break."""
    return [f"{value}\\" for value in values[:-1]] + list(values[-1:])


def markdown_text(text: str) -> str:
    """Keep a textarea answer as Markdown, without the constructs that act on the document.

    A heading turns into a bold line; an image, a callout marker, a shortcode, a formula
    and a link to an embedded PDF print as text.
    """
    bold = _HEADING.sub(_bold_heading, text.strip())
    return _unbar(functools.reduce(lambda acc, rule: rule[0].sub(rule[1], acc), _NEUTRAL, bold))


def format_day(value: date | str) -> str:
    """Write a date as `TT.MM.JJJJ`. A string that is no ISO day stays as it is."""
    match value:
        case date():
            return value.strftime("%d.%m.%Y")
        case str():
            found = _ISO_DAY.fullmatch(value.strip()[:10])
            return f"{found[3]}.{found[2]}.{found[1]}" if found else value


def _money(value: object, currency: str) -> str | None:
    """Write an amount, or `None` when the value is no number."""
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return format_money(amount, currency, LANG) if amount.is_finite() else None


def _plain(value: object) -> str:
    """Write a value without a field definition."""
    match value:
        case bool():
            return "Ja" if value else "Nein"
        case float() if value.is_integer():
            return str(int(value))
        case str() | int() | float() | Decimal():
            return str(value)
        case list() | tuple():
            return ", ".join(_plain(v) for v in value)
        case Mapping():
            return ", ".join(f"{k}: {_plain(v)}" for k, v in value.items())
        case _:
            return ""


def is_empty(value: object) -> bool:
    """Tell whether an answer counts as not given. `False` and `0` are answers."""
    match value:
        case None:
            return True
        case str():
            return not value.strip()
        case list() | tuple():
            return not value
        case Mapping():
            return all(is_empty(v) for v in value.values())
        case _:
            return False


def _option(fdef: FormFieldDef, value: object) -> str:
    """Return the label of the option of a value, or the value when the option is gone."""
    label = next(
        (resolve_i18n(o.label, LANG) for o in fdef.options or () if o.value == value), None
    )
    return label or _plain(value)


def _daterange(value: object) -> str:
    """Write a range `{from, to}` as `from – to`, or the half it has."""
    ends = [value.get("from"), value.get("to")] if isinstance(value, Mapping) else []
    days = [format_day(e) for e in ends if isinstance(e, str) and e.strip()]
    return " – ".join(days) if days else _plain(value)


def format_answer(fdef: FormFieldDef, value: object, currency: str) -> str:
    """Write one answer as the text that the detail page shows."""
    match fdef.type:
        case "checkbox":
            return _plain(value)
        case "date":
            return format_day(value) if isinstance(value, str) else _plain(value)
        case "daterange":
            return _daterange(value)
        case "select" | "gremium_select" | "budget_select":
            return _option(fdef, value)
        case "multiselect":
            items = value if isinstance(value, list) else [value]
            return ", ".join(_option(fdef, v) for v in items)
        case "currency" | "funding":
            return _money(value, currency) or _plain(value)
        case _:
            return _plain(value)


def _computed(fdef: FormFieldDef, data: Mapping[str, object], ctx: dict[str, object]) -> object:
    """Return the stored value of a computed field, else its computed value."""
    stored = data.get(fdef.key)
    if not is_empty(stored) or fdef.compute is None:
        return stored
    try:
        return eval_jsonlogic(fdef.compute, ctx)
    except JsonLogicError:
        return None


def _visible(fdef: FormFieldDef, ctx: dict[str, object]) -> bool:
    """Evaluate `visibleIf`. An error counts as visible, as in the validation."""
    if fdef.visible_if is None:
        return True
    try:
        return bool(eval_jsonlogic(fdef.visible_if, ctx))
    except JsonLogicError:
        return True


def field_row(label: str, value: Sequence[str]) -> list[str]:
    """Write one table row: the escaped label and the value lines as block Markdown."""
    quoted = [f"> {line}" if line else ">" for line in value]
    return [f"> [!feld] {escape(label)}", ">", *quoted, ""]


def _table(value: object) -> list[str]:
    """Write a table answer as a GFM table, or as text when it is no list of rows."""
    rows = value if isinstance(value, list) else []
    objects = [r for r in rows if isinstance(r, Mapping)]
    if not objects or len(objects) != len(rows):
        return [escape(_plain(value))]
    columns = list(dict.fromkeys(str(k) for r in objects for k in r))
    return [
        "| " + " | ".join(escape(c) for c in columns) + " |",
        "|" + "---|" * len(columns),
        *("| " + " | ".join(escape(_plain(r.get(c))) for c in columns) + " |" for r in objects),
    ]


def _offers(position: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = position.get("offers")
    return [o for o in raw if isinstance(o, Mapping)] if isinstance(raw, list) else []


def _preferred_value(position: Mapping[str, object]) -> Decimal:
    """Return the value of the preferred offer of a position, else 0."""
    offer = next((o for o in _offers(position) if o.get("preferred") is True), None)
    try:
        return Decimal(str(offer.get("value"))) if offer is not None else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def _position_rows(index: int, position: Mapping[str, object], currency: str) -> list[str]:
    """Write the table rows of one position: one row per offer, the preferred marked."""
    label = escape(_plain(position.get("label")) or f"Position {index}")
    offers = _offers(position)
    reason = _plain(position.get("noOffersReason"))
    offer_rows = [
        "| {pos} | {name}{pref} | {amount} |".format(
            pos=label if n == 0 else "",
            name=escape(_plain(o.get("label")) or "—"),
            pref=" (bevorzugt)" if o.get("preferred") is True else "",
            amount=code(money) if (money := _money(o.get("value"), currency)) else "",
        )
        for n, o in enumerate(offers)
    ]
    no_offers = (
        [f"| | Keine Vergleichsangebote: {escape(reason)} | |"]
        if position.get("noOffers") is True and reason
        else []
    )
    return [*(offer_rows or [f"| {label} | — | |"]), *no_offers]


def positions_block(value: object, currency: str) -> list[str]:
    """Write the Kostenaufstellung as a table with the total of the preferred offers."""
    positions = [p for p in value if isinstance(p, Mapping)] if isinstance(value, list) else []
    total = sum((_preferred_value(p) for p in positions), Decimal(0))
    return [
        "| Position | Angebot | Betrag |",
        "|---|---|---:|",
        *(row for n, p in enumerate(positions, start=1) for row in _position_rows(n, p, currency)),
        f"| **Summe** | | **{code(format_money(total, currency, LANG))}** |",
    ]


def _answer_value(doc: ApplicationDoc, fdef: FormFieldDef, value: object) -> list[str]:
    """Write the value lines of one given answer."""
    match fdef.type:
        case "positions":
            return positions_block(value, doc.currency)
        case "table":
            return _table(value)
        case "textarea":
            return markdown_text(_plain(value)).splitlines()
        case "date" | "daterange" | "iban" | "currency" | "funding":
            return [code(format_answer(fdef, value, doc.currency))]
        case _:
            return [escape(format_answer(fdef, value, doc.currency))]


def _answer_lines(doc: ApplicationDoc, fdef: FormFieldDef, ctx: dict[str, object]) -> list[str]:
    """Write the row of one shown field, or nothing for an empty answer."""
    label = resolve_i18n(fdef.label, LANG) or fdef.key
    value = _computed(fdef, doc.data, ctx) if fdef.type == "computed" else doc.data.get(fdef.key)
    if fdef.key in doc.hidden_keys:
        return field_row(label, [NOT_VISIBLE])
    if is_empty(value):
        return []
    if fdef.key in doc.redacted_keys:
        return field_row(label, [BAR])
    return field_row(label, _answer_value(doc, fdef, value))


def _shown(fdef: FormFieldDef, ctx: dict[str, object]) -> bool:
    return fdef.key not in _HEAD_KEYS and fdef.type not in _NOT_SHOWN and _visible(fdef, ctx)


def _section_lines(doc: ApplicationDoc, section: FormSection, ctx: dict[str, object]) -> list[str]:
    """Write one section: its heading and its table, or nothing without an answer."""
    body = [
        line
        for fdef in section.fields
        if _shown(fdef, ctx)
        for line in _answer_lines(doc, fdef, ctx)
    ]
    return [f"# {escape(section.label)}", "", *body] if body else []


def _other_lines(doc: ApplicationDoc) -> list[str]:
    """Write the answers without a field: they come from an older form version."""
    known = {f.key for s in doc.sections for f in s.fields}
    skipped = known | _HEAD_KEYS | doc.hidden_keys
    rows = [
        line
        for key, value in doc.data.items()
        if key not in skipped and not is_empty(value)
        for line in field_row(key, [BAR if key in doc.redacted_keys else escape(_plain(value))])
    ]
    return ["# Weitere Angaben", "", *rows] if rows else []


#: The signature rows of the Antrag PDF: the label and the signer (spec 000888).
SIGNATURES: Final[tuple[tuple[str, str], ...]] = (
    ("Sachlich richtig", "Finanzreferent:in"),
    ("Ausführungsermächtigt", "Haushaltsbeauftragte:r"),
)


def signature_row(label: str, signer: str) -> list[str]:
    """Write one signature row of the render service: room to sign by hand."""
    return [f"> [!unterschrift] {escape(label)}", ">", f"> {escape(signer)}", ""]


def signature_lines() -> list[str]:
    """Write the signature section: one row per signer, to fill in by hand."""
    rows = [line for label, signer in SIGNATURES for line in signature_row(label, signer)]
    return ["# Unterschriften", "", *rows]


def _decision_lines(doc: ApplicationDoc) -> list[str]:
    """Write the valid decision: the approved amount and the conditions."""
    decision = doc.decision
    if decision is None:
        return []
    amount = (
        "wie beantragt"
        if decision.approved_amount is None
        else code(format_money(decision.approved_amount, doc.currency, LANG))
    )
    # One paragraph per condition, with a rule between two: the render service draws
    # it as the dashed rule of the table rows.
    conditions = [
        line
        for n, text in enumerate(decision.conditions)
        for line in ([*(["", "---", ""] if n else []), escape(text)])
    ]
    return [
        "# Beschluss",
        "",
        *(field_row("Gremium", [escape(decision.gremium_name)]) if decision.gremium_name else []),
        *field_row("Beschlossen am", [code(format_day(decision.decided_at.date()))]),
        *(field_row("Ergebnis", [escape(decision.result)]) if decision.result else []),
        *(field_row("Bewilligter Betrag", [amount]) if decision.approved else []),
        *(field_row("Auflagen", conditions) if conditions else []),
    ]


def _head_lines(doc: ApplicationDoc) -> list[str]:
    """Write the head data as the first table, the file names last."""
    known = [
        *([escape(doc.applicant)] if doc.applicant else []),
        *([mail_link(doc.applicant_email)] if doc.applicant_email else []),
    ]
    applicant = [BAR] if doc.redact_applicant else _lines(known)
    rows = (
        ("Antragsart", [escape(doc.type_name)] if doc.type_name else []),
        ("Status", [escape(doc.state_label)] if doc.state_label else []),
        ("Eingang", [code(format_day(doc.received_on))] if doc.received_on else []),
        ("Antragsteller", applicant),
        ("Version", [code(str(doc.version))]),
    )
    files = _lines([code(name) for name in doc.files])
    return [
        *(line for label, value in rows if value for line in field_row(label, value)),
        *(field_row("Anhänge", files) if files else []),
    ]


def _frontmatter(doc: ApplicationDoc) -> list[str]:
    return [
        "---",
        f"title: {_yaml_scalar(_unbar(doc.title or 'Antrag'))}",
        "typ: antrag",
        *([f"gremium: {_yaml_scalar(doc.gremium_name)}"] if doc.gremium_name else []),
        *([f"cd: {_yaml_scalar(doc.cd_variant)}"] if doc.cd_variant else []),
        "---",
    ]


def build_application_document(doc: ApplicationDoc) -> str:
    """Build the Markdown of the Antrag PDF: the frontmatter and the body."""
    ctx: dict[str, object] = {**doc.context, **doc.data}
    body = [
        *_head_lines(doc),
        *(line for section in doc.sections for line in _section_lines(doc, section, ctx)),
        *_other_lines(doc),
        *_decision_lines(doc),
        *(signature_lines() if doc.signatures else []),
    ]
    return "\n".join([*_frontmatter(doc), "", *body]).rstrip() + "\n"


def anlage_link(title: str, document_path: str) -> str:
    """Write the reference of an Antrag Anlage below its TOP heading.

    The render service turns a link to an embedded PDF with its asset into
    `Anlage <N>: Antrag <Titel> (Seite <P>)` and appends the PDF as an Anlage.
    """
    return f"[Antrag {escape(title or 'ohne Titel')}]({document_path})"
