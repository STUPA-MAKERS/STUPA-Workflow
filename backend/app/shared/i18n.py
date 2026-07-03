"""i18n helpers for DB ``*_i18n`` JSONB.

Configurable text: requested language, else fallback ``default_lang`` (DE), else the
first present value.
"""

from __future__ import annotations

from typing import Literal

I18nMap = dict[str, str]

# Supported UI languages. Used as a query/body field type so invalid values
# (e.g. ``lang=null``) are rejected as 422 problem+json instead of silently passing.
Lang = Literal["de", "en"]

DEFAULT_LANG: Lang = "de"


def resolve_i18n(
    value: I18nMap | None, lang: str, default_lang: str = "de"
) -> str | None:
    """Resolve text in ``lang``; fall back to ``default_lang``, then any present value."""
    if not value:
        return None
    if lang in value:
        return value[lang]
    if default_lang in value:
        return value[default_lang]
    return next(iter(value.values()), None)
