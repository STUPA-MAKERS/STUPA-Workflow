"""Unit tests of the Markdown of the Antrag PDF (specs 000881, 000882, 000886)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.modules.documents.application_markdown import (
    BAR,
    NOT_VISIBLE,
    ApplicationDoc,
    DecisionView,
    FormSection,
    build_application_document,
    escape,
    format_day,
    is_empty,
)
from app.modules.documents.router import application_pdf_filename
from app.shared.config_schemas import FormFieldDef


def _field(**kwargs: Any) -> FormFieldDef:
    return FormFieldDef.model_validate(kwargs)


SECTIONS = (
    FormSection(
        "Antrag",
        (
            _field(key="title", type="text", label={"de": "Titel"}),
            _field(key="org", type="text", label={"de": "Organisation"}),
            _field(
                key="art",
                type="select",
                label={"de": "Art"},
                options=[{"value": "fahrt", "label": {"de": "Exkursion"}}],
            ),
            _field(
                key="ziel",
                type="text",
                label={"de": "Ziel"},
                visibleIf={"==": [{"var": "art"}, "andere"]},
            ),
            _field(key="iban", type="iban", label={"de": "IBAN"}, isPII=True),
            _field(key="beleg", type="file", label={"de": "Beleg"}),
            _field(key="leer", type="text", label={"de": "Leer"}),
        ),
    ),
    FormSection(
        "Kosten",
        (
            _field(key="kosten", type="positions", label={"de": "Kostenaufstellung"}),
            _field(key="foerderung", type="funding", label={"de": "Förderung"}),
            _field(key="zeit", type="daterange", label={"de": "Zeitraum"}),
            _field(key="text", type="textarea", label={"de": "Beschreibung"}),
            _field(key="liste", type="table", label={"de": "Teilnehmende"}),
            _field(key="ok", type="checkbox", label={"de": "Bestätigt"}),
        ),
    ),
)

DATA: dict[str, object] = {
    "title": "Exkursion *Stuttgart*",
    "org": "Fachschaft [Informatik]",
    "art": "fahrt",
    "ziel": "versteckt",
    "iban": "DE02120300000000202051",
    "leer": "  ",
    "kosten": [
        {
            "label": "Bus",
            "offers": [
                {"label": "Müller", "value": 1200, "preferred": True},
                {"label": "Flix", "value": 1450, "preferred": False},
            ],
        },
        {"label": "Haus", "offers": [], "noOffers": True, "noOffersReason": "einzig"},
    ],
    "foerderung": 1000,
    "zeit": {"from": "2026-12-01", "to": "2026-12-03"},
    "text": "Wir fahren.\n# Programm\n![x](http://evil/x.png) 50%%rabatt%%",
    "liste": [{"Name": "Anna", "Rolle": "Leitung"}],
    "ok": False,
    "alt": "aus alter Version",
}


def _doc(**kwargs: Any) -> ApplicationDoc:
    base: dict[str, Any] = {
        "title": "Exkursion *Stuttgart*",
        "type_name": "Finanzantrag",
        "gremium_name": "Studierendenparlament",
        "cd_variant": "stupa",
        "state_label": "Bewilligt",
        "received_on": date(2026, 11, 10),
        "applicant": "Max Muster (max@example.org)",
        "version": 3,
        "sections": SECTIONS,
        "data": DATA,
        "files": ("Angebot.pdf",),
        "decision": DecisionView(
            Decimal("900"), ("Belege einreichen",), datetime(2026, 11, 12, 19, 0), "StuPa"
        ),
    }
    return ApplicationDoc(**{**base, **kwargs})


def test_document_has_the_parts_in_order() -> None:
    md = build_application_document(_doc())
    order = ["# Antrag", "# Kosten", "# Weitere Angaben", "# Anhänge", "# Beschluss"]
    assert [md.index(h + "\n") for h in order] == sorted(md.index(h + "\n") for h in order)
    assert "typ: antrag" in md
    assert '  - "Antragsart: Finanzantrag"' in md
    assert '  - "Status: Bewilligt"' in md
    assert '  - "Eingang: 10.11.2026"' in md
    assert '  - "Antragsteller: Max Muster (max@example.org)"' in md
    assert '  - "Version: 3"' in md


def test_answers_are_formatted_and_escaped() -> None:
    md = build_application_document(_doc())
    assert "**Organisation:** Fachschaft \\[Informatik\\]" in md
    assert "**Art:** Exkursion" in md
    assert "**Förderung:** 1\\.000,00 €" in md
    assert "**Zeitraum:** 01\\.12\\.2026 – 03\\.12\\.2026" in md
    assert "**Bestätigt:** Nein" in md
    assert "| Bus | Müller (bevorzugt) | 1.200,00 € |" in md
    assert "| Keine Vergleichsangebote: einzig |" in md
    assert "| **Summe** | | **1.200,00 €** |" in md
    assert "| Name | Rolle |" in md and "| Anna | Leitung |" in md
    assert "**alt:** aus alter Version" in md


def test_hidden_fields_files_and_head_keys_are_left_out() -> None:
    md = build_application_document(_doc())
    assert "versteckt" not in md
    assert "**Leer" not in md
    assert "**Beleg" not in md
    assert "**Titel" not in md
    assert "- Angebot\\.pdf" in md


def test_textarea_stays_markdown_without_headings_images_and_bars() -> None:
    md = build_application_document(_doc())
    assert "\\# Programm" in md
    assert "\\![x]" in md
    assert "%%" not in md.split("# Kosten", 1)[1]


def test_a_field_the_reader_may_not_read_shows_not_visible() -> None:
    data = {k: v for k, v in DATA.items() if k != "iban"}
    md = build_application_document(_doc(data=data, hidden_keys=frozenset({"iban"})))
    assert f"**IBAN:** {NOT_VISIBLE}" in md


def test_public_variant_blacks_out_pii_and_applicant() -> None:
    md = build_application_document(
        _doc(redacted_keys=frozenset({"iban", "alt"}), redact_applicant=True, decision=None)
    )
    assert "DE02" not in md and "Max Muster" not in md
    assert f"**IBAN:** {BAR}" in md
    assert f"**alt:** {BAR}" in md
    assert f'  - "Antragsteller: {BAR}"' in md
    assert "# Beschluss" not in md


def test_decision_as_requested_without_conditions() -> None:
    decision = DecisionView(None, (), datetime(2026, 11, 12, 19, 0))
    md = build_application_document(_doc(decision=decision, files=()))
    assert "**Bewilligter Betrag:** wie beantragt" in md
    assert "Auflagen" not in md
    assert "# Anhänge" not in md


def test_an_empty_antrag_has_only_the_head() -> None:
    md = build_application_document(
        _doc(data={}, decision=None, files=(), title="", applicant=None, state_label=None)
    )
    assert 'title: "Antrag"' in md
    assert "Antragsteller" not in md and "Status" not in md
    assert md.rstrip().endswith("---")


def test_helpers() -> None:
    assert escape("a\n*b*  %%c%%") == "a \\*b\\* %⁠%c%⁠%"
    assert format_day("2026-01-02") == "02.01.2026"
    assert format_day("bald") == "bald"
    assert is_empty({"from": "", "to": None})
    assert not is_empty(0) and not is_empty(False)


def test_file_name() -> None:
    assert (
        application_pdf_filename("Exkursion: Stuttgart/Ulm", date(2026, 11, 10))
        == "Antrag_Exkursion_Stuttgart_Ulm_2026-11-10.pdf"
    )
    assert application_pdf_filename("", None) == "Antrag.pdf"


def test_more_field_types() -> None:
    sections = (
        FormSection(
            "Mehr",
            (
                _field(key="tag", type="date", label={"de": "Tag"}),
                _field(key="tag2", type="date", label={"de": "Tag2"}),
                _field(
                    key="multi",
                    type="multiselect",
                    label={"de": "Multi"},
                    options=[{"value": "a", "label": {"de": "Alpha"}}],
                ),
                _field(key="betrag", type="currency", label={"de": "Betrag"}),
                _field(key="summe", type="computed", label={"de": "Summe"}, compute={"+": [1, 2]}),
                _field(
                    key="kaputt", type="computed", label={"de": "Kaputt"}, compute={"/": [1, 0]}
                ),
                _field(key="tab", type="table", label={"de": "Tab"}),
                _field(key="obj", type="text", label={"de": "Obj"}),
                _field(key="rng", type="daterange", label={"de": "Rng"}),
                _field(
                    key="cond",
                    type="text",
                    label={"de": "Cond"},
                    visibleIf={"/": [1, 0]},
                ),
            ),
        ),
    )
    data: dict[str, object] = {
        "tag": "2026-03-04",
        "tag2": 5,
        "multi": ["a", "z"],
        "betrag": "abc",
        "tab": "kein Tabellenwert",
        "obj": {"x": [1, True]},
        "rng": "frei",
        "cond": "sichtbar",
    }
    md = build_application_document(_doc(sections=sections, data=data, decision=None))
    assert "**Tag:** 04\\.03\\.2026" in md
    assert "**Tag2:** 5" in md
    assert "**Multi:** Alpha, z" in md
    assert "**Betrag:** abc" in md
    assert "**Summe:** 3" in md
    assert "Kaputt" not in md
    assert "**Tab:** kein Tabellenwert" in md
    assert "**Obj:** x: 1, Ja" in md
    assert "**Rng:** frei" in md
    assert "**Cond:** sichtbar" in md
