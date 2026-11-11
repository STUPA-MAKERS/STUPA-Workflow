"""Unit tests of the blackout marks in protocol Markdown (specs 000685, 000686, 000687)."""

from __future__ import annotations

import pytest

from app.shared.blackout import BAR, black_out, has_open_marker


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
