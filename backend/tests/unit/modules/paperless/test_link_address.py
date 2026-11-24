"""Unit tests of the address that a browser link to Paperless names.

§F/integrations/paperless/002844 a link names the address for links, or the address when
the field is empty. The address for links is an absolute `http` or `https` address.
"""

from __future__ import annotations

import pytest

from app.modules.paperless.client import document_url, link_address, link_address_valid

_API = "http://paperless.int.example:8100"
_PUBLIC = "https://paperless.example.org"


def test_a_link_names_the_address_for_links() -> None:
    address = link_address(_API, _PUBLIC)
    assert address == _PUBLIC
    assert document_url(_PUBLIC, 3178) == f"{_PUBLIC}/documents/3178/details"


def test_a_link_without_an_address_for_links_names_the_server_address() -> None:
    assert link_address(_API, None) == _API
    assert link_address(_API, "") == _API
    assert link_address(None, None) is None


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        (_PUBLIC, True),
        ("http://paperless.example.org:8000/dms", True),
        ("HTTPS://paperless.example.org", True),
        ("ftp://paperless.example.org", False),
        ("javascript:alert(1)", False),
        ("paperless.example.org", False),
        ("https://", False),
    ],
)
def test_the_address_for_links_is_http_or_https(url: str, valid: bool) -> None:
    assert link_address_valid(url) is valid
