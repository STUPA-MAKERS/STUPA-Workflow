"""i18n helpers for the `*_i18n` JSONB columns in the database.

A text exists in German (the reference), in English and in any extra language that an
admin adds on the translations page. A lookup follows the fallback chain of the requested
language: an extra language falls back to English and then to German, English falls back
to German. If no language of the chain has a text, the lookup returns the first value
present.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from pydantic import StringConstraints

I18nMap = dict[str, str]

#: A BCP 47 tag of a language: `de`, `en`, `fr`, `pt-BR`, `sr-Latn`, `es-419`.
LANGUAGE_CODE_PATTERN = r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-([A-Z]{2}|[0-9]{3}))?$"

#: A language of the content: `de`, `en` or the code of an extra language. A route uses
#: this type for a query or body field, so the API rejects an invalid value such as
#: ``lang=null`` with a 422 instead of letting it pass. A valid code without texts is no
#: error: the lookup falls back along the chain.
Lang = Annotated[str, StringConstraints(pattern=LANGUAGE_CODE_PATTERN, max_length=16)]

DEFAULT_LANG = "de"

#: The language that every extra language falls back to before German.
FALLBACK_LANG = "en"


def fallback_chain(lang: str) -> list[str]:
    """Return the languages whose texts `lang` shows, the first one first.

    German is the reference and has no fallback. English falls back to German. An extra
    language falls back to English and then to German.
    """
    if lang == DEFAULT_LANG:
        return [DEFAULT_LANG]
    if lang == FALLBACK_LANG:
        return [FALLBACK_LANG, DEFAULT_LANG]
    return [lang, FALLBACK_LANG, DEFAULT_LANG]


def resolve_i18n(
    value: Mapping[str, str] | None, lang: str, default_lang: str = DEFAULT_LANG
) -> str | None:
    """Resolve the text for `lang` along its fallback chain.

    If no language of the chain has a text, fall back to `default_lang`, then to any
    value present.

    Returns:
        The resolved text, or `None` when the map is empty or absent.
    """
    if not value:
        return None
    for code in (*fallback_chain(lang), default_lang):
        if code in value:
            return value[code]
    return next(iter(value.values()), None)


def pick_lang[T](table: Mapping[str, T], lang: str) -> T:
    """Return the entry of a built-in `{lang: value}` table for `lang`.

    The tables of the server (mail footers, link labels, fallback names) exist in German
    and English, so an extra language gets the English entry. A table without the entry
    of the chain gives the German one, which every table has.
    """
    for code in fallback_chain(lang):
        if code in table:
            return table[code]
    return table[DEFAULT_LANG]
