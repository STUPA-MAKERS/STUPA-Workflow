"""Tests des gebrandeten HTML-Mail-Layouts (#4)."""

from __future__ import annotations

from app.modules.notifications.layout import (
    reason_text,
    render_layout,
    text_to_html,
)


def test_text_to_html_escapes_and_paragraphs() -> None:
    html = text_to_html("Hallo <b>,\nZeile 2\n\nAbsatz 2 & mehr")
    assert "&lt;b&gt;" in html
    assert "&amp; mehr" in html
    assert html.count("<p") == 2
    assert "Zeile 2" in html and "<br>" in html


def test_render_layout_wraps_content_with_footer() -> None:
    out = render_layout(
        content_html="<p>Inhalt</p>",
        title='Update zu "Beamer" <kaufen>',
        site_name="StuPa <Plattform>",
        base_url="https://antrag.example.org/",
        reason=reason_text("status_update", "de"),
        lang="de",
    )
    assert out.startswith("<!DOCTYPE html>")
    assert "<p>Inhalt</p>" in out
    # Titel/Site-Name werden escaped.
    assert "&lt;kaufen&gt;" in out
    assert "StuPa &lt;Plattform&gt;" in out
    # Footer: Auslöser-Hinweis + Link zu den Benachrichtigungs-Einstellungen.
    assert "Sie erhalten diese E-Mail" in out
    assert "https://antrag.example.org/account/notifications" in out


def test_reason_text_falls_back_to_generic_and_de() -> None:
    assert reason_text("nope", "de") == reason_text("generic", "de")
    assert reason_text("magic_link", "fr") == reason_text("magic_link", "de")
    assert reason_text("magic_link", "en") != reason_text("magic_link", "de")
