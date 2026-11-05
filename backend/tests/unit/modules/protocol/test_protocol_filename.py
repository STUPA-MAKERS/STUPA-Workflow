"""Unit tests for the download name of a protocol PDF (`protocol_pdf_filename`)."""

from __future__ import annotations

from datetime import date

from app.modules.protocol.filename import TITLE_MAX, protocol_pdf_filename

DAY = date(2026, 11, 5)


def test_title_and_day() -> None:
    name = protocol_pdf_filename("7. ordentliche Sitzung StuPa", DAY)
    assert name == "Protokoll_7._ordentliche_Sitzung_StuPa_2026-11-05.pdf"


def test_public_variant() -> None:
    name = protocol_pdf_filename("Sitzung", DAY, public=True)
    assert name == "Protokoll_Sitzung_2026-11-05_oeffentlich.pdf"


def test_keeps_umlauts_and_drops_unsafe_characters() -> None:
    name = protocol_pdf_filename(' Fachschaft Ökonomie: "Q4"/<Haushalt>?* | ', DAY)
    assert name == "Protokoll_Fachschaft_Ökonomie_Q4_Haushalt_2026-11-05.pdf"


def test_drops_control_and_bidi_characters() -> None:
    name = protocol_pdf_filename("Sitz‮ung\n\tneu\x00", DAY)
    assert name == "Protokoll_Sitzung_neu_2026-11-05.pdf"


def test_empty_title_leaves_the_day() -> None:
    assert protocol_pdf_filename(None, DAY) == "Protokoll_2026-11-05.pdf"
    assert protocol_pdf_filename(" ./\\ ", DAY) == "Protokoll_2026-11-05.pdf"


def test_long_title_is_cut_at_a_word() -> None:
    title = " ".join(["Haushaltsberatung"] * 10)
    stem = protocol_pdf_filename(title, DAY).removeprefix("Protokoll_")
    stem = stem.removesuffix("_2026-11-05.pdf")
    assert len(stem) <= TITLE_MAX
    assert stem.split("_") == ["Haushaltsberatung"] * len(stem.split("_"))


def test_one_long_word_is_cut_hard() -> None:
    stem = protocol_pdf_filename("x" * 200, DAY).removeprefix("Protokoll_")
    assert stem == "x" * TITLE_MAX + "_2026-11-05.pdf"
