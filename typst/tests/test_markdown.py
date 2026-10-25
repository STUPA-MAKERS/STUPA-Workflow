"""Unit tests for the Markdown -> JSON converter."""

from __future__ import annotations

from typing import cast

import pytest

from typst_service.frontmatter import Meta
from typst_service.markdown import MAX_DEPTH, ConversionError, Node, convert_body

META: Meta = {"anwesend": ["A", "B", "C"], "gremium": "StuPa", "datum": "2026-06-15"}


def conv(md: str, meta: Meta | None = None) -> list[Node]:
    return convert_body(md, META if meta is None else meta)


def texts(nodes: object) -> str:
    """Flatten the text of an inline or block tree."""
    if isinstance(nodes, list):
        return "".join(texts(n) for n in nodes)
    if isinstance(nodes, dict):
        if nodes.get("t") in ("text", "sym", "code", "time"):
            return str(nodes["v"])
        return "".join(texts(v) for k, v in nodes.items() if k in ("c", "items", "lines"))
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
        assert first["c"][0] == {"t": "strong", "c": [{"t": "text", "v": label}]}
    assert "Kopf weiter" in texts(first)


def test_unknown_callout_is_a_quote() -> None:
    (block,) = conv("> [!foo] bar")
    assert block["t"] == "quote"
    assert "[!foo] bar" in texts(block)


def test_vote_tally_keeps_the_formatting_of_the_question() -> None:
    (vote,) = conv("> [!abstimmung] **Soll das so?**\n> ja: 12, nein: 3, enthaltung: 2")
    assert vote["t"] == "tally"
    assert (vote["yes"], vote["no"], vote["abstain"]) == (12, 3, 2)
    assert vote["counts"] is True
    assert vote["lines"] == [[{"t": "strong", "c": [{"t": "text", "v": "Soll das so?"}]}]]


def test_vote_tally_ignores_counts_outside_the_tally_line() -> None:
    (vote,) = conv("> [!vote] Antrag ja 7\n> Beschreibung\n> yes: 1, no: 2")
    assert (vote["yes"], vote["no"], vote["abstain"]) == (1, 2, 0)
    assert [texts(line) for line in vote["lines"]] == ["Antrag ja 7", "Beschreibung"]  # pyright: ignore[reportGeneralTypeIssues]


def test_election_without_a_tally_line_has_no_counts() -> None:
    (vote,) = conv(
        "> [!abstimmung] **DEF**\n> Wahl · 1 Posten\n"
        "> Jakob Frey: 1 · Frederik Beimgraben: 0 · Enthaltungen: 0\n> Gewählt: Jakob Frey"
    )
    assert vote["t"] == "tally"
    assert vote["counts"] is False
    # Only the question stays a body line; the template draws the ranking.
    assert len(vote["lines"]) == 1  # pyright: ignore[reportArgumentType]
    assert vote["election"] == {
        "meta": "Wahl · 1 Posten",
        "rows": [
            {"name": "Jakob Frey", "votes": 1, "elected": True},
            {"name": "Frederik Beimgraben", "votes": 0, "elected": False},
        ],
        "abstentions": 0,
        "elected": [],
        "others": 0,
        "lot": None,
        "notes": [],
    }


def test_election_keeps_a_name_with_a_comma_and_reads_the_lot() -> None:
    (vote,) = conv(
        "> [!abstimmung] **Q**\n> Wahl · 2 Posten\n"
        "> Krüger, Ben: 6 · Amira: 6 · Finn: 3 · Enthaltungen: 0\n"
        "> Gewählt: Amira, Krüger, Ben\n> Durch Los entschieden.\n> Ein Hinweis"
    )
    election = cast("dict[str, object]", vote["election"])
    assert election["rows"] == [
        {"name": "Krüger, Ben", "votes": 6, "elected": True},
        {"name": "Amira", "votes": 6, "elected": True},
        {"name": "Finn", "votes": 3, "elected": False},
    ]
    assert election["lot"] == "drawn"
    assert election["notes"] == ["Ein Hinweis"]


def test_public_election_and_a_pending_lot() -> None:
    public, pending = conv(
        "> [!abstimmung] **A**\n> Wahl · 1 Posten\n> Gewählt: Hannah, Ida\n"
        "> 3 weitere Kandidierende\n\n"
        "> [!abstimmung] **B**\n> Wahl · 1 Posten\n> Ben: 6 · Amira: 6\n"
        "> Gewählt: niemand\n> Gleichstand: das Los steht aus."
    )
    election = cast("dict[str, object]", public["election"])
    assert election["elected"] == ["Hannah", "Ida"]
    assert election["others"] == 3
    assert cast("dict[str, object]", pending["election"])["lot"] == "pending"


def test_single_candidate_and_motion_have_no_ranking() -> None:
    single, motion = conv(
        "> [!abstimmung] **A**\n> Wahl · 1 Posten\n> Kandidatur: Anna\n"
        "> ja: 3, nein: 1, enthaltung: 0\n\n"
        "> [!abstimmung] **B**\n> Wahl · 1 Posten\n> Kandidatur: Anna\n> Gewählt: Anna"
    )
    assert "election" not in single
    assert "election" not in motion


def test_poll_reads_options_abstentions_top_and_footer() -> None:
    (vote,) = conv(
        "> [!abstimmung] **Wohin geht der Ausflug?**\n> Umfrage · Einzelwahl\n"
        "> Freiburg: 7\n> Konstanz: 4\n> Tübingen: 2\n> Enthaltungen: 1\n"
        "> Meiste Stimmen: Freiburg\n> 14 Antworten"
    )
    assert vote["counts"] is False
    assert "election" not in vote
    # Only the question stays a body line; the template draws the options.
    assert [texts(line) for line in vote["lines"]] == ["Wohin geht der Ausflug?"]  # pyright: ignore[reportGeneralTypeIssues]
    assert vote["poll"] == {
        "kind": "single",
        "meta": "Umfrage · Einzelwahl",
        "rows": [
            {"label": "Freiburg", "count": 7, "maybe": None, "top": True},
            {"label": "Konstanz", "count": 4, "maybe": None, "top": False},
            {"label": "Tübingen", "count": 2, "maybe": None, "top": False},
        ],
        "abstentions": 1,
        "footer": "14 Antworten",
        "notes": [],
    }


def test_poll_with_several_top_options_marks_each() -> None:
    (vote,) = conv(
        "> [!abstimmung] **Q**\n> Umfrage · Mehrfachwahl, höchstens 2\n"
        "> Ja: 5\n> Nein, danke: 5\n> Nein: 1\n> Enthaltungen: 0\n"
        "> Meiste Stimmen: Ja, Nein, danke\n> 6 Antworten"
    )
    # "Ja: 5" and "Nein: 1" are two lines, so they form no tally line.
    assert vote["counts"] is False
    poll = cast("dict[str, object]", vote["poll"])
    assert poll["kind"] == "multi"
    rows = cast("list[dict[str, object]]", poll["rows"])
    assert [(r["label"], r["top"]) for r in rows] == [
        ("Ja", True),
        ("Nein, danke", True),
        ("Nein", False),
    ]


def test_date_poll_reads_ja_and_vielleicht_and_drops_the_legend() -> None:
    (vote,) = conv(
        "> [!abstimmung] **Wann?**\n> Terminumfrage\n"
        "> Mi, 4.11. · 17:00–19:00: 6 (+3)\n> Di, 3.11. · 18:00–20:00: 5 (+2)\n"
        "> Zahl = Ja, (+n) = Vielleicht\n> Bester Termin: Mi, 4.11. · 17:00–19:00\n"
        "> 10 Antworten"
    )
    poll = cast("dict[str, object]", vote["poll"])
    assert poll["kind"] == "date"
    assert poll["rows"] == [
        {"label": "Mi, 4.11. · 17:00–19:00", "count": 6, "maybe": 3, "top": True},
        {"label": "Di, 3.11. · 18:00–20:00", "count": 5, "maybe": 2, "top": False},
    ]
    assert poll["abstentions"] is None
    assert poll["notes"] == []


def test_open_poll_has_the_kind_only() -> None:
    (vote,) = conv("> [!abstimmung] **Q**\n> Umfrage · Mehrfachwahl")
    assert vote["poll"] == {
        "kind": "multi",
        "meta": "Umfrage · Mehrfachwahl",
        "rows": [],
        "abstentions": None,
        "footer": None,
        "notes": [],
    }


def test_vote_without_a_poll_kind_is_no_poll() -> None:
    plain, motion = conv(
        "> [!abstimmung] **A**\n> Umfrage zur Mensa\n> Freiburg: 7\n\n"
        "> [!abstimmung] **B**\n> Umfrage · Einzelwahl\n> ja: 3, nein: 1, enthaltung: 0"
    )
    assert "poll" not in plain
    assert "poll" not in motion
    assert motion["counts"] is True


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


# -- uploaded images ------------------------------------------------------------

IMG_ID = "0b7c6f0e-3a51-4c3e-9b8e-6f1d2a3b4c5d"
IMG_PATH = f"/api/media/images/{IMG_ID}"
IMG_ASSET = f"img-{IMG_ID}.png"


def conv_assets(md: str, *assets: str) -> list[Node]:
    return convert_body(md, META, assets)


def test_canonical_image_with_asset_becomes_a_block_image() -> None:
    (block,) = conv_assets(f"![Foto vom Stand]({IMG_PATH})\n", IMG_ASSET, "a1-logo.png")
    assert block == {"t": "figure", "asset": IMG_ASSET, "alt": "Foto vom Stand"}


def test_canonical_image_without_asset_keeps_the_alt_text() -> None:
    (block,) = conv_assets(f"![Foto]({IMG_PATH})\n", "a1-logo.png")
    assert block == {"t": "par", "c": [{"t": "image", "alt": "Foto"}]}


def test_image_in_a_line_stays_inline_with_its_asset() -> None:
    (block,) = conv_assets(f"Vorher ![Foto]({IMG_PATH}) nachher\n", IMG_ASSET)
    assert block["t"] == "par"
    assert {"t": "image", "asset": IMG_ASSET, "alt": "Foto"} in block["c"]  # pyright: ignore[reportOperatorIssue]


@pytest.mark.parametrize(
    "dest",
    [
        f"https://evil.example{IMG_PATH}",
        f"{IMG_PATH}/../../etc/passwd",
        f"/api/media/images/{IMG_ID.upper()}",
        f"assets/{IMG_ASSET}",
        f"/assets/{IMG_ASSET}",
        "data:image/png;base64,AAAA",
    ],
)
def test_other_image_destinations_keep_the_alt_text(dest: str) -> None:
    (block,) = conv_assets(f"![Bild]({dest})\n", IMG_ASSET)
    assert block == {"t": "par", "c": [{"t": "image", "alt": "Bild"}]}


def test_image_without_alt_gets_a_default_alt() -> None:
    (block,) = conv_assets(f"![]({IMG_PATH})\n", IMG_ASSET)
    assert block == {"t": "figure", "asset": IMG_ASSET, "alt": "Bild"}


def test_image_in_a_table_cell_names_its_asset() -> None:
    (table,) = conv_assets(f"| Bild | Text |\n|---|---|\n| ![a]({IMG_PATH}) | b |\n", IMG_ASSET)
    assert table["t"] == "table"
    image = {"t": "image", "asset": IMG_ASSET, "alt": "a"}
    assert table["rows"] == [[[image], [{"t": "text", "v": "b"}]]]


def test_table_with_inline_markup_still_converts() -> None:
    (table,) = conv("| **a** | `b` |\n|---|--:|\n| ~~c~~ | [d](https://x.org) |\n")
    assert table["align"] == ["left", "right"]
    assert table["head"] == [
        [{"t": "strong", "c": [{"t": "text", "v": "a"}]}],
        [{"t": "code", "v": "b"}],
    ]
    assert table["rows"] == [
        [
            [{"t": "strike", "c": [{"t": "text", "v": "c"}]}],
            [{"t": "link", "url": "https://x.org", "c": [{"t": "text", "v": "d"}]}],
        ]
    ]


def test_image_assets_maps_only_image_names() -> None:
    from typst_service.markdown import image_assets

    other = "img-not-a-uuid.png"
    assert image_assets([IMG_ASSET, "a1-logo.png", other, f"img-{IMG_ID}.svg"]) == {
        IMG_ID: IMG_ASSET
    }


def test_poll_footer_comes_from_the_number_of_answers() -> None:
    for stored, footer in (
        ("1 Antworten · Meinungsbild, kein Beschluss", "1 Antwort"),
        ("1 Antwort", "1 Antwort"),
        ("17 Antworten · Meinungsbild, kein Beschluss", "17 Antworten"),
    ):
        (vote,) = conv(f"> [!abstimmung] **Q**\n> Umfrage · Einzelwahl\n> A: 1\n> {stored}")
        poll = cast("dict[str, object]", vote["poll"])
        assert poll["footer"] == footer
