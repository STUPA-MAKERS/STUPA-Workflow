"""Unit tests of the blackout marks in protocol Markdown (000685-000687, 000965-000967)."""

from __future__ import annotations

import pytest

from app.shared.blackout import BAR, BLOCK_BAR, black_out, has_open_marker


def test_black_out_replaces_each_marked_name_with_the_bar() -> None:
    """§000687: the public text holds the bar, never the marked name."""
    text = "Die Antragstellerin %%Lena Hoffmann%% fragt %%Jonas Weber%%."
    out = black_out(text)
    assert out == f"Die Antragstellerin {BAR} fragt {BAR}."
    assert "Lena" not in out
    assert "Jonas" not in out


def test_black_out_keeps_an_escaped_marker_and_other_text() -> None:
    r"""§000685: a `\%%` is a literal `%%` and starts no marker."""
    assert black_out(r"50 \%% Rabatt") == r"50 \%% Rabatt"
    assert black_out("ohne Marker") == "ohne Marker"


def test_black_out_does_not_span_lines() -> None:
    """§000685: a marker is on one line, so two open markers never join."""
    text = "%%Anna\nBernd%%"
    assert black_out(text) == text
    assert has_open_marker(text)


_DOC = "[Gutachten.pdf](/api/media/documents/0b9d1d3e-7a39-4b3f-9a4e-3c1f2a5b6c7d)"
_BLOCK = f"Vorher %%Anna%%.\n%%\nErster Absatz\n\n- Punkt\n\n{_DOC}\n%%\nDanach."


def test_black_out_parses_a_block_with_paragraphs_and_a_pdf() -> None:
    """§000965: a block between two `%%` lines holds any Markdown and becomes the empty block."""
    out = black_out(_BLOCK)
    assert out == f"Vorher {BAR}.\n{BLOCK_BAR}\nDanach."


def test_black_out_drops_the_pdf_of_a_block() -> None:
    """§000966 §000967: the public text holds no content and no PDF of the block."""
    out = black_out(_BLOCK)
    assert "Erster Absatz" not in out
    assert "/api/media/documents/" not in out
    assert "Punkt" not in out


def test_black_out_keeps_two_blocks_apart() -> None:
    """§000965: the next fence line closes a block, so two blocks stay two blocks."""
    text = "%%\nA\n%%\nMitte\n%%\nB\n%%"
    assert black_out(text) == f"{BLOCK_BAR}\nMitte\n{BLOCK_BAR}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Text\n%%\nGeheim", True),
        ("%%\nGeheim\n%%", False),
        ("%%\nA %%B%%\n%%", False),
        ("%%\nA\n%%\n%%\nB", True),
    ],
)
def test_has_open_marker_for_a_block(text: str, expected: bool) -> None:
    """§000686: a fence line without its closing fence line is open."""
    assert has_open_marker(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("%%Name", True),
        ("%%Name%% und %%Rest", True),
        ("%%Name%%", False),
        ("%%A%% %%B%%", False),
        (r"\%%Name", False),
        ("", False),
        (None, False),
    ],
)
def test_has_open_marker(text: str | None, expected: bool) -> None:
    """§000686: a `%%` without its closing pair is open."""
    assert has_open_marker(text) is expected
