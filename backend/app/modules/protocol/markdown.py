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

from dataclasses import dataclass, field
from datetime import date as _date
from datetime import time as _time

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
    gremium_name: str | None
    cd_variant: str | None
    date: _date | None
    markdown: str
    # Zusätzliche Titelseiten-/Header-Daten (#protocol-metadata, pytex-Protokoll-Header).
    start_time: _time | None = None
    protokollant: str | None = None
    present: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    datalines: list[str] = field(default_factory=list)


def _yaml_list(key: str, items: list[str]) -> list[str]:
    """YAML-Block-Liste (leere Liste ⇒ nichts) — Werte werden quotiert/escaped."""
    if not items:
        return []
    return [f"{key}:", *(f"  - {_yaml_scalar(i)}" for i in items)]


def _frontmatter(doc: ProtocolDoc) -> list[str]:
    lines = ["---", f"title: {_yaml_scalar(doc.title)}", "typ: protokoll"]
    if doc.gremium_name:
        lines.append(f"gremium: {_yaml_scalar(doc.gremium_name)}")
    if doc.cd_variant:
        lines.append(f"cd: {_yaml_scalar(doc.cd_variant)}")
    if doc.date is not None:
        # ``datum`` füllt den Protokoll-Header (Datum + Uhrzeit), ``date`` die
        # Report-Titelseite.
        datum = doc.date.isoformat()
        if doc.start_time is not None:
            datum = f"{datum} {doc.start_time.strftime('%H:%M')}"
        lines.append(f"datum: {_yaml_scalar(datum)}")
        lines.append(f"date: {_yaml_scalar(doc.date.isoformat())}")
    if doc.protokollant:
        lines.append(f"protokoll: {_yaml_scalar(doc.protokollant)}")
    lines += _yaml_list("anwesend", doc.present)
    lines += _yaml_list("abwesend", doc.absent)
    lines += _yaml_list("datalines", doc.datalines)
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
    """Eine Abstimmung als pytex-Protokoll-Callout (``> [!abstimmung]``) → eingebaute
    Vote-Tally-Box im PDF (statt einer Aufzählung). Die Stimmen-Zeile (``yes/no/abstain``
    bzw. ``ja/nein/enthaltung``) erkennt pytex und rendert die Zähl-Box; die übrigen
    Zeilen (Beschlussfrage/Ergebnis) bleiben Box-Text. Alle Werte werden escaped.

    Bleibt Teil des editierbaren Markdowns (Blockquote-Callout)."""
    head = question.strip() if question and question.strip() else title
    lines = [f"> [!abstimmung] {_md_escape(head)}"]
    if result:
        lines.append(f"> Ergebnis: {_md_escape(result)}")
    if counts:
        # pytex erkennt die Tally-Zeile an ≥2 von ja/nein/enthaltung (yes/no/abstain) —
        # die Antrags-Optionen tragen genau diese Schlüssel.
        tally = ", ".join(f"{_md_escape(opt)}: {n}" for opt, n in counts.items())
        lines.append(f"> {tally}")
    return "\n".join(lines)
