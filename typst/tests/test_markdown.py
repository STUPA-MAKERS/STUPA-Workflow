"""Unit tests for the Markdown -> JSON converter."""

from __future__ import annotations

import pytest

from typst_service.frontmatter import Meta
from typst_service.markdown import MAX_DEPTH, ConversionError, Node, convert_body

META: Meta = {"anwesend": ["A", "B", "C"], "gremium": "StuPa", "datum": "2026-06-15"}


def conv(md: str, meta: Meta | None = None) -> list[Node]:
    return convert_body(md, META if meta is None else meta)


def texts(nodes: object) -> str:
    """Flatten the text of an inline or block tree."""
    if isinstance(nodes, list):
        return "".join(texts(n) for n in nodes)  # pyright: ignore[reportUnknownVariableType]
    if isinstance(nodes, dict):
        if nodes.get("t") in ("text", "sym", "code", "time"):
            return str(nodes["v"])
        return "".join(texts(v) for k, v in nodes.items() if k in ("c", "items", "lines"))  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return ""


def test_headings_and_paragraphs() -> None:
    blocks = conv("# TOP eins\n\nText *kursiv* und **fett**.\n\nSetext\n===\n")
    assert blocks[0] == {"t": "heading", "level": 1, "c": [{"t": "text", "v": "TOP eins"}]}
    assert blocks[1]["t"] == "par"
    inline = blocks[1]["c"]
    assert {"t": "emph", "c": [{"t": "text", "v": "kursiv"}]} in inline  # pyright: ignore[reportOperatorIssue]
    assert {"t": "strong", "c": [{"t": "text", "v": "fett"}]} in inline  # pyright: ignore[reportOperatorIssue]
    assert blocks[2]["t"] == "heading" and blocks[2]["level"] == 1


def test_typst_markup_stays_text() -> None:
    """Typst syntax in the source is plain text data, never code."""
    src = '#set page(fill: red) #read("/etc/passwd") = heading <label> @ref $$'
    (block,) = conv(src)
    assert texts(block) == src


@pytest.mark.parametrize(
    ("marker", "kind", "label"),
    [
        ("NOTE", "info", None),
        ("TIP", "success", None),
        ("IMPORTANT", "important", None),
        ("WARNING", "warning", None),
        ("beschluss", "decision", "Beschluss: "),
        ("aufgabe", "task", "Aufgabe: "),
        ("frist", "deadline", "Frist: "),
    ],
)
def test_callouts(marker: str, kind: str, label: str | None) -> None:
    (box,) = conv(f"> [!{marker}] Kopf\n> weiter\n\n> zweiter Absatz")[:1]
    assert box["t"] == "callout"
    assert box["kind"] == kind
    first = box["c"][0]  # pyright: ignore[reportIndexIssue]
    if label:
        assert first["c"][0] == {"t": "strong", "c": [{"t": "text", "v": label}]}  # pyright: ignore[reportIndexIssue]
    assert "Kopf weiter" in texts(first)


def test_unknown_callout_is_a_quote() -> None:
    (block,) = conv("> [!foo] bar")
    assert block["t"] == "quote"
    assert "[!foo] bar" in texts(block)


def test_vote_tally_keeps_the_formatting_of_the_question() -> None:
    (vote,) = conv("> [!abstimmung] **Soll das so?**\n> ja: 12, nein: 3, enthaltung: 2")
    assert vote["t"] == "tally"
    assert (vote["yes"], vote["no"], vote["abstain"]) == (12, 3, 2)
    assert vote["lines"] == [[{"t": "strong", "c": [{"t": "text", "v": "Soll das so?"}]}]]


def test_vote_tally_ignores_counts_outside_the_tally_line() -> None:
    (vote,) = conv("> [!vote] Antrag ja 7\n> Beschreibung\n> yes: 1, no: 2")
    assert (vote["yes"], vote["no"], vote["abstain"]) == (1, 2, 0)
    assert [texts(line) for line in vote["lines"]] == ["Antrag ja 7", "Beschreibung"]  # pyright: ignore[reportGeneralTypeIssues]


def test_signature_callout() -> None:
    (sig,) = conv("> [!unterschriften] Sitzungsleitung: A. Muster\n> Vorstand:")
    assert sig == {
        "t": "signatures",
        "signers": [["Sitzungsleitung", "A. Muster"], ["Vorstand", ""]],
    }


def test_shortcodes() -> None:
    (block,) = conv(
        "{{time 18:30}} {{count anwesend}} {{anwesend}} {{gremium}} {{vote ja=2 nein=1}} {{nope x}}"
    )
    inline = block["c"]
    assert inline[0] == {"t": "time", "v": "18:30"}  # pyright: ignore[reportIndexIssue]
    assert {"t": "vote", "yes": 2, "no": 1, "abstain": 0} in inline  # pyright: ignore[reportOperatorIssue]
    flat = texts(block)
    assert " 3 A, B, C StuPa " in flat
    assert flat.endswith("{{nope x}}")


def test_shortcode_in_code_span_stays_literal() -> None:
    (block,) = conv("`{{time 1}}`")
    assert block["c"] == [{"t": "code", "v": "{{time 1}}"}]


def test_math_inline_display_and_prices() -> None:
    blocks = conv(
        "Die Formel $E = mc^2$ und $\\frac{a}{b}$. Preise wie $5 und $6 bleiben Text."
        "\n\n$$\\int_0^1 x\\,dx$$"
    )
    inline = blocks[0]["c"]
    assert {"t": "math", "tex": "E = mc^2"} in inline  # pyright: ignore[reportOperatorIssue]
    assert {"t": "math", "tex": "\\frac{a}{b}"} in inline  # pyright: ignore[reportOperatorIssue]
    assert "$5 und $6" in texts(blocks[0])
    assert blocks[1] == {"t": "mathblock", "tex": "\\int_0^1 x\\,dx"}


def test_escaped_dollar_is_text() -> None:
    (block,) = conv("Kosten \\$5 und \\$6")
    assert not any(n["t"] == "math" for n in block["c"])  # pyright: ignore[reportGeneralTypeIssues]


def test_arrows_and_symbols_become_math_symbols() -> None:
    (block,) = conv("a -> b <=> c ≤ d · e")
    syms = [n["v"] for n in block["c"] if n["t"] == "sym"]  # pyright: ignore[reportGeneralTypeIssues]
    assert syms == ["→", "⇔", "≤", "·"]


def test_antrag_fences_are_dropped_outside_code() -> None:
    md = ":::antrag{#0b9f-uuid}\n### Titel\n:::\n\n```\n:::antrag{#x}\n:::\n```\n\n:::\n"
    blocks = conv(md)
    assert blocks[0] == {"t": "heading", "level": 3, "c": [{"t": "text", "v": "Titel"}]}
    assert blocks[1] == {"t": "codeblock", "v": ":::antrag{#x}\n:::"}
    # A stray `:::` without an open application fence stays text.
    assert texts(blocks[2]) == ":::"
    assert "uuid" not in texts(blocks)


def test_strike_links_images_html() -> None:
    (block,) = conv("~~alt~~ [ext](https://x.org) [rel](docs/a.md) ![Logo](a.png) <b>x</b>")
    inline = block["c"]
    assert inline[0] == {"t": "strike", "c": [{"t": "text", "v": "alt"}]}  # pyright: ignore[reportIndexIssue]
    assert {"t": "link", "url": "https://x.org", "c": [{"t": "text", "v": "ext"}]} in inline  # pyright: ignore[reportOperatorIssue]
    assert {"t": "text", "v": "rel"} in inline  # pyright: ignore[reportOperatorIssue]
    assert {"t": "image", "alt": "Logo"} in inline  # pyright: ignore[reportOperatorIssue]
    assert "<b>" in texts(block)


def test_html_block_is_dropped() -> None:
    assert conv("<div>\nx\n</div>\n") == []


def test_list_levels_count_bullets_and_numbers_apart() -> None:
    (outer,) = conv("1. eins\n   - a\n     1. tief\n2. zwei\n")
    assert outer["t"] == "list" and outer["ordered"] and outer["olevel"] == 0
    inner = outer["items"][0][1]  # pyright: ignore[reportIndexIssue]
    assert inner["ulevel"] == 0
    assert inner["items"][0][1]["olevel"] == 1


def test_ordered_list_start() -> None:
    (block,) = conv("3. c\n4. d\n")
    assert block["start"] == 3


def test_table() -> None:
    (table,) = conv("| a | b | c |\n|:--|:-:|--:|\n| 1 | 2 | 3 |\n")
    assert table["align"] == ["left", "center", "right"]
    assert table["head"] == [[{"t": "text", "v": x}] for x in "abc"]
    assert table["rows"] == [[[{"t": "text", "v": x}] for x in "123"]]


def test_code_block_and_rule() -> None:
    blocks = conv("```python\nx = 1\n```\n\n---\n")
    assert blocks == [{"t": "codeblock", "v": "x = 1"}, {"t": "rule"}]


def test_too_deep_nesting_raises() -> None:
    with pytest.raises(ConversionError):
        conv("> " * (MAX_DEPTH + 2) + "x")
