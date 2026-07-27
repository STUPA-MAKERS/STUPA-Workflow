"""Application → Markdown + YAML frontmatter.

The generation is pure and needs no DB. ``ApplicationDoc`` carries everything the
document needs: fields, values, timeline and an optional vote result.
``build_application_markdown`` turns the document into Markdown with frontmatter. This
split keeps the generation unit-testable and leaves the DB load to the worker.

Nothing can inject here. The caller passes the result to the pytex client as an HTTP
body, never as a shell command. This module quotes frontmatter scalars defensively as
YAML. A field value that holds a ``:``, a newline or ``---`` can therefore neither
break the frontmatter nor inject a directive.

Per-gremium variant: pytex offers the ``report`` and ``report-makers`` variants for
applications. The gremium ``cd_variant`` selects one of them. The ``gremium``
frontmatter key carries the brand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.shared.config_schemas import FormFieldDef
from app.shared.i18n import resolve_i18n

# cd_variant → pytex render variant (application report). Default: "report".
_VARIANT_MAP = {"makers": "report-makers"}
DEFAULT_VARIANT = "report"


def variant_for(cd_variant: str | None) -> str:
    """Gremium ``cd_variant`` → pytex ``variant`` (application report)."""
    if cd_variant is None:
        return DEFAULT_VARIANT
    return _VARIANT_MAP.get(cd_variant, DEFAULT_VARIANT)


@dataclass(slots=True)
class TimelineItem:
    """One status-timeline entry (time + target state + optional note)."""

    at: datetime
    state_label: str
    note: str | None = None


@dataclass(slots=True)
class VoteResult:
    """Condensed vote result, present only when the application has one."""

    title: str
    result: str
    counts: dict[str, int] | None = None


@dataclass(slots=True)
class ApplicationDoc:
    """All data for an application PDF. The service fills it from the DB."""

    application_id: str
    type_name: str
    gremium_slug: str | None
    cd_variant: str | None
    lang: str
    default_lang: str
    fields: list[FormFieldDef]
    data: dict[str, object]
    applicant_name: str | None = None
    created_at: datetime | None = None
    timeline: list[TimelineItem] = field(default_factory=list)
    vote: VoteResult | None = None

    @property
    def variant(self) -> str:
        return variant_for(self.cd_variant)


def _yaml_scalar(value: str) -> str:
    """Quote a string as a safe double-quoted YAML scalar that cannot inject a directive."""
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _format_value(value: object) -> str:
    """Render a field value for the Markdown list.

    A list becomes a comma-joined string. An empty value and ``None`` become an em dash.
    """
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "ja" if value else "nein"
    if isinstance(value, list):
        parts = [_format_value(v) for v in value]  # type: ignore[arg-type]
        return ", ".join(p for p in parts if p != "—") or "—"
    if isinstance(value, dict):
        # Flat and compact, so a nested structure cannot break the Markdown list.
        return ", ".join(f"{k}: {_format_value(v)}" for k, v in value.items())  # type: ignore[arg-type]
    return str(value)


def _md_escape(text: str) -> str:
    """Minimal escape for inline Markdown text (newline → space)."""
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _sanitize_applicant_value(text: str) -> str:
    """Neutralize RCE and traversal in an applicant field value before Markdown use.

    Applications render ``trusted``, because the ``report`` variant needs the pytex
    template machinery. Field values come from the public applicant input, which is the
    least trusted path. ``_md_escape`` collapses newlines. It does NOT neutralize the
    pytex ``eval`` escape (``[//]: # "EXPR"``) or image-path traversal (``![a](/abs)``,
    ``![a](../x)``). The value therefore goes through the same
    ``sanitize_user_markdown`` that hardens the protocol body. The function-local
    import breaks the module cycle, because ``protocol.markdown`` in turn imports
    ``_md_escape`` and ``_yaml_scalar`` from here.
    """
    from app.modules.protocol.markdown import sanitize_user_markdown

    return sanitize_user_markdown(text)


def _frontmatter(doc: ApplicationDoc) -> list[str]:
    lines = ["---"]
    title = f"{doc.type_name}"
    if doc.applicant_name:
        title = f"{doc.type_name} — {doc.applicant_name}"
    lines.append(f"title: {_yaml_scalar(title)}")
    lines.append("typ: antrag")
    if doc.gremium_slug:
        lines.append(f"gremium: {_yaml_scalar(doc.gremium_slug)}")
    if doc.cd_variant:
        lines.append(f"cd: {_yaml_scalar(doc.cd_variant)}")
    if doc.created_at is not None:
        lines.append(f"date: {_yaml_scalar(doc.created_at.date().isoformat())}")
    lines.append(f"lang: {_yaml_scalar(doc.lang)}")
    lines.append("---")
    return lines


def build_application_markdown(doc: ApplicationDoc) -> str:
    """Build the application Markdown with frontmatter (deterministic, injection-safe)."""
    lang, default = doc.lang, doc.default_lang
    out: list[str] = []
    out.extend(_frontmatter(doc))
    out.append("")

    heading = doc.type_name
    if doc.applicant_name:
        heading = f"{doc.type_name} — {doc.applicant_name}"
    out.append(f"# {_md_escape(heading)}")
    out.append("")

    out.append("## Antragsdaten")
    out.append("")
    for f in doc.fields:
        if f.is_pii:
            continue  # PII stays in the applicant record, not in the gremium PDF.
        label = resolve_i18n(f.label, lang, default) or f.key
        value = _sanitize_applicant_value(_format_value(doc.data.get(f.key)))
        out.append(f"- **{_md_escape(label)}:** {_md_escape(value)}")
    out.append("")

    if doc.vote is not None:
        out.append("## Abstimmung")
        out.append("")
        out.append(f"- **{_md_escape(doc.vote.title)}:** {_md_escape(doc.vote.result)}")
        if doc.vote.counts:
            counts = ", ".join(f"{k}: {v}" for k, v in doc.vote.counts.items())
            out.append(f"- Stimmen: {_md_escape(counts)}")
        out.append("")

    if doc.timeline:
        out.append("## Verlauf")
        out.append("")
        for item in doc.timeline:
            stamp = item.at.date().isoformat()
            line = f"- {stamp} — {_md_escape(item.state_label)}"
            if item.note:
                line += f" ({_md_escape(item.note)})"
            out.append(line)
        out.append("")

    return "\n".join(out).rstrip() + "\n"
