"""Unit-Tests Markdown-Gen + Frontmatter-Variante (T-20, Akzeptanz: flows §6).

Reine, DB-freie Logik: Frontmatter je Gremium, Variante-Mapping, Wert-Formatierung,
PII-Ausschluss, YAML-/Markdown-Injection-Sicherheit.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.pdf.markdown import (
    DEFAULT_VARIANT,
    ApplicationDoc,
    TimelineItem,
    VoteResult,
    build_application_markdown,
    variant_for,
)
from app.shared.config_schemas import FormFieldDef


def _field(key: str, label: str) -> FormFieldDef:
    return FormFieldDef.model_validate(
        {"key": key, "type": "text", "label": {"de": label}}
    )


def _doc(**over: object) -> ApplicationDoc:
    base: dict[str, object] = {
        "application_id": "app-1",
        "type_name": "Förderantrag",
        "gremium_slug": "stupa",
        "cd_variant": "stupa",
        "lang": "de",
        "default_lang": "de",
        "fields": [_field("title", "Titel"), _field("amount", "Betrag")],
        "data": {"title": "Projekt X", "amount": 1200},
    }
    base.update(over)
    return ApplicationDoc(**base)  # type: ignore[arg-type]


def test_variant_for_maps_makers_else_report() -> None:
    assert variant_for("makers") == "report-makers"
    assert variant_for("stupa") == DEFAULT_VARIANT
    assert variant_for(None) == DEFAULT_VARIANT


def test_frontmatter_carries_gremium_and_variant() -> None:
    md = build_application_markdown(_doc(created_at=datetime(2026, 6, 7, tzinfo=UTC)))
    assert md.startswith("---\n")
    assert 'gremium: "stupa"' in md
    assert 'typ: antrag' in md
    assert 'cd: "stupa"' in md
    assert 'date: "2026-06-07"' in md


def test_fields_rendered_with_labels_and_values() -> None:
    md = build_application_markdown(_doc())
    assert "## Antragsdaten" in md
    assert "- **Titel:** Projekt X" in md
    assert "- **Betrag:** 1200" in md


def test_applicant_name_in_heading_and_title() -> None:
    md = build_application_markdown(_doc(applicant_name="Erika M."))
    assert "# Förderantrag — Erika M." in md
    assert 'title: "Förderantrag — Erika M."' in md


def test_vote_and_timeline_sections() -> None:
    doc = _doc(
        vote=VoteResult(title="Annahme?", result="passed", counts={"yes": 5, "no": 1}),
        timeline=[
            TimelineItem(
                at=datetime(2026, 6, 1, tzinfo=UTC), state_label="Eingereicht"
            ),
            TimelineItem(
                at=datetime(2026, 6, 2, tzinfo=UTC), state_label="Angenommen", note="ok"
            ),
        ],
    )
    md = build_application_markdown(doc)
    assert "## Abstimmung" in md
    assert "- **Annahme?:** passed" in md
    assert "Stimmen: yes: 5, no: 1" in md
    assert "## Verlauf" in md
    assert "- 2026-06-01 — Eingereicht" in md
    assert "- 2026-06-02 — Angenommen (ok)" in md


def test_value_formatting_list_bool_none_dict() -> None:
    doc = _doc(
        fields=[
            _field("tags", "Tags"),
            _field("flag", "Flag"),
            _field("missing", "Fehlt"),
            _field("meta", "Meta"),
        ],
        data={"tags": ["a", "b"], "flag": True, "missing": None, "meta": {"k": "v"}},
    )
    md = build_application_markdown(doc)
    assert "- **Tags:** a, b" in md
    assert "- **Flag:** ja" in md
    assert "- **Fehlt:** —" in md
    assert "- **Meta:** k: v" in md


def test_yaml_injection_is_escaped() -> None:
    # Ein Antragsteller-Name mit Newline + Quote darf das Frontmatter nicht sprengen.
    md = build_application_markdown(_doc(applicant_name='x"\n---\ngremium: evil'))
    lines = md.splitlines()
    # Genau zwei `---`-Zeilen (Frontmatter-Start/-Ende), keine eingeschleuste dritte.
    assert lines.count("---") == 2
    # Im Frontmatter-Block exakt ein `gremium:`-Key — der injizierte Wert bleibt als
    # escaptes Skalar im title-Feld gefangen, wird keine eigene Direktive.
    fm = lines[1 : lines.index("---", 1)]
    assert sum(1 for ln in fm if ln.startswith("gremium:")) == 1
    assert "\\n" in md  # Newline wurde escaped, nicht als echter Umbruch übernommen


def test_markdown_value_newline_collapsed() -> None:
    doc = _doc(
        fields=[_field("desc", "Beschreibung")],
        data={"desc": "Zeile1\nZeile2"},
    )
    md = build_application_markdown(doc)
    assert "- **Beschreibung:** Zeile1 Zeile2" in md


def test_yaml_scalar_escapes_tab_and_control_chars() -> None:
    # Tab + Steuerzeichen werden escaped (kein roher Umbruch/Steuerzeichen im YAML).
    md = build_application_markdown(_doc(applicant_name="a\tb\x01c"))
    fm = md.splitlines()[1 : md.splitlines().index("---", 1)]
    title_line = next(ln for ln in fm if ln.startswith("title:"))
    assert "\\t" in title_line
    assert "\\x01" in title_line
    assert "\t" not in title_line


def test_frontmatter_minimal_without_gremium_cd_date() -> None:
    md = build_application_markdown(
        _doc(gremium_slug=None, cd_variant=None, created_at=None)
    )
    assert "gremium:" not in md
    assert "cd:" not in md
    assert "date:" not in md
    assert "typ: antrag" in md


def test_lang_fallback_uses_default_lang() -> None:
    doc = _doc(
        lang="en",
        default_lang="de",
        fields=[_field("title", "Titel")],
        data={"title": "X"},
    )
    md = build_application_markdown(doc)
    assert "- **Titel:** X" in md  # de-Label als Fallback
    assert 'lang: "en"' in md
