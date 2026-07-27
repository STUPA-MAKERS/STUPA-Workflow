"""i18n helpers for the `*_i18n` JSONB columns in the database.

A lookup returns the configurable text in the requested language. If that language is
missing, it returns the text in `default_lang`, which is German. If that is also
missing, it returns the first value present.
"""

from __future__ import annotations

from typing import Literal

I18nMap = dict[str, str]

# The supported UI languages. Routes use this type for a query or body field, so the API
# rejects an invalid value such as `lang=null` with a 422 problem+json instead of letting
# it pass.
Lang = Literal["de", "en"]

DEFAULT_LANG: Lang = "de"


def resolve_i18n(
    value: I18nMap | None, lang: str, default_lang: str = "de"
) -> str | None:
    """Resolve the text for `lang`.

    If `lang` is missing, fall back to `default_lang`. If that is also missing, return
    any value present.

    Returns:
        The resolved text, or `None` when the map is empty or absent.
    """
    if not value:
        return None
    if lang in value:
        return value[lang]
    if default_lang in value:
        return value[default_lang]
    return next(iter(value.values()), None)
