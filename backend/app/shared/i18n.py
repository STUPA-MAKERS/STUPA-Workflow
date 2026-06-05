"""i18n-Helfer für DB-`*_i18n`-JSONB (overview §5).

Konfigurierbare Texte: angeforderte Sprache, sonst Fallback `default_lang` (DE),
sonst erster vorhandener Wert.
"""

from __future__ import annotations

I18nMap = dict[str, str]


def resolve_i18n(
    value: I18nMap | None, lang: str, default_lang: str = "de"
) -> str | None:
    """Text in `lang` auflösen; Fallback `default_lang`, dann beliebig vorhanden."""
    if not value:
        return None
    if lang in value:
        return value[lang]
    if default_lang in value:
        return value[default_lang]
    return next(iter(value.values()), None)
