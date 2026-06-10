"""Unit-Tests Protokoll-Markdown (T-22): DB-frei, injection-sicher, Vote-Snippets."""

from __future__ import annotations

from datetime import date

from app.modules.protocol.markdown import (
    ProtocolDoc,
    build_protocol_document,
    build_vote_snippet,
    protocol_variant_for,
)


def _doc(**kw: object) -> ProtocolDoc:
    base: dict[str, object] = {
        "title": "StuPa-Sitzung",
        "gremium_slug": "stupa",
        "cd_variant": "stupa",
        "date": date(2026, 6, 12),
        "markdown": "# TOP 1\n\nText.",
    }
    base.update(kw)
    return ProtocolDoc(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------- variant
def test_variant_for_known_protocol_variants() -> None:
    assert protocol_variant_for("stupa") == "protocol-stupa"
    assert protocol_variant_for("asta") == "protocol-asta"


def test_variant_for_other_is_none_autodetect() -> None:
    assert protocol_variant_for("makers") is None
    assert protocol_variant_for(None) is None


# -------------------------------------------------------------- frontmatter
def test_document_has_protocol_frontmatter_then_body() -> None:
    md = build_protocol_document(_doc())
    assert md.startswith("---\n")
    assert 'title: "StuPa-Sitzung"' in md
    assert "typ: protokoll" in md
    assert 'gremium: "stupa"' in md
    assert 'date: "2026-06-12"' in md
    # Editor-Body bleibt verbatim, nach dem Frontmatter.
    assert md.rstrip().endswith("# TOP 1\n\nText.")


def test_document_without_optional_fields() -> None:
    md = build_protocol_document(
        _doc(gremium_slug=None, cd_variant=None, date=None, markdown="")
    )
    assert "gremium:" not in md
    assert "date:" not in md
    assert "typ: protokoll" in md


def test_frontmatter_injection_is_quoted() -> None:
    # Ein Titel mit Doppelpunkt/Newline/--- darf das Frontmatter nicht sprengen.
    md = build_protocol_document(_doc(title='evil: \n---\ntyp: antrag'))
    lines = md.splitlines()
    # Genau zwei `---`-Begrenzer (öffnend/schließend) — kein eingeschleustes drittes.
    assert lines.count("---") == 2
    assert "typ: protokoll" in md
    assert "typ: antrag" not in md.split("---")[1]  # nicht im Frontmatter-Block


# ------------------------------------------------------------- vote snippet
def test_vote_snippet_renders_abstimmung_callout_with_tally() -> None:
    snippet = build_vote_snippet("Antrag A", "passed", {"yes": 5, "no": 2, "abstain": 1})
    # pytex-Protokoll-Callout → eingebaute Vote-Box; Tally-Zeile (yes/no/abstain).
    assert snippet.startswith("> [!abstimmung] Antrag A")
    assert "> Ergebnis: passed" in snippet
    assert "> yes: 5, no: 2, abstain: 1" in snippet


def test_vote_snippet_question_overrides_title_and_omits_empty_tally() -> None:
    snippet = build_vote_snippet("Antrag B", None, None, question="Soll X?")
    assert snippet.startswith("> [!abstimmung] Soll X?")
    assert "Ergebnis" not in snippet
    assert "yes:" not in snippet


def test_vote_snippet_escapes_newlines() -> None:
    snippet = build_vote_snippet("Zeile1\nZeile2", "passed", None)
    # Titel bleibt einzeilig (kein Markdown-Bruch im Callout-Marker).
    assert "> [!abstimmung] Zeile1 Zeile2" in snippet
