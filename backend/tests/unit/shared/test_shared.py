"""Helpers in shared/paging and shared/i18n."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.shared.i18n import Lang, fallback_chain, pick_lang, resolve_i18n
from app.shared.paging import Page, PageParams


def test_resolve_i18n_returns_requested_lang() -> None:
    assert resolve_i18n({"de": "Hallo", "en": "Hi"}, "en") == "Hi"


def test_resolve_i18n_falls_back_to_default() -> None:
    assert resolve_i18n({"de": "Hallo"}, "en") == "Hallo"
    assert resolve_i18n({"de": "Hallo"}, "en", default_lang="de") == "Hallo"


def test_resolve_i18n_none() -> None:
    assert resolve_i18n(None, "de") is None
    assert resolve_i18n({}, "de") is None


def test_fallback_chain() -> None:
    assert fallback_chain("de") == ["de"]
    assert fallback_chain("en") == ["en", "de"]
    assert fallback_chain("fr") == ["fr", "en", "de"]


def test_resolve_i18n_extra_lang_falls_back_to_en_then_de() -> None:
    assert resolve_i18n({"de": "Hallo", "en": "Hi", "fr": "Salut"}, "fr") == "Salut"
    assert resolve_i18n({"de": "Hallo", "en": "Hi"}, "fr") == "Hi"
    assert resolve_i18n({"de": "Hallo"}, "fr") == "Hallo"
    assert resolve_i18n({"it": "Ciao"}, "fr") == "Ciao"


def test_resolve_i18n_de_never_shows_en_before_de() -> None:
    assert resolve_i18n({"en": "Hi", "de": "Hallo"}, "de") == "Hallo"


def test_pick_lang_gives_en_to_an_extra_lang() -> None:
    table = {"de": "Neu", "en": "New"}
    assert pick_lang(table, "de") == "Neu"
    assert pick_lang(table, "en") == "New"
    assert pick_lang(table, "pt-BR") == "New"
    assert pick_lang({"de": "Neu"}, "fr") == "Neu"


@pytest.mark.parametrize("code", ["de", "en", "fr", "pt-BR", "sr-Latn", "es-419"])
def test_lang_accepts_bcp47_codes(code: str) -> None:
    assert TypeAdapter(Lang).validate_python(code) == code


@pytest.mark.parametrize("code", ["", "x", "null ", "DE", "de_DE", "a" * 17])
def test_lang_rejects_invalid_codes(code: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Lang).validate_python(code)


def test_page_params_defaults_and_bounds() -> None:
    p = PageParams()
    assert p.limit == 50
    assert p.offset == 0
    assert PageParams(limit=200, offset=10).limit == 200


def test_page_envelope() -> None:
    page = Page[int](items=[1, 2, 3], total=3, limit=50, offset=0)
    assert page.items == [1, 2, 3]
    assert page.total == 3
