"""Unit tests for the document data: title page, logos, signatures."""

from __future__ import annotations

import pytest

from typst_service.document import build_document, format_date
from typst_service.frontmatter import FrontmatterError, split_frontmatter
from typst_service.markdown import ConversionError

from .conftest import FIXTURES

BACKEND_DOC = """---
title: "Sitzung \\"Sommer\\""
typ: protokoll
gremium: "Studierendenparlament"
cd: "stupa"
datum: "2026-06-15 18:30"
date: "2026-06-15"
beginn: "18:30"
ende: "20:05"
protokoll: "Berta Beispiel"
anwesend:
  - "Anna"
  - "Berta"
abwesend:
  - "Gustav"
beschlussfaehigkeit: "Gegeben"
datalines:
  - "Anwesend: 3"
  - "frei"
unterschriften:
  - "Schriftführung"
  - "Vorstand"
---

# TOP
"""


def test_frontmatter_keeps_strings() -> None:
    meta, body = split_frontmatter(
        "---\nbeginn: 18:30\ndatum: 2026-06-15\nx: [a, b]\ny:\n  k: v\n---\n\nBody"
    )
    assert meta == {"beginn": "18:30", "datum": "2026-06-15", "x": ["a", "b"]}
    assert body == "Body"


def test_frontmatter_absent_or_unclosed() -> None:
    assert split_frontmatter("# no fm") == ({}, "# no fm")
    assert split_frontmatter("---\na: b\n") == ({}, "---\na: b\n")


def test_frontmatter_invalid_yaml() -> None:
    with pytest.raises(FrontmatterError):
        split_frontmatter("---\na: [unclosed\n---\n")


@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("2026-06-15", "15.06.2026"),
        ("2026-06-15 18:30", "15.06.2026, 18:30"),
        ("2026-06-15T08:05", "15.06.2026, 08:05"),
        ("gestern", "gestern"),
    ],
)
def test_format_date(raw: str, out: str) -> None:
    assert format_date(raw) == out


def test_backend_document() -> None:
    doc = build_document(BACKEND_DOC, variant="protocol-stupa")
    assert doc["title"] == 'Sitzung "Sommer"'
    assert doc["data"] == [
        ["Datum", "15.06.2026, 18:30"],
        ["Zeit", "18:30 – 20:05"],
        ["Protokoll", "Berta Beispiel"],
        ["Gremium", "Studierendenparlament"],
        ["Beschlussfähigkeit", "Gegeben"],
        ["Anwesend", "3"],
        ["", "frei"],
        ["Anwesend (2)", "Anna, Berta"],
        ["Abwesend (1)", "Gustav"],
    ]
    assert doc["logos"] == [{"name": "STUPA"}]
    assert doc["footer_logos"] == [{"name": "STUPA"}]
    body = doc["body"]
    assert isinstance(body, list)
    assert body[-1] == {
        "t": "signatures",
        "signers": [["Schriftführung", "Berta Beispiel"], ["Vorstand", ""]],
    }


def test_title_falls_back_to_gremium_and_date() -> None:
    doc = build_document("---\ngremium: StuPa\ndatum: 2026-06-15 18:30\n---\n", variant=None)
    assert doc["title"] == "Protokoll der Sitzung des StuPa vom 15.06.2026"
    doc = build_document("---\ngremium: X\n---\n", variant=None)
    assert doc["title"] == "Protokoll der Sitzung des X"
    assert build_document("text", variant=None)["title"] == "Sitzungsprotokoll"


@pytest.mark.parametrize(
    ("variant", "gremium", "logos"),
    [
        ("protocol-stupa", "AStA", [{"name": "STUPA"}]),
        ("protocol-asta", "StuPa", [{"name": "ASTA"}]),
        ("protocol", "asta", [{"name": "ASTA"}]),
        (None, "echo", [{"name": "ECHO"}]),
        (None, "Fachschaft", [{"name": "STUPA"}]),
    ],
)
def test_default_logos(variant: str | None, gremium: str, logos: list[dict[str, str]]) -> None:
    doc = build_document(f"---\ngremium: {gremium}\n---\n", variant=variant)
    assert doc["logos"] == logos


def test_config_logos_override_and_footer_keeps_variant_set() -> None:
    doc = build_document(
        "---\ngremium: StuPa\n---\n",
        variant="protocol-asta",
        config={"logos": ["up.png", "INF"]},
        assets=["up.png"],
    )
    assert doc["logos"] == [{"asset": "up.png"}, {"name": "INF"}]
    # pytex keeps the footer set of the variant when only `logos` is given.
    assert doc["footer_logos"] == [{"name": "ASTA"}]


def test_makers_footer_takes_the_right_aligned_logo() -> None:
    doc = build_document("x", variant=None, config={"logos": "MAKERS"})
    assert doc["logos"] == [{"name": "MAKERS"}]
    doc = build_document("x", variant=None, config={"footer_logos": ["MAKERS-RAlign"]})
    assert doc["footer_logos"] == [{"name": "MAKERS-RAlign"}]


def test_unknown_logo_and_variant() -> None:
    with pytest.raises(ConversionError, match="unknown logo"):
        build_document("x", variant=None, config={"logos": ["missing.png"]})
    with pytest.raises(ConversionError, match="unknown variant"):
        build_document("x", variant="report")


def test_fixture_converts() -> None:
    doc = build_document((FIXTURES / "protocol-full.md").read_text(), variant="protocol-stupa")
    body = doc["body"]
    assert isinstance(body, list)
    kinds = {b["t"] for b in body}
    assert kinds >= {
        "heading",
        "par",
        "tally",
        "callout",
        "table",
        "list",
        "quote",
        "mathblock",
        "codeblock",
        "rule",
        "signatures",
    }
