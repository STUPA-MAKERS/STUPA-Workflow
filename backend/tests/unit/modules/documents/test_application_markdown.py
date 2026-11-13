"""Unit tests of the Markdown of the Antrag PDF (specs 000881, 000882, 000886).

The Antrag is field rows (`> [!feld] Label` and the value below it) that the render
service draws as tables of two columns.
"""

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
    field_row,
    format_day,
    is_empty,
    offer_name,
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


def row(label: str, *value: str) -> str:
    """The Markdown of one field row, as the builder writes it."""
    return "\n".join(field_row(label, value))


def _doc(**kwargs: Any) -> ApplicationDoc:
    base: dict[str, Any] = {
        "title": "Exkursion *Stuttgart*",
        "type_name": "Finanzantrag",
        "gremium_name": "Studierendenparlament",
        "cd_variant": "stupa",
        "state_label": "Bewilligt",
        "received_on": date(2026, 11, 10),
        "applicant": "Max Muster",
        "applicant_email": "max@example.org",
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
    head = md.split("---\n", 2)[2]
    order = [row("Antragsart", "Finanzantrag"), "# Antrag", "# Kosten"]
    order += ["# Weitere Angaben", "# Beschluss"]
    assert [md.index(h) for h in order] == sorted(md.index(h) for h in order)
    assert "typ: antrag" in md
    assert "datalines" not in md
    assert head.lstrip().startswith(row("Antragsart", "Finanzantrag"))
    assert "[!feld] Gremium" not in md.split("# Beschluss")[0]
    assert row("Antragsart", "Finanzantrag") in md
    assert row("Status", "Bewilligt") in md
    assert row("Eingang", "`10.11.2026`") in md
    mail = "[`max@example.org`](mailto:max@example.org)"
    assert row("Antragsteller", "Max Muster\\", mail) in md
    assert row("Version", "`3`") in md
    assert row("Anhänge", "`Angebot.pdf`") in md


def test_the_signature_section_ends_the_document_only_with_the_switch() -> None:
    """§000888: two rows to sign by hand, after the decision."""
    assert "[!unterschrift]" not in build_application_document(_doc())
    md = build_application_document(_doc(signatures=True))
    first = "> [!unterschrift] Sachlich richtig\n>\n> Finanzreferent:in\n"
    second = "> [!unterschrift] Ausführungsermächtigt\n>\n> Haushaltsbeauftragte:r\n"
    assert md.index("# Beschluss") < md.index("# Unterschriften") < md.index(first)
    assert md.endswith(second)


def test_answers_are_formatted_and_escaped() -> None:
    md = build_application_document(_doc())
    assert row("Organisation", "Fachschaft \\[Informatik\\]") in md
    assert row("Art", "Exkursion") in md
    assert row("Förderung", "`1.000,00 €`") in md
    assert row("Zeitraum", "`01.12.2026 – 03.12.2026`") in md
    assert row("Bestätigt", "Nein") in md
    assert "> | Bus | Müller (bevorzugt) | `1.200,00 €` |" in md
    assert "> | | Keine Vergleichsangebote: einzig | |" in md
    assert "> | **Summe** | | **`1.200,00 €`** |" in md
    assert "> | Name | Rolle |" in md and "> | Anna | Leitung |" in md
    assert row("alt", "aus alter Version") in md


def test_hidden_fields_files_and_head_keys_are_left_out() -> None:
    md = build_application_document(_doc())
    assert "versteckt" not in md
    assert "[!feld] Leer" not in md
    assert "[!feld] Beleg" not in md
    assert "[!feld] Titel" not in md


def test_textarea_renders_markdown_and_neutralizes_document_constructs() -> None:
    sections = (FormSection("Text", (_field(key="t", type="textarea", label={"de": "T"}),)),)
    text = (
        "Wir *fahren*.\n## Programm\n- A\n\n![x](http://evil/x.png) 50%%rabatt%%\n"
        "> [!abstimmung]\n{{title}} $x$ [d](/api/media/documents/1)\n#\n"
    )
    md = build_application_document(_doc(sections=sections, data={"t": text}, decision=None))
    body = md.split("[!feld] T", 1)[1]
    assert "> Wir *fahren*." in body
    assert "> **Programm**" in body and "#" not in body.split("\n\n", 1)[0]
    assert "> - A" in body
    assert "\\![x]" in body and "\\[!abstimmung]" in body
    assert "{\u2060{title}}" in body and "\\$x\\$" in body
    assert "/api/media/documents\u2060/1" in body
    assert "%%" not in body


def test_a_field_the_reader_may_not_read_shows_not_visible() -> None:
    data = {k: v for k, v in DATA.items() if k != "iban"}
    md = build_application_document(_doc(data=data, hidden_keys=frozenset({"iban"})))
    assert row("IBAN", NOT_VISIBLE) in md


def test_public_variant_blacks_out_pii_and_applicant() -> None:
    md = build_application_document(
        _doc(redacted_keys=frozenset({"iban", "alt"}), redact_applicant=True, decision=None)
    )
    assert "DE02" not in md and "Max Muster" not in md
    assert row("IBAN", BAR) in md
    assert row("alt", BAR) in md
    assert row("Antragsteller", BAR) in md
    assert "# Beschluss" not in md


def test_decision_as_requested_without_conditions() -> None:
    decision = DecisionView(None, (), datetime(2026, 11, 12, 19, 0))
    md = build_application_document(_doc(decision=decision, files=()))
    assert row("Bewilligter Betrag", "wie beantragt") in md
    assert row("Beschlossen am", "`12.11.2026`") in md
    assert "[!feld] Gremium" not in md
    assert "Auflagen" not in md
    assert "Anhänge" not in md


def test_a_vote_decision_names_its_result_and_a_rejected_one_has_no_amount() -> None:
    """§000881: the result of the vote prints; a vote that did not pass approves nothing."""
    when = datetime(2026, 11, 12, 19, 0)
    passed = DecisionView(None, (), when, "StuPa", result="Angenommen")
    md = build_application_document(_doc(decision=passed))
    assert row("Ergebnis", "Angenommen") in md
    assert row("Bewilligter Betrag", "wie beantragt") in md
    rejected = DecisionView(None, (), when, "StuPa", result="Abgelehnt", approved=False)
    md = build_application_document(_doc(decision=rejected))
    assert row("Ergebnis", "Abgelehnt") in md
    assert "[!feld] Bewilligter Betrag" not in md


def test_an_offer_that_is_a_web_address_is_a_short_link() -> None:
    """§000881: the link text drops scheme, www and the closing slash and is cut at 40."""
    assert offer_name("https://www.epidemicsound.com/business/") == (
        "[epidemicsound\\.com/business](https://www.epidemicsound.com/business/)"
    )
    long = "https://example.org/" + "a" * 60
    assert offer_name(long) == f"[example\\.org/{'a' * 27}…]({long})"
    assert offer_name("Firma (A) https://x.org") == "Firma \\(A\\) https://x\\.org"
    assert offer_name(" ") == "—"


def test_the_decision_lists_its_conditions() -> None:
    md = build_application_document(_doc())
    assert row("Gremium", "StuPa") + "\n" + row("Beschlossen am", "`12.11.2026`") in md
    assert row("Bewilligter Betrag", "`900,00 €`") in md
    assert row("Auflagen", "Belege einreichen") in md


def test_several_conditions_are_paragraphs_with_a_rule_between() -> None:
    decision = DecisionView(None, ("Erste *Auflage*", "Zweite"), datetime(2026, 11, 12, 19, 0))
    md = build_application_document(_doc(decision=decision))
    assert row("Auflagen", "Erste \\*Auflage\\*", "", "---", "", "Zweite") in md


def test_an_empty_antrag_has_only_the_head() -> None:
    md = build_application_document(
        _doc(
            data={},
            decision=None,
            files=(),
            title="",
            applicant=None,
            applicant_email=None,
            state_label=None,
        )
    )
    assert 'title: "Antrag"' in md
    assert "Antragsteller" not in md and "Status" not in md
    assert md.rstrip().endswith(row("Version", "`3`").rstrip())


def test_several_files_stand_one_per_line_in_code() -> None:
    md = build_application_document(_doc(files=("a.pdf", "b `c`.pdf")))
    assert row("Anhänge", "`a.pdf`\\", "`b 'c'.pdf`") in md


def test_the_applicant_shows_what_is_known() -> None:
    only_mail = build_application_document(_doc(applicant=None))
    assert row("Antragsteller", "[`max@example.org`](mailto:max@example.org)") in only_mail
    only_name = build_application_document(_doc(applicant_email=None))
    assert row("Antragsteller", "Max Muster") in only_name
    odd = build_application_document(_doc(applicant_email="a)b@x.org"))
    assert row("Antragsteller", "Max Muster\\", "`a)b@x.org`") in odd


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
    assert row("Tag", "`04.03.2026`") in md
    assert row("Tag2", "`5`") in md
    assert row("Multi", "Alpha, z") in md
    assert row("Betrag", "`abc`") in md
    assert row("Summe", "3") in md
    assert "Kaputt" not in md
    assert row("Tab", "kein Tabellenwert") in md
    assert row("Obj", "x: 1, Ja") in md
    assert row("Rng", "`frei`") in md
    assert row("Cond", "sichtbar") in md
