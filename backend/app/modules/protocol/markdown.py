"""Protokoll → Markdown + YAML-Frontmatter + Vote-Snippets (T-22, flows §7).

Reine, DB-freie Erzeugung (unit-testbar, Akzeptanzkriterium »build_markdown bettet
referenzierte Votes/Decisions korrekt ein«):

* :func:`build_protocol_document` legt das YAML-Frontmatter (``typ: protokoll``,
  ``gremium`` → pytex-Variante) **vor** den vom Editor gelieferten Markdown-Body.
* :func:`build_vote_snippet` rendert eine Abstimmung als Markdown-Abschnitt
  (Titel + Ergebnis + Stimmen), der beim Einbetten an den Body angehängt wird.

**Injection-Härtung** (security.md §2): das Ergebnis geht als HTTP-**Body** an den
pytex-Client (kein Shell). Frontmatter-Skalare werden YAML-quotiert; Snippet-Text
wird Markdown-escaped — beides wiederverwendet aus :mod:`app.modules.pdf.markdown`
(keine Duplikation). Der Editor-Body ist nutzer-geschrieben; :func:`sanitize_user_markdown`
entfernt vor der Ausgabe pytex' ``eval``-Escape (``[//]: # "EXPR"`` → RCE im Container)
sowie Bilder mit absolutem/``..``-Pfad. Normales Markdown (Überschriften, Listen,
Hervorhebung, echte Links/Bilder) bleibt erhalten. Dieser Sanitizer IST der
RCE-Schutz: der Service rendert den Body ``trusted`` (Client-Default), weil die
Protokoll-Variante pytex' Template-Maschinerie braucht — ``untrusted`` würde sie
sperren und jeden Render mit 400 abbrechen.

**Variante je Gremium** (flows §7): pytex kennt die Protokoll-Varianten
``protocol-stupa`` / ``protocol-asta``; die Gremium-``cd_variant`` wählt sie.
Für andere ``cd_variant`` bleibt die Variante ``None`` → pytex erkennt sie aus dem
``typ: protokoll``-Frontmatter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import time as _time

from app.modules.pdf.markdown import _md_escape, _yaml_scalar

# --- RCE-Defense-in-Depth (security.md §2) ----------------------------------
# pytex hat im ``trusted``-Modus einen Markdown-``eval``-Escape: eine Zeile der
# Form ``[//]: # "EXPR"`` (eine Markdown-Link-Referenz-Definition, die im PDF
# unsichtbar bleibt) führt ``eval(EXPR, {__builtins__})`` IM pytex-Container aus
# → Remote Code Execution. Der Body ist nutzer-geschrieben (Protokollant). Da die
# Protokoll-Variante pytex' Template-Maschinerie braucht (und deshalb ``trusted``
# gerendert wird — ``untrusted`` → 400), ist DIESER Sanitizer der RCE-Schutz: er
# entfernt den Konstrukt bedingungslos, bevor das Markdown pytex erreicht.
#
# Erkannte Varianten der Link-Referenz-Definition (führender Whitespace erlaubt):
#   [//]: # "EXPR"      [//]: # 'EXPR'      [//]: # (EXPR)      [//]: # EXPR
# ``//`` ist die Konvention für »Kommentar«; das Label ist case-insensitiv und der
# Doppelpunkt kann von beliebigem Whitespace gefolgt sein. Wir matchen defensiv
# JEDE ``[label]: # …``-Zeile (das ``#``-Ziel ist nie ein echter Link).
_EVAL_COMMENT_RE = re.compile(
    r"^[ \t]*\[[^\]]*\]:[ \t]*#.*$",
    re.MULTILINE,
)
# pytex' interner Marker für den ausgewerteten Ausdruck: ``\iffalse{pytex(...)}\fi``
# (LaTeX-``\iffalse``-Block, der die Auswertung kapselt). Im Editor-Body hat er
# nichts zu suchen → entfernen (auch mehrzeilig, non-greedy).
_PYTEX_IFFALSE_RE = re.compile(
    r"\\iffalse\s*\{?\s*pytex\s*\(.*?\)\s*\}?\s*\\fi",
    re.DOTALL | re.IGNORECASE,
)
# FIX 3 (Bild-Pfad-Traversal, narrow): Markdown-Bilder ``![alt](PFAD)`` mit
# absolutem (``/...``) oder ``../``-Traversal-Pfad könnten via ``\includegraphics``
# einen Container-Dateipfad referenzieren. pytex beschränkt zwar auf Bild-Endungen
# (Restrisiko gering), aber ein lesbares Bild außerhalb des Render-Verzeichnisses
# könnte exfiltriert werden. Solche Bild-Pfade werden zum Klartext-Platzhalter
# entschärft; relative In-Repo-Pfade bleiben unberührt.
_UNSAFE_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(\s*(?P<path>[^)\s]+)[^)]*\)",
)


def _is_unsafe_image_path(path: str) -> bool:
    """Bild-Pfad mit absolutem Root- oder ``..``-Traversal-Anteil? (FIX 3)."""
    if path.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:[\\/]", path):
        return True  # absolut (POSIX/UNC/Windows-Laufwerk)
    # ``../`` an beliebiger Stelle (auch URL-encoded ``%2e%2e``) ist Traversal.
    normalized = path.replace("\\", "/").lower()
    return "../" in normalized or "%2e%2e" in normalized


def _neutralize_unsafe_image(match: re.Match[str]) -> str:
    path = match.group("path")
    if not _is_unsafe_image_path(path):
        return match.group(0)  # harmloser relativer Pfad → unverändert
    alt = match.group("alt").strip() or "Bild"
    # Pfad NICHT durchreichen — als Klartext-Platzhalter entschärfen.
    return f"*[{_md_escape(alt)} (Bild entfernt)]*"


def sanitize_user_markdown(markdown: str) -> str:
    """Nutzer-Markdown von pytex-``eval``-Escapes (+ Pfad-Traversal-Bildern) befreien.

    Entfernt RCE-Vektoren (``[//]: # "…"``-Kommentar-Eval, ``\\iffalse{pytex(…)}\\fi``)
    und entschärft Bilder mit absolutem/``..``-Pfad (FIX 3). **Normales** Markdown
    (Überschriften, Listen, Hervorhebung, echte Links/Bilder mit relativem Pfad)
    bleibt vollständig erhalten."""
    cleaned = _PYTEX_IFFALSE_RE.sub("", markdown)
    cleaned = _EVAL_COMMENT_RE.sub("", cleaned)
    cleaned = _UNSAFE_IMAGE_RE.sub(_neutralize_unsafe_image, cleaned)
    return cleaned

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
    # Sitzungsende (#14, lokale Zeit) — aus ``meeting.closed_at``; mit Start ergibt
    # das die »Zeit: Start – Ende«-Titelseiten-Zeile (pytex ``beginn``/``ende``).
    end_time: _time | None = None
    protokollant: str | None = None
    present: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    datalines: list[str] = field(default_factory=list)
    # Beschlussfähigkeit (anwesende vs. aktive Mitglieder); None = keine Aussage.
    quorate: bool | None = None


# Unterschriften-Block (pytex ``signature_block_from_meta``): die Schriftführung
# zieht ihren Namen aus dem ``protokoll``-Frontmatter, der Vorstand bleibt eine
# Blanko-Linie zum handschriftlichen Unterschreiben (Vault-Konvention).
_SIGNATURES = ["Schriftführung", "Vorstand"]


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
    # Start/Ende (#14): pytex rendert daraus die »Zeit: Start – Ende«-Daten-Zeile.
    if doc.start_time is not None:
        lines.append(f"beginn: {_yaml_scalar(doc.start_time.strftime('%H:%M'))}")
    if doc.end_time is not None:
        lines.append(f"ende: {_yaml_scalar(doc.end_time.strftime('%H:%M'))}")
    if doc.protokollant:
        lines.append(f"protokoll: {_yaml_scalar(doc.protokollant)}")
    lines += _yaml_list("anwesend", doc.present)
    lines += _yaml_list("abwesend", doc.absent)
    if doc.quorate is not None:
        # Beschlussfähigkeit als Titelseiten-Daten-Zeile (#protocol-quorum) — der
        # pytex-Wrapper registriert den Key in der Daten-Zeilen-Tabelle.
        quorate = "Gegeben" if doc.quorate else "Nicht gegeben"
        lines.append(f"beschlussfaehigkeit: {_yaml_scalar(quorate)}")
    lines += _yaml_list("datalines", doc.datalines)
    # Unterschriften-Seite (pytex rendert die Signatur-Linien aus dieser Liste).
    lines += _yaml_list("unterschriften", _SIGNATURES)
    lines.append("---")
    return lines


def build_protocol_document(doc: ProtocolDoc) -> str:
    """Frontmatter + Editor-Body → finales Markdown (deterministisch).

    Der nutzer-geschriebene Body wird durch :func:`sanitize_user_markdown` von
    pytex-``eval``-Escapes (RCE, security.md §2) und Pfad-Traversal-Bildern befreit;
    normales Markdown bleibt verbatim. Frontmatter-Skalare bleiben YAML-quotiert.
    Der eval-Escape ist damit weg, bevor pytex den Body sieht; ``\\write18``-Shell-
    Escape greift unter der tectonic-Engine ohnehin nicht. Der Service rendert diesen
    Pfad ``trusted`` (Client-Default) — die Protokoll-Variante braucht pytex'
    Template-Maschinerie, die ``untrusted`` sperrt."""
    body = sanitize_user_markdown(doc.markdown).strip("\n")
    out = [*_frontmatter(doc), ""]
    if body:
        out.append(body)
    return "\n".join(out).rstrip() + "\n"


def build_vote_snippet(
    title: str,
    counts: dict[str, int] | None,
    question: str | None = None,
) -> str:
    """Eine Abstimmung als pytex-Protokoll-Callout (``> [!abstimmung]``) → eingebaute
    Vote-Tally-Box im PDF (statt einer Aufzählung). Die Stimmen-Zeile (``yes/no/abstain``
    bzw. ``ja/nein/enthaltung``) erkennt pytex und rendert die Zähl-Box. Alle Werte
    werden escaped; der Titel ist **fett** (#pdf-format). Eine separate
    »Ergebnis: …«-Zeile entfällt — das Ergebnis liest sich aus der Zähl-Box.

    Bleibt Teil des editierbaren Markdowns (Blockquote-Callout)."""
    head = question.strip() if question and question.strip() else title
    lines = [f"> [!abstimmung] **{_md_escape(head)}**"]
    if counts:
        # pytex erkennt die Tally-Zeile an ≥2 von ja/nein/enthaltung (yes/no/abstain) —
        # die Antrags-Optionen tragen genau diese Schlüssel.
        tally = ", ".join(f"{_md_escape(opt)}: {n}" for opt, n in counts.items())
        lines.append(f"> {tally}")
    return "\n".join(lines)


def demote_headings(markdown: str) -> str:
    """Alle ATX-Headings im TOP-Body **eine Ebene absenken** (#pdf-format).

    Die TOP-Überschrift selbst ist das einzige Top-Level-``#`` (pytex nummeriert
    sie als »TOP n«); vom Protokollanten im Body geschriebene ``#``-Headings
    würden sonst als eigene TOPs mitnummeriert. Code-Fences bleiben unberührt;
    Ebene 6 bleibt 6 (tiefer kennt Markdown nicht)."""
    out: list[str] = []
    in_fence = False
    for line in markdown.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        elif not in_fence and stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= hashes <= 5 and stripped[hashes : hashes + 1] in (" ", "\t"):
                line = line.replace("#", "##", 1)
        out.append(line)
    return "\n".join(out)
