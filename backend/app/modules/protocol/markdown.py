"""Protokoll → Markdown + YAML-Frontmatter + Vote-Snippets (T-22, flows §7).

Reine, DB-freie Erzeugung (unit-testbar, Akzeptanzkriterium »build_markdown bettet
referenzierte Votes/Decisions korrekt ein«):

* :func:`build_protocol_document` legt das YAML-Frontmatter (``typ: protokoll``,
  ``gremium`` → pytex-Variante) **vor** den vom Editor gelieferten Markdown-Body.
* :func:`build_vote_snippet` rendert eine Abstimmung als Markdown-Abschnitt
  (Titel + Ergebnis + Stimmen), der beim Einbetten an den Body angehängt wird.

**Keine Injection** (security.md §2): das Ergebnis geht als HTTP-**Body** an den
pytex-Client (kein Shell). Frontmatter-Skalare werden YAML-quotiert; Snippet-Text
wird Markdown-escaped — beides wiederverwendet aus :mod:`app.modules.pdf.markdown`
(keine Duplikation). Der Editor-Body bleibt bewusst **verbatim** (es ist genau das
vom Protokollanten geschriebene Markdown, das pytex rendern soll).

**Variante je Gremium** (flows §7): pytex kennt die Protokoll-Varianten
``protocol-stupa`` / ``protocol-asta``; die Gremium-``cd_variant`` wählt sie.
Für andere ``cd_variant`` bleibt die Variante ``None`` → pytex erkennt sie aus dem
``typ: protokoll``-Frontmatter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date

from app.modules.pdf.markdown import _md_escape, _yaml_scalar

# Gremium-``cd_variant`` → pytex-Protokoll-Variante (flows §7).
_PROTOCOL_VARIANTS = {"stupa", "asta"}


def protocol_variant_for(cd_variant: str | None) -> str | None:
    """``cd_variant`` → pytex-``variant`` (``protocol-<cd>``) oder ``None`` (Auto)."""
    if cd_variant in _PROTOCOL_VARIANTS:
        return f"protocol-{cd_variant}"
    return None


@dataclass(slots=True)
class ProtocolDoc:
    """Alle Kopf-Daten eines Protokolls (vom Service aus der DB befüllt)."""

    title: str
    gremium_slug: str | None
    cd_variant: str | None
    date: _date | None
    markdown: str


def _frontmatter(doc: ProtocolDoc) -> list[str]:
    lines = ["---", f"title: {_yaml_scalar(doc.title)}", "typ: protokoll"]
    if doc.gremium_slug:
        lines.append(f"gremium: {_yaml_scalar(doc.gremium_slug)}")
    if doc.cd_variant:
        lines.append(f"cd: {_yaml_scalar(doc.cd_variant)}")
    if doc.date is not None:
        lines.append(f"date: {_yaml_scalar(doc.date.isoformat())}")
    lines.append("---")
    return lines


def build_protocol_document(doc: ProtocolDoc) -> str:
    """Frontmatter + Editor-Body → finales Markdown (deterministisch, injection-sicher)."""
    body = doc.markdown.strip("\n")
    out = [*_frontmatter(doc), ""]
    if body:
        out.append(body)
    return "\n".join(out).rstrip() + "\n"


def build_vote_snippet(
    title: str,
    result: str | None,
    counts: dict[str, int] | None,
    question: str | None = None,
) -> str:
    """Eine Abstimmung als Markdown-Snippet (Titel + Beschlussfrage + Ergebnis + Stimmen).

    Wird beim Einbetten an den Protokoll-Body angehängt; bleibt damit Teil des vom
    Protokollanten editierbaren Markdowns. Alle Werte werden Markdown-escaped."""
    lines = [f"### {_md_escape(title)}", ""]
    if question and question.strip():
        lines.append(f"**Beschlussfrage:** {_md_escape(question.strip())}")
        lines.append("")
    lines.append(f"- **Ergebnis:** {_md_escape(result) if result else '—'}")
    if counts:
        rendered = ", ".join(f"{_md_escape(opt)}: {n}" for opt, n in counts.items())
        lines.append(f"- **Stimmen:** {rendered}")
    return "\n".join(lines)
