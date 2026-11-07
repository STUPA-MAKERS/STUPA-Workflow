"""DTOs of the UI text overrides and the extra UI languages (camelCase JSON)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints

from app.shared.i18n import LANGUAGE_CODE_PATTERN
from app.shared.schemas import FrozenStrictCamelModel

#: The longest override. The longest built-in text has under 300 characters.
MAX_VALUE_LENGTH = 1000

#: The most keys that one save may change. The catalog has about 4000 keys.
MAX_CHANGES = 5000

#: The code of an extra language. The built-in `de` and `en` match too; the service
#: refuses them.
LanguageCode = Annotated[str, StringConstraints(pattern=LANGUAGE_CODE_PATTERN, max_length=16)]
LanguageName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
TextKey = Annotated[str, StringConstraints(min_length=1, max_length=200)]
TextValue = Annotated[str, StringConstraints(max_length=MAX_VALUE_LENGTH)]


class LanguageOut(FrozenStrictCamelModel, frozen=True):
    """An extra UI language as the admin page shows it."""

    code: str
    name: str
    active: bool
    updated_at: datetime | None = Field(default=None, serialization_alias="updatedAt")


class PublicLanguageOut(FrozenStrictCamelModel, frozen=True):
    """An active extra UI language as the language switch lists it."""

    code: str
    name: str


class LanguageCreate(FrozenStrictCamelModel, frozen=True):
    """A new extra UI language. It starts inactive unless `active` says otherwise."""

    code: LanguageCode
    name: LanguageName
    active: bool = False


class LanguageUpdate(FrozenStrictCamelModel, frozen=True):
    """A change of the name or of the switch `active`. An absent field stays."""

    name: LanguageName | None = None
    active: bool | None = None


class TextsOut(FrozenStrictCamelModel, frozen=True):
    """The overrides of one locale: key to text. A key without an override is absent."""

    locale: str
    overrides: Mapping[str, str]


class TextsUpdate(FrozenStrictCamelModel, frozen=True):
    """The changes of one save: key to the new text, or null for the built-in text.

    An empty or blank text counts as null. A key that the body leaves out stays.
    """

    changes: Mapping[TextKey, TextValue | None] = Field(max_length=MAX_CHANGES)


class BuiltinTextOut(FrozenStrictCamelModel, frozen=True):
    """The built-in texts of one key and, for a requested locale, its own text.

    `en` is null where EN shows the DE text. `own` is the override of the requested
    locale, null without one or without a requested locale.
    """

    key: str
    de: str
    en: str | None
    own: str | None = None


class BuiltinTextsOut(FrozenStrictCamelModel, frozen=True):
    """The built-in texts that match a request, sorted by key."""

    locale: str | None
    texts: tuple[BuiltinTextOut, ...]


class I18nBundleOut(FrozenStrictCamelModel, frozen=True):
    """What the app needs before its first paint.

    `locale` is the resolved UI locale: the requested one when it is built-in or an
    active extra language, else `de`. `languages` lists the active extra languages.
    `overrides` holds the overrides of each locale of the fallback chain of `locale`.
    """

    locale: str
    languages: tuple[PublicLanguageOut, ...]
    overrides: Mapping[str, Mapping[str, str]]
