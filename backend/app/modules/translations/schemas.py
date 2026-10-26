"""DTOs of the UI text overrides and the extra UI languages (camelCase JSON)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

#: A BCP 47 tag of a language: `fr`, `pt-BR`, `sr-Latn`, `es-419`. The built-in `de`
#: and `en` match too; the service refuses them.
LANGUAGE_CODE_PATTERN = r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-([A-Z]{2}|[0-9]{3}))?$"

#: The longest override. The longest built-in text has under 300 characters.
MAX_VALUE_LENGTH = 1000

#: The most keys that one save may change. The catalog has about 4000 keys.
MAX_CHANGES = 5000

LanguageCode = Annotated[str, StringConstraints(pattern=LANGUAGE_CODE_PATTERN, max_length=16)]
LanguageName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
TextKey = Annotated[str, StringConstraints(min_length=1, max_length=200)]
TextValue = Annotated[str, StringConstraints(max_length=MAX_VALUE_LENGTH)]


class _CamelModel(BaseModel):
    """Base model with camelCase JSON aliases and population by field name."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class LanguageOut(_CamelModel):
    """An extra UI language as the admin page shows it."""

    code: str
    name: str
    active: bool
    updated_at: datetime | None = Field(default=None, serialization_alias="updatedAt")


class PublicLanguageOut(_CamelModel):
    """An active extra UI language as the language switch lists it."""

    code: str
    name: str


class LanguageCreate(_CamelModel):
    """A new extra UI language. It starts inactive unless `active` says otherwise."""

    code: LanguageCode
    name: LanguageName
    active: bool = False


class LanguageUpdate(_CamelModel):
    """A change of the name or of the switch `active`. An absent field stays."""

    name: LanguageName | None = None
    active: bool | None = None


class TextsOut(_CamelModel):
    """The overrides of one locale: key to text. A key without an override is absent."""

    locale: str
    overrides: dict[str, str]


class TextsUpdate(_CamelModel):
    """The changes of one save: key to the new text, or null for the built-in text.

    An empty or blank text counts as null. A key that the body leaves out stays.
    """

    changes: dict[TextKey, TextValue | None] = Field(max_length=MAX_CHANGES)


class BuiltinTextOut(_CamelModel):
    """The built-in texts of one key and, for a requested locale, its own text.

    `en` is null where EN shows the DE text. `own` is the override of the requested
    locale, null without one or without a requested locale.
    """

    key: str
    de: str
    en: str | None
    own: str | None = None


class BuiltinTextsOut(_CamelModel):
    """The built-in texts that match a request, sorted by key."""

    locale: str | None
    texts: list[BuiltinTextOut]


class I18nBundleOut(_CamelModel):
    """What the app needs before its first paint.

    `locale` is the resolved UI locale: the requested one when it is built-in or an
    active extra language, else `de`. `languages` lists the active extra languages.
    `overrides` holds the overrides of each locale of the fallback chain of `locale`.
    """

    locale: str
    languages: list[PublicLanguageOut]
    overrides: dict[str, dict[str, str]]
