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
entschärft vor der Ausgabe pytex' ``eval``-Escape (``[//]: # "EXPR"`` → RCE im Container)
in JEDER CommonMark-Form (ein-/mehrzeilig, container-verschachtelt, Whitespace im
Label) sowie Bilder mit absolutem/``..``-Pfad. Normales Markdown (Überschriften, Listen,
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

try:  # marko ist (über pytex_markdown) im Render-Pfad vorhanden; optional gehärtet.
    import marko as _marko
except ImportError:  # pragma: no cover - Primärschutz (Regex) bleibt ohne marko aktiv
    _marko = None  # type: ignore[assignment]

from app.modules.pdf.markdown import _md_escape, _yaml_scalar

# --- RCE-Defense-in-Depth (security.md §2) ----------------------------------
# pytex hat im ``trusted``-Modus einen Markdown-``eval``-Escape: eine
# Link-Referenz-Definition der Form ``[//]: # "EXPR"`` (im PDF unsichtbar) führt
# ``eval(EXPR, pytex_namespace())`` IM pytex-Container aus → Remote Code Execution.
# pytex feuert das eval AUSSCHLIESSLICH, wenn CommonMark die Definition mit
# ``label == "//"`` UND ``dest == "#"`` parst (pytex_markdown ``_eval_comment``).
# Der Body ist nutzer-geschrieben (Protokollant); da die Protokoll-Variante pytex'
# Template-Maschinerie braucht und deshalb ``trusted`` gerendert wird, ist DIESER
# Sanitizer der RCE-Schutz.
#
# WICHTIG (AUD-001): Eine zeilen-orientierte Regex (``^[ \t]*[...]: #``) ist KEIN
# verlässlicher Schutz — eine Link-Referenz-Definition ist ein CommonMark-Block,
# der mehrzeilig (``[//]:\n#\n"EXPR"``), in Containern verschachtelt
# (``> [//]: # "EXPR"``, ``- [//]: # "EXPR"``, ``1. [//]: # "EXPR"``) und mit
# Whitespace/Zeilenumbruch im Label (``[ // ]``, ``[//\n]``) auftreten darf und so
# jede einfache Zeilen-Regex umgeht. Wir entfernen daher die GESAMTE
# eval-fähige Definition: Kopf ``[label] : #`` (``#``-Ziel exakt — KEIN
# ``#fragment``) plus optionalen Titel (``"…"``/``'…'``/``(…)``), tolerant
# gegenüber Whitespace und Zeilenumbruch an jeder von CommonMark erlaubten Stelle.
# pytex' ``_eval_comment`` feuert ausschließlich für ``label='//'`` + ``dest='#'``;
# ``dest='#'`` setzt eine bare-``#``-Definition voraus, deren Kopf hier matcht.
# Echte Referenz-Links (``[foo]: #section``), Inline-Links/Bilder und der
# Abstimmungs-Callout (``> [!abstimmung]``) bleiben unberührt.
_EVAL_REFDEF_RE = re.compile(
    r"\[[^\]]*\]\s*:\s*#"  # Definitions-Kopf, Ziel exakt ``#`` …
    r"(?=[ \t\r\n\"'(]|$)"  # … bare-``#`` (von WS/Titel-Delimiter/Zeilenende gefolgt)
    r"[ \t]*"  # Whitespace vor optionalem Titel
    r"(?:\r?\n[ \t]*)?"  # Titel darf in der mehrzeiligen Form auf der Folgezeile stehen
    r"""(?:"[^"]*"|'[^']*'|\([^)]*\)|[^\r\n]*)?""",  # optionaler Titel bzw. Resttext
    re.DOTALL,
)


def _strip_eval_refdefs(markdown: str) -> str:
    r"""Eval-fähige ``[label]: # "EXPR"``-Definitionen restlos entfernen.

    Streicht Kopf **und** Ausdruck jeder bare-``#``-Link-Referenz-Definition (in
    jeder CommonMark-Form), sodass pytex' ``_eval_comment``-Trigger gar nicht erst
    in den Markdown-Baum gelangt. Normales Markdown bleibt unberührt."""
    return _EVAL_REFDEF_RE.sub("", markdown)


def _has_eval_refdef(markdown: str) -> bool:
    """Parst ``markdown`` mit marko und meldet einen verbleibenden eval-Trigger.

    Strukturelle Verifikation (AUD-001): ein ``LinkRefDef``-Knoten mit
    ``label == "//"`` und ``dest == "#"`` irgendwo im Baum (oder in
    ``document.link_ref_defs``) würde pytex' eval auslösen. Ohne installiertes
    marko greift allein der Regex-Primärschutz; dann gilt der Body als sauber."""
    if _marko is None:  # pragma: no cover - Regex-Primärschutz deckt alle Vektoren
        return False
    document = _marko.Markdown().parse(markdown)
    refs = getattr(document, "link_ref_defs", {}) or {}
    if refs.get("//", (None,))[0] == "#":
        return True

    def _walk(node: object) -> bool:
        if (
            type(node).__name__ == "LinkRefDef"
            and getattr(node, "label", None) == "//"
            and getattr(node, "dest", None) == "#"
        ):
            return True
        children = getattr(node, "children", None)
        if isinstance(children, list):
            return any(_walk(c) for c in children if not isinstance(c, str))
        return False

    return _walk(document)


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

    Entfernt RCE-Vektoren (``[//]: # "…"``-Kommentar-Eval in JEDER CommonMark-Form —
    ein-/mehrzeilig, container-verschachtelt, Whitespace im Label — sowie
    ``\\iffalse{pytex(…)}\\fi``) und entschärft Bilder mit absolutem/``..``-Pfad
    (FIX 3). **Normales** Markdown (Überschriften, Listen, Hervorhebung, echte
    Links/Bilder mit relativem Pfad, Abstimmungs-Callouts) bleibt vollständig
    erhalten. Der eval-Trigger wird über das marko-Parse strukturell verifiziert
    (AUD-001): solange ein eval-fähiger ``LinkRefDef`` überlebt, wird erneut
    entschärft — der Body erreicht pytex garantiert ohne eval-Vektor."""
    cleaned = _PYTEX_IFFALSE_RE.sub("", markdown)
    cleaned = _strip_eval_refdefs(cleaned)
    # Strukturelle Absicherung: sollte (z. B. durch künftige marko-Versionen) doch
    # ein eval-fähiger LinkRefDef überleben, erneut entfernen, bis keiner mehr da
    # ist. Begrenzt, damit die Schleife nicht ewig läuft.
    for _ in range(3):
        if not _has_eval_refdef(cleaned):
            break
        cleaned = _strip_eval_refdefs(cleaned)
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
