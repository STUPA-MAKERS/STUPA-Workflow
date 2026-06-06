"""Mail-Template-Render (Jinja2, i18n DE/EN, Platzhalter, Vorschau).

Reine Render-Logik auf Dicts (`*_i18n`) — keine DB. Sprache wird mit Fallback DE
aufgelöst (i18n-Helfer), dann via **gesandboxtem** Jinja2 mit dem Kontext gerendert.
Sandbox + `StrictUndefined`: unbekannte Platzhalter scheitern laut (Vorschau zeigt
den Fehler), kein Zugriff auf gefährliche Attribute trotz Admin-Autorschaft.
"""

from __future__ import annotations

from dataclasses import dataclass

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from app.shared.i18n import I18nMap

_env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
_env_html = SandboxedEnvironment(undefined=StrictUndefined, autoescape=True)


class TemplateRenderError(Exception):
    """Render fehlgeschlagen (unbekannter Platzhalter, Syntaxfehler, …)."""


@dataclass(frozen=True, slots=True)
class RenderedMail:
    """Gerendertes Ergebnis (eine Sprache)."""

    subject: str
    text: str
    html: str | None
    lang: str


def _resolve(value: I18nMap | None, lang: str, default_lang: str) -> tuple[str | None, str]:
    """Text + tatsächlich genutzte Sprache (für Anzeige/Debug)."""
    if not value:
        return None, lang
    if lang in value:
        return value[lang], lang
    if default_lang in value:
        return value[default_lang], default_lang
    used = next(iter(value), lang)
    return value[used], used


def _sanitize_subject(value: str) -> str:
    """Header-Injection abwehren: CR/LF (und weitere Zeilenumbrüche) aus dem Subject
    entfernen, sonst könnte Kontext-Input zusätzliche Mail-Header schmuggeln
    (security.md). `splitlines()` deckt \\r \\n \\r\\n \\v \\f u. a. ab."""
    return " ".join(value.splitlines()).strip()


def _render_str(template_str: str, context: dict[str, object], *, html: bool) -> str:
    env = _env_html if html else _env
    try:
        return env.from_string(template_str).render(**context)
    except TemplateError as exc:
        raise TemplateRenderError(str(exc)) from exc


def render_mail(
    *,
    subject_i18n: I18nMap,
    body_i18n: I18nMap,
    body_html_i18n: I18nMap | None = None,
    context: dict[str, object],
    lang: str = "de",
    default_lang: str = "de",
) -> RenderedMail:
    """Subject/Body (+ optional HTML) in `lang` rendern (Fallback `default_lang`)."""
    subject_tpl, used = _resolve(subject_i18n, lang, default_lang)
    body_tpl, _ = _resolve(body_i18n, lang, default_lang)
    if subject_tpl is None or body_tpl is None:
        raise TemplateRenderError("template missing subject or body")
    html_tpl, _ = _resolve(body_html_i18n, lang, default_lang)

    subject = _sanitize_subject(_render_str(subject_tpl, context, html=False))
    text = _render_str(body_tpl, context, html=False)
    html = _render_str(html_tpl, context, html=True) if html_tpl else None
    return RenderedMail(subject=subject, text=text, html=html, lang=used)
