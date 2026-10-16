"""``TicketContext.url`` keeps a page of the platform only."""

from __future__ import annotations

import pytest

from app.modules.tickets.schemas import TicketContext, platform_page_url
from app.settings import get_settings


@pytest.fixture
def base(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(get_settings(), "public_base_url", "https://stupa.example.org")
    return "https://stupa.example.org"


@pytest.mark.parametrize(
    "url",
    [
        "https://stupa.example.org/status/A-1",
        "https://STUPA.example.org/x",
        "/applications/1",
        None,
    ],
)
def test_a_platform_page_is_kept(base: str, url: str | None) -> None:
    assert TicketContext.model_validate({"url": url}).url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://stupa-login.evil.example/auth",
        "http://stupa.example.org/x",
        "https://stupa.example.org:8443/x",
        "https://stupa.example.org.evil.example/x",
        "//evil.example/x",
        "/\\evil.example",
        "/\t/evil.example/x",
        "/\n/evil.example",
        "/\r/evil.example",
        "\t//evil.example/x",
        "/ /evil.example",
        "/\x7f/evil.example",
        "https://stupa.example.org/\t/x",
        "javascript:alert(1)",
        "data:text/html,x",
        "ftp://stupa.example.org/x",
        "stupa.example.org/x",
        "https://[::1/x",
        "",
    ],
)
def test_any_other_url_is_dropped(base: str, url: str) -> None:
    assert TicketContext.model_validate({"url": url}).url is None
    assert platform_page_url(url) is None
