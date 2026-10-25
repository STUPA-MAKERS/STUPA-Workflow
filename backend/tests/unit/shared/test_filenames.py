"""Unit tests for the two file-name sanitizers and the Content-Disposition helper."""

from __future__ import annotations

import unicodedata
from urllib.parse import unquote

import pytest

from app.shared.filenames import (
    DISPLAY_NAME_MAX,
    STORAGE_NAME_MAX,
    content_disposition,
    sanitize_display_name,
    sanitize_storage_name,
)


@pytest.mark.parametrize(
    "raw",
    [
        "Einführung.pdf",
        "Einführung €.pdf",
        "Straße Ärger Öl.docx",
        "会议记录.pdf",
        "회의록.pdf",
        "протокол.pdf",
        "تقرير.pdf",
        "Beleg 🧾.png",
        "Familie 👨\u200d👩\u200d👧.jpg",
        "ok.pdf",
    ],
)
def test_display_keeps_unicode(raw: str) -> None:
    assert sanitize_display_name(raw) == raw


def test_display_normalizes_to_nfc() -> None:
    decomposed = unicodedata.normalize("NFD", "Einführung.pdf")
    assert decomposed != "Einführung.pdf"
    assert sanitize_display_name(decomposed) == "Einführung.pdf"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        (r"C:\Windows\evil.exe", "evil.exe"),
        ("/abs/path/Bericht.pdf", "Bericht.pdf"),
        ("a/b/c", "c"),
        ("..", "upload"),
        ("../..", "upload"),
        ("dir/", "upload"),
    ],
)
def test_display_strips_path_components(raw: str, expected: str) -> None:
    assert sanitize_display_name(raw) == expected


def test_display_drops_controls_and_line_breaks() -> None:
    assert sanitize_display_name("a\x00b\r\nc\td\x7fe\x85.pdf") == "abcde.pdf"
    assert sanitize_display_name("a\u2028b\u2029c.pdf") == "abc.pdf"


def test_display_drops_lone_surrogates() -> None:
    """Drop the lone surrogates of a surrogateescape decode, which Postgres cannot store."""
    assert sanitize_display_name("bad\udcff.pdf") == "bad.pdf"


@pytest.mark.parametrize(
    "bidi",
    ["\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069"],
)
def test_display_drops_bidi_controls(bidi: str) -> None:
    """Drop the bidi controls, so an override cannot show "Rechnungfdp.exe" as "Rechnungexe.pdf"."""
    assert sanitize_display_name(f"Rechnung{bidi}fdp.exe") == "Rechnungfdp.exe"


def test_display_drops_invisible_characters() -> None:
    assert sanitize_display_name("\ufeffa\u200bb\u2060c\u180e.pdf") == "abc.pdf"


@pytest.mark.parametrize(
    "fmt",
    [
        "\N{LEFT-TO-RIGHT MARK}",
        "\N{RIGHT-TO-LEFT MARK}",
        "\N{ARABIC LETTER MARK}",
        "\N{SOFT HYPHEN}",
        "\N{INVISIBLE TIMES}",
        "\N{INHIBIT SYMMETRIC SWAPPING}",
        "\N{INTERLINEAR ANNOTATION ANCHOR}",
        "\N{TAG LATIN CAPITAL LETTER A}\N{TAG LATIN CAPITAL LETTER B}",
    ],
)
def test_display_drops_every_format_character(fmt: str) -> None:
    """Drop every format character, tag characters included, which hide text from a person."""
    assert sanitize_display_name(f"Bericht{fmt}final.pdf") == "Berichtfinal.pdf"


def test_display_keeps_joiners_inside_and_drops_loose_ones() -> None:
    """Keep a joiner inside an emoji sequence or a word and drop a loose one.

    At an edge, next to a dot or a space, or doubled, a joiner only hides something.
    """
    assert sanitize_display_name("a\u200db.pdf") == "a\u200db.pdf"
    assert sanitize_display_name("می\u200cخواهم.pdf") == "می\u200cخواهم.pdf"
    assert sanitize_display_name("\u200dabc.pdf\u200c") == "abc.pdf"
    assert sanitize_display_name("abc\u200d.pdf") == "abc.pdf"
    assert sanitize_display_name("a\u200d b.pdf") == "a b.pdf"
    assert sanitize_display_name("a\u200d\u200db.pdf") == "ab.pdf"


def test_display_maps_space_separators_and_trims() -> None:
    assert sanitize_display_name("\u00a0 Bericht\u3000final .pdf. ") == "Bericht final .pdf"
    assert sanitize_display_name("  .hidden") == "hidden"


@pytest.mark.parametrize("raw", [None, "", "   ", "...", "\u202e", "\u200d", "\x00\r\n"])
def test_display_falls_back_when_empty(raw: str | None) -> None:
    assert sanitize_display_name(raw) == "upload"
    assert sanitize_display_name(raw, default="beleg.pdf") == "beleg.pdf"


def test_display_caps_length_and_keeps_extension() -> None:
    name = sanitize_display_name("ä" * 500 + ".pdf")
    assert len(name) == DISPLAY_NAME_MAX
    assert name.endswith("ä.pdf")


def test_display_cap_without_short_extension_cuts_plainly() -> None:
    assert len(sanitize_display_name("x" * 500)) == DISPLAY_NAME_MAX
    long_ext = "a." + "b" * 300
    assert sanitize_display_name(long_ext) == long_ext[:DISPLAY_NAME_MAX]


def test_display_cap_drops_a_joiner_that_the_cut_exposed() -> None:
    stem = "x" * (DISPLAY_NAME_MAX - 5) + "\u200d" + "y" * 50
    name = sanitize_display_name(stem + ".pdf")
    assert "\u200d" not in name
    assert name.endswith("x.pdf")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Einführung.pdf", "Einfuhrung.pdf"),
        ("Einführung €.pdf", "Einfuhrung _.pdf"),
        ("会议.pdf", "__.pdf"),
        ("Beleg 🧾.png", "Beleg _.png"),
        ("a\x00b\nc;d.pdf", "a_b_c_d.pdf"),
        ("Rechnung\u202efdp.exe", "Rechnung_fdp.exe"),
        ("../../etc/passwd", "passwd"),
        (r"C:\Windows\evil.exe", "evil.exe"),
        ("/abs/path/report.pdf", "report.pdf"),
    ],
)
def test_storage_name_is_ascii(raw: str, expected: str) -> None:
    out = sanitize_storage_name(raw)
    assert out == expected
    assert out.isascii()
    assert "/" not in out
    assert "\\" not in out


@pytest.mark.parametrize("raw", [None, "", "   ", "...", "..", "a/.."])
def test_storage_name_falls_back_when_empty(raw: str | None) -> None:
    assert sanitize_storage_name(raw) == "upload"


def test_storage_name_caps_length() -> None:
    out = sanitize_storage_name("ü" * 500 + ".pdf")
    assert len(out) == STORAGE_NAME_MAX
    assert out.endswith("u.pdf")


def test_storage_name_of_a_display_name_never_has_a_separator() -> None:
    for raw in [
        "..\\..\\x",
        "a/b/../c",
        "\u2215fake-slash.pdf",
        "\uff0e\uff0e/x",
        "\uff0e\uff0e",
        "a\uff0f..",
        "a\uff0fb.pdf",
    ]:
        out = sanitize_storage_name(sanitize_display_name(raw))
        assert "/" not in out
        assert out not in {"", ".", ".."}


def _parts(value: str) -> tuple[str, str, str]:
    kind, plain, ext = value.split("; ")
    assert plain.startswith('filename="')
    assert plain.endswith('"')
    assert ext.startswith("filename*=UTF-8''")
    return kind, plain[len('filename="') : -1], ext[len("filename*=UTF-8''") :]


def test_disposition_carries_fallback_and_utf8_name() -> None:
    value = content_disposition("attachment", "Einführung €.pdf")
    assert value == (
        "attachment; filename=\"Einfuhrung _.pdf\"; "
        "filename*=UTF-8''Einf%C3%BChrung%20%E2%82%AC.pdf"
    )
    value.encode("latin-1")


def test_disposition_inline_kind() -> None:
    kind, plain, ext = _parts(content_disposition("inline", "a.pdf"))
    assert (kind, plain, ext) == ("inline", "a.pdf", "a.pdf")


@pytest.mark.parametrize(
    "name",
    [
        'a"b.pdf',
        "a\\b.pdf",
        "a\r\nSet-Cookie: x=1.pdf",
        "x;y=z%41.pdf",
        "😀😀😀.png",
        "会议记录.pdf",
        "Rechnung\u202efdp.exe",
        "\u0301",
        "a\uff0fb.pdf",
    ],
)
def test_disposition_is_ascii_and_cannot_inject(name: str) -> None:
    value = content_disposition("attachment", name)
    assert value.isascii()
    value.encode("latin-1")
    assert "\r" not in value
    assert "\n" not in value
    _kind, plain, ext = _parts(value)
    assert plain
    assert '"' not in plain
    assert "\\" not in plain
    assert "%" not in plain
    assert ";" not in plain
    assert "/" not in plain
    assert unquote(ext) == sanitize_display_name(name, default="download")


def test_disposition_round_trips_a_long_name() -> None:
    name = "Ä" * 300 + ".pdf"
    _kind, _plain, ext = _parts(content_disposition("attachment", name))
    assert unquote(ext) == sanitize_display_name(name)


def test_disposition_caps_a_fallback_that_the_fold_expands() -> None:
    """Cap a fallback name that the NFKD fold expands.

    NFKD makes U+FDFA into 18 characters. Without the cap the header passes 5 KB, and nginx
    answers 502 above its proxy_buffer_size of 4 KB.
    """
    name = "ﷺ" * 300 + ".pdf"
    value = content_disposition("attachment", name)
    _kind, plain, ext = _parts(value)
    assert len(plain) == DISPLAY_NAME_MAX
    assert plain.endswith(".pdf")
    assert unquote(ext) == sanitize_display_name(name)
    assert len(value) < 3000


def test_disposition_default_for_an_empty_name() -> None:
    _kind, plain, ext = _parts(content_disposition("attachment", "\u202e"))
    assert (plain, ext) == ("download", "download")
    _kind, plain, _ext = _parts(content_disposition("attachment", "", default="beleg.pdf"))
    assert plain == "beleg.pdf"
