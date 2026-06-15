"""Antrag → Markdown + YAML-Frontmatter (T-20, flows §6).

Reine, DB-freie Erzeugung: der :class:`ApplicationDoc` trägt alles, was das Dokument
braucht (Felder + Werte + Verlauf + ggf. Abstimmungsergebnis); :func:`build_application_markdown`
formt daraus Markdown mit Frontmatter. So ist die Generierung unit-testbar (Akzeptanz)
und der Worker hält nur das Laden aus der DB.

**Keine Injection**: das Ergebnis wird als HTTP-**Body** an den pytex-Client übergeben
(kein Shell-Aufruf). Frontmatter-Skalare werden defensiv YAML-quotiert, damit ein
Feldwert mit ``:`` / Zeilenumbruch / ``---`` weder das Frontmatter sprengt noch eine
neue Direktive einschleust.

**Variante je Gremium** (flows §6): pytex kennt für Anträge die Report-Varianten
``report`` / ``report-makers``; die Gremium-``cd_variant`` (stupa/asta/echo/makers/report)
wählt sie aus, die Marke selbst trägt das ``gremium``-Frontmatter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.shared.config_schemas import FormFieldDef
from app.shared.i18n import resolve_i18n

# cd_variant → pytex-Render-Variante (Antrags-Report). Default: "report".
_VARIANT_MAP = {"makers": "report-makers"}
DEFAULT_VARIANT = "report"


def variant_for(cd_variant: str | None) -> str:
    """Gremium-``cd_variant`` → pytex-``variant`` (Antrags-Report)."""
    if cd_variant is None:
        return DEFAULT_VARIANT
    return _VARIANT_MAP.get(cd_variant, DEFAULT_VARIANT)


@dataclass(slots=True)
class TimelineItem:
    """Ein Status-Verlaufseintrag (Zeitpunkt + Ziel-Status + optional Notiz)."""

    at: datetime
    state_label: str
    note: str | None = None


@dataclass(slots=True)
class VoteResult:
    """Verdichtetes Abstimmungsergebnis (optional; nur wenn vorhanden)."""

    title: str
    result: str
    counts: dict[str, int] | None = None


@dataclass(slots=True)
class ApplicationDoc:
    """Alle Daten für ein Antrags-PDF — vom Service aus der DB befüllt."""

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
    """String als sicheres, doppelt-quotiertes YAML-Skalar (keine Direktiven-Injection)."""
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
    """Feldwert für die Markdown-Liste rendern (Liste → Komma-getrennt; None → »—«)."""
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "ja" if value else "nein"
    if isinstance(value, list):
        parts = [_format_value(v) for v in value]  # type: ignore[arg-type]
        return ", ".join(p for p in parts if p != "—") or "—"
    if isinstance(value, dict):
        # Verschachtelte Strukturen kompakt + flach darstellen (kein Markdown-Bruch).
        return ", ".join(f"{k}: {_format_value(v)}" for k, v in value.items())  # type: ignore[arg-type]
    return str(value)


def _md_escape(text: str) -> str:
    """Minimal-Escape für Markdown-Inline-Text (Zeilenumbruch → Leerzeichen)."""
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


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
    """Antrags-Dokument als Markdown + Frontmatter (deterministisch, injection-sicher)."""
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
            continue  # PII bleibt im `applicant`-Record, nicht im Gremium-PDF.
        label = resolve_i18n(f.label, lang, default) or f.key
        value = _format_value(doc.data.get(f.key))
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
