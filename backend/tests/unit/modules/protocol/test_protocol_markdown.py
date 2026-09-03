"""Unit tests for the protocol Markdown builder (T-22): no DB, injection-safe, snippets."""

from __future__ import annotations

import time
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


def test_variant_for_known_protocol_variants() -> None:
    assert protocol_variant_for("stupa") == "protocol-stupa"
    assert protocol_variant_for("asta") == "protocol-asta"


def test_variant_for_other_is_none_autodetect() -> None:
    assert protocol_variant_for("makers") is None
    assert protocol_variant_for(None) is None


def test_document_has_protocol_frontmatter_then_body() -> None:
    md = build_protocol_document(_doc())
    assert md.startswith("---\n")
    assert 'title: "StuPa-Sitzung"' in md
    assert "typ: protokoll" in md
    assert 'gremium: "StuPa"' in md
    assert 'date: "2026-06-12"' in md
    # The editor body stays verbatim and follows the frontmatter.
    assert md.rstrip().endswith("# TOP 1\n\nText.")


def test_document_without_optional_fields() -> None:
    md = build_protocol_document(
        _doc(gremium_name=None, cd_variant=None, date=None, markdown="")
    )
    assert "gremium:" not in md
    assert "date:" not in md
    assert "typ: protokoll" in md


def test_frontmatter_injection_is_quoted() -> None:
    # A title with a colon, a newline or --- must not break the frontmatter open.
    md = build_protocol_document(_doc(title='evil: \n---\ntyp: antrag'))
    lines = md.splitlines()
    # Exactly two `---` delimiters, one open and one close. No injected third one.
    assert lines.count("---") == 2
    assert "typ: protokoll" in md
    assert "typ: antrag" not in md.split("---")[1]  # not inside the frontmatter block


def test_vote_snippet_renders_abstimmung_callout_with_tally() -> None:
    snippet = build_vote_snippet("Antrag A", {"yes": 5, "no": 2, "abstain": 1})
    # The pytex protocol callout renders the built-in vote box: a bold title plus a
    # tally line (yes/no/abstain). It carries NO separate `Ergebnis:` line.
    assert snippet.startswith("> [!abstimmung] **Antrag A**")
    assert "Ergebnis" not in snippet
    assert "> yes: 5, no: 2, abstain: 1" in snippet


def test_vote_snippet_question_overrides_title_and_omits_empty_tally() -> None:
    snippet = build_vote_snippet("Antrag B", None, question="Soll X?")
    assert snippet.startswith("> [!abstimmung] **Soll X?**")
    assert "yes:" not in snippet


def test_vote_snippet_escapes_newlines() -> None:
    snippet = build_vote_snippet("Zeile1\nZeile2", None)
    # The title stays on one line, so the callout marker does not break.
    assert "> [!abstimmung] **Zeile1 Zeile2**" in snippet


def test_frontmatter_has_signatures_and_quorum_dataline() -> None:
    md = build_protocol_document(_doc(quorate=True, datalines=["Ort: R 1"]))
    block = md.split("---")[1]
    assert "unterschriften:" in block
    assert '- "Schriftführung"' in block and '- "Vorstand"' in block
    # The quorum gets its own frontmatter key. The pytex wrapper renders it as a
    # data line on the title page.
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
    assert "# nicht anfassen" in out  # the code fence stays untouched
    assert "###### F" in out  # level 6 stays level 6
    assert "kein # heading" in out


def test_frontmatter_includes_protokollant_when_set() -> None:
    md = build_protocol_document(_doc(protokollant="Frau Schmidt"))
    assert 'protokoll: "Frau Schmidt"' in md


def test_frontmatter_start_end_time_lines() -> None:
    """#14: the start time and the end time travel as `beginn` and `ende`.

    pytex renders them into the `Zeit: Start - Ende` line of the title page.
    """
    from datetime import time

    md = build_protocol_document(
        _doc(start_time=time(18, 30), end_time=time(21, 5))
    )
    assert 'beginn: "18:30"' in md
    assert 'ende: "21:05"' in md


def test_frontmatter_end_time_omitted_when_unknown() -> None:
    md = build_protocol_document(_doc())
    assert "ende:" not in md


# RCE defense in depth (FIX 1b).
def test_sanitizer_strips_eval_comment_double_quotes() -> None:
    """The sanitizer strips the `[//]: # "EXPR"` pytex `eval` escape, so no RCE stays."""
    out = sanitize_user_markdown('# TOP\n[//]: # "__import__(\'os\').system(\'id\')"\nText')
    assert "__import__" not in out
    assert "[//]:" not in out
    assert "# TOP" in out and "Text" in out


def test_sanitizer_strips_eval_comment_single_quotes_and_parens_and_bare() -> None:
    variants = [
        "[//]: # 'evil'",
        "[//]: # (evil)",
        "[//]: # evil",
        "   [//]: #  evil",  # leading whitespace
        "[comment]: # evil",  # a different label
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
    assert "secret" in out  # the alt text stays as the placeholder label


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
    """Defense in depth: the eval comment must never reach the final document."""
    md = build_protocol_document(_doc(markdown='# TOP 1\n[//]: # "evil"\nText.'))
    assert "evil" not in md
    assert "# TOP 1" in md and "Text." in md


# AUD-001: sanitizer bypass regression.
# The old line-oriented regex let through the multiline, the container-nested and the
# whitespace-in-label forms of the eval-capable link reference definition. They reached
# the pytex `eval` as `LinkRefDef(label='//', dest='#')` and gave an RCE.
def test_sanitizer_strips_multiline_eval_comment() -> None:
    r"""Multiline form `[//]:\n#\n"EXPR"` with the target and the title on later lines."""
    out = sanitize_user_markdown('# TOP\n[//]:\n#\n"__import__(\'os\').system(\'id\')"\nText')
    assert "__import__" not in out
    assert "[//]" not in out
    assert "# TOP" in out and "Text" in out


def test_sanitizer_strips_head_then_title_on_next_line() -> None:
    out = sanitize_user_markdown('[//]: #\n"evil_expr"')
    assert "evil_expr" not in out
    assert "[//]" not in out


def test_sanitizer_strips_whitespace_inside_label() -> None:
    for src in ("[ // ]: # \"evil\"", "[//\n]: # \"evil\""):
        out = sanitize_user_markdown(src)
        assert "evil" not in out, src
        assert "[//" not in out and "[ //" not in out, src


def test_sanitizer_strips_container_nested_eval_comments() -> None:
    """Definitions nested in a blockquote or a list (`>`, `-`, `*`, `1.`)."""
    for prefix in ("> ", "- ", "* ", "1. "):
        out = sanitize_user_markdown(f'{prefix}[//]: # "evil"')
        assert "evil" not in out, prefix
        assert "[//]" not in out, prefix


def test_sanitizer_keeps_anchor_reference_definition() -> None:
    """A real anchor reference (`[foo]: #section`) is no eval trigger.

    pytex fires only when `dest == '#'`, so the sanitizer keeps the line unchanged.
    """
    src = '[foo]: #section "Title"'
    assert sanitize_user_markdown(src) == src


def test_sanitizer_keeps_vote_callout_intact() -> None:
    """The sanitizer must keep the vote callout unchanged.

    `embed_protocol_votes` mixes the callout (`> [!abstimmung]` plus the tally line)
    into `protocol.markdown`, so the sanitizer sees it together with the body. Any
    change here breaks the pytex tally box.
    """
    callout = build_vote_snippet("Antrag A", {"yes": 5, "no": 2, "abstain": 1})
    assert sanitize_user_markdown(callout) == callout


def test_sanitizer_no_eval_refdef_survives_marko_parse() -> None:
    """Structural check: after the sanitizer, marko parses no eval-capable `LinkRefDef`.

    The check covers every known bypass form. It applies only when marko is installed.
    """
    from app.modules.protocol.markdown import _has_eval_refdef

    vectors = [
        '[//]: # "x"',
        '[//]:\n#\n"x"',
        '[//]: #\n"x"',
        '[ // ]: # "x"',
        '[//\n]: # "x"',
        '> [//]: # "x"',
        '- [//]: # "x"',
        '1. [//]: # "x"',
    ]
    for src in vectors:
        cleaned = sanitize_user_markdown(src)
        assert not _has_eval_refdef(cleaned), src


def test_sanitizer_is_linear_on_adversarial_open_brackets() -> None:
    """ReDoS regression: a long run of `[` must not backtrack catastrophically.

    A run of `[` without a closing bracket made the label scan restart at every `[`
    position, which is O(N**2) and hung the contract-test job. The run matches no
    reference definition, so the text stays unchanged, and it must finish in
    milliseconds.
    """
    adversarial = "[" * 200_000
    start = time.perf_counter()
    out = sanitize_user_markdown(adversarial)
    assert time.perf_counter() - start < 1.0
    assert out == adversarial
