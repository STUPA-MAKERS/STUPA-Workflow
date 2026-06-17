"""Unit-Tests Protokoll-Markdown (T-22): DB-frei, injection-sicher, Vote-Snippets."""

from __future__ import annotations

from datetime import date

from app.modules.protocol.markdown import (
    ProtocolDoc,
    build_protocol_document,
    build_vote_snippet,
    demote_headings,
    protocol_variant_for,
    sanitize_user_markdown,
)


def _doc(**kw: object) -> ProtocolDoc:
    base: dict[str, object] = {
        "title": "StuPa-Sitzung",
        "gremium_name": "StuPa",
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
    assert 'gremium: "StuPa"' in md
    assert 'date: "2026-06-12"' in md
    # Editor-Body bleibt verbatim, nach dem Frontmatter.
    assert md.rstrip().endswith("# TOP 1\n\nText.")


def test_document_without_optional_fields() -> None:
    md = build_protocol_document(
        _doc(gremium_name=None, cd_variant=None, date=None, markdown="")
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
    snippet = build_vote_snippet("Antrag A", {"yes": 5, "no": 2, "abstain": 1})
    # pytex-Protokoll-Callout → eingebaute Vote-Box; Titel fett, Tally-Zeile
    # (yes/no/abstain), KEINE separate »Ergebnis:«-Zeile (#pdf-format).
    assert snippet.startswith("> [!abstimmung] **Antrag A**")
    assert "Ergebnis" not in snippet
    assert "> yes: 5, no: 2, abstain: 1" in snippet


def test_vote_snippet_question_overrides_title_and_omits_empty_tally() -> None:
    snippet = build_vote_snippet("Antrag B", None, question="Soll X?")
    assert snippet.startswith("> [!abstimmung] **Soll X?**")
    assert "yes:" not in snippet


def test_vote_snippet_escapes_newlines() -> None:
    snippet = build_vote_snippet("Zeile1\nZeile2", None)
    # Titel bleibt einzeilig (kein Markdown-Bruch im Callout-Marker).
    assert "> [!abstimmung] **Zeile1 Zeile2**" in snippet


# ------------------------------------------------------------- pdf format
def test_frontmatter_has_signatures_and_quorum_dataline() -> None:
    md = build_protocol_document(_doc(quorate=True, datalines=["Ort: R 1"]))
    block = md.split("---")[1]
    assert "unterschriften:" in block
    assert '- "Schriftführung"' in block and '- "Vorstand"' in block
    # Beschlussfähigkeit als eigener Frontmatter-Key (der pytex-Wrapper rendert
    # ihn als Titelseiten-Daten-Zeile, #protocol-quorum).
    assert 'beschlussfaehigkeit: "Gegeben"' in block


def test_frontmatter_quorum_not_given() -> None:
    md = build_protocol_document(_doc(quorate=False))
    assert 'beschlussfaehigkeit: "Nicht gegeben"' in md


def test_frontmatter_quorum_omitted_when_unknown() -> None:
    md = build_protocol_document(_doc())
    assert "beschlussfaehigkeit" not in md


def test_demote_headings_shifts_levels_and_skips_fences() -> None:
    md = "\n".join(
        [
            "# A",
            "",
            "## B",
            "",
            "```",
            "# nicht anfassen",
            "```",
            "",
            "###### F",
            "kein # heading",
        ]
    )
    out = demote_headings(md)
    assert "## A" in out and "### B" in out
    assert "# nicht anfassen" in out  # Code-Fence unberührt
    assert "###### F" in out  # Ebene 6 bleibt 6
    assert "kein # heading" in out


def test_frontmatter_includes_protokollant_when_set() -> None:
    md = build_protocol_document(_doc(protokollant="Frau Schmidt"))
    assert 'protokoll: "Frau Schmidt"' in md


def test_frontmatter_start_end_time_lines() -> None:
    """#14: Start/Ende reisen als ``beginn``/``ende`` — pytex rendert daraus die
    »Zeit: Start – Ende«-Titelseiten-Zeile."""
    from datetime import time

    md = build_protocol_document(
        _doc(start_time=time(18, 30), end_time=time(21, 5))
    )
    assert 'beginn: "18:30"' in md
    assert 'ende: "21:05"' in md


def test_frontmatter_end_time_omitted_when_unknown() -> None:
    md = build_protocol_document(_doc())
    assert "ende:" not in md


# ---------------------------------------------------- RCE-Defense-in-Depth (FIX 1b)
def test_sanitizer_strips_eval_comment_double_quotes() -> None:
    """``[//]: # "EXPR"`` (pytex-``eval``-Escape) wird entfernt → kein RCE-Vektor."""
    out = sanitize_user_markdown('# TOP\n[//]: # "__import__(\'os\').system(\'id\')"\nText')
    assert "__import__" not in out
    assert "[//]:" not in out
    assert "# TOP" in out and "Text" in out


def test_sanitizer_strips_eval_comment_single_quotes_and_parens_and_bare() -> None:
    variants = [
        "[//]: # 'evil'",
        "[//]: # (evil)",
        "[//]: # evil",
        "   [//]: #  evil",  # führender Whitespace
        "[comment]: # evil",  # anderes Label
    ]
    for line in variants:
        out = sanitize_user_markdown(f"# TOP\n{line}\nText")
        assert "evil" not in out, line
        assert "# TOP" in out and "Text" in out


def test_sanitizer_strips_iffalse_pytex_marker() -> None:
    out = sanitize_user_markdown("vor\n\\iffalse{pytex(open('/etc/passwd'))}\\fi\nnach")
    assert "pytex(" not in out
    assert "passwd" not in out
    assert "vor" in out and "nach" in out


def test_sanitizer_keeps_normal_markdown_intact() -> None:
    src = (
        "# Heading\n\n"
        "- list item\n"
        "- *emph* and **bold**\n\n"
        "A [real link](https://example.org) and `code`.\n\n"
        "![Diagramm](images/chart.png)\n"
    )
    assert sanitize_user_markdown(src) == src


def test_sanitizer_neutralizes_absolute_image_path() -> None:
    out = sanitize_user_markdown("![secret](/etc/passwd)")
    assert "/etc/passwd" not in out
    assert "Bild entfernt" in out
    assert "secret" in out  # Alt-Text bleibt als Platzhalter-Label


def test_sanitizer_neutralizes_traversal_image_path() -> None:
    out = sanitize_user_markdown("![x](../../secrets/key.png)")
    assert "../../secrets" not in out
    assert "Bild entfernt" in out


def test_sanitizer_neutralizes_windows_and_encoded_traversal() -> None:
    assert "Bild entfernt" in sanitize_user_markdown("![](C:\\windows\\win.png)")
    assert "Bild entfernt" in sanitize_user_markdown("![](a/%2e%2e/b.png)")
    assert "Bild entfernt" in sanitize_user_markdown("![](\\\\host\\share.png)")


def test_sanitizer_image_without_alt_uses_default_label() -> None:
    out = sanitize_user_markdown("![](/abs/img.png)")
    assert "Bild entfernt" in out
    assert "Bild" in out


def test_sanitizer_keeps_relative_image_path() -> None:
    src = "![ok](assets/logo.png)"
    assert sanitize_user_markdown(src) == src


def test_build_document_applies_sanitizer_to_body() -> None:
    """Defense-in-Depth: der Eval-Kommentar darf das finale Dokument nie erreichen."""
    md = build_protocol_document(_doc(markdown='# TOP 1\n[//]: # "evil"\nText.'))
    assert "evil" not in md
    assert "# TOP 1" in md and "Text." in md
