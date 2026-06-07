"""i18n-Helfer für DB-`*_i18n`-JSONB (overview §5).

Konfigurierbare Texte: angeforderte Sprache, sonst Fallback `default_lang` (DE),
sonst erster vorhandener Wert.
"""

from __future__ import annotations

from typing import Literal

I18nMap = dict[str, str]

# Unterstützte UI-Sprachen (T-25). Als Query-/Body-Feldtyp verwendet, damit
# ungültige Werte (z.B. ``lang=null``) sauber als 422 problem+json abgelehnt
# werden statt still durchzulaufen — schließt den be-contract-Coverage-Flake
# (schemathesis injiziert ungültige Enum-Werte, erwartet 4xx; vgl. PR #63).
Lang = Literal["de", "en"]

DEFAULT_LANG: Lang = "de"


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
