"""TDD: shared/paging + shared/i18n Helfer."""

from app.shared.i18n import resolve_i18n
from app.shared.paging import Page, PageParams


def test_resolve_i18n_returns_requested_lang() -> None:
    assert resolve_i18n({"de": "Hallo", "en": "Hi"}, "en") == "Hi"


def test_resolve_i18n_falls_back_to_default() -> None:
    assert resolve_i18n({"de": "Hallo"}, "en") == "Hallo"
    assert resolve_i18n({"de": "Hallo"}, "en", default_lang="de") == "Hallo"


def test_resolve_i18n_none() -> None:
    assert resolve_i18n(None, "de") is None
    assert resolve_i18n({}, "de") is None


def test_page_params_defaults_and_bounds() -> None:
    p = PageParams()
    assert p.limit == 50
    assert p.offset == 0
    assert PageParams(limit=200, offset=10).limit == 200


def test_page_envelope() -> None:
    page = Page[int](items=[1, 2, 3], total=3, limit=50, offset=0)
    assert page.items == [1, 2, 3]
    assert page.total == 3
