"""Unit tests for public share links.

The point of these is the security surface, not the happy path. A share link is the one
route on the platform that answers without a principal, so what it refuses matters more
than what it renders.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.applications.models import ApplicationShare
from app.modules.applications.share import (
    DEFAULT_TTL_DAYS,
    MAX_TTL_DAYS,
    PublicApplication,
    ShareService,
    build_public_view,
    clamp_ttl,
    new_token,
)
from app.modules.applications.share_page import render_share_page
from app.modules.auth import tokens
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError

PEPPER = "pepper-for-tests-only"
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


class _Session:
    """Minimal stand-in: one row to find, and a record of what was added."""

    def __init__(
        self, row: ApplicationShare | None = None, *, application: object | None = object()
    ) -> None:
        self.row = row
        self.application = application
        self.added: list[object] = []

    async def get(self, _model: type, _pk: object) -> object | None:
        return self.application

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def scalar(self, *_a: object, **_k: object) -> object:
        return self.row

    async def scalars(self, *_a: object, **_k: object) -> list[object]:
        return [self.row] if self.row is not None else []


def _svc(row: ApplicationShare | None = None) -> ShareService:
    return ShareService(_Session(row), pepper=PEPPER)  # type: ignore[arg-type]


def _svc_without_application() -> ShareService:
    return ShareService(_Session(application=None), pepper=PEPPER)  # type: ignore[arg-type]


def _share(**over: object) -> ApplicationShare:
    row = ApplicationShare(
        application_id=uuid.uuid4(),
        token_hash=tokens.hash_token("t", PEPPER),
        expires_at=NOW + timedelta(days=1),
    )
    for k, v in over.items():
        setattr(row, k, v)
    return row


# -- tokens -------------------------------------------------------------------


def test_a_token_is_long_and_url_safe() -> None:
    """The URL is the only secret, so it carries session-token weight."""
    token = new_token()
    assert len(token) >= 32
    assert all(c.isalnum() or c in "-_" for c in token)


def test_two_tokens_are_never_the_same() -> None:
    assert len({new_token() for _ in range(50)}) == 50


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        (None, DEFAULT_TTL_DAYS),
        (7, 7),
        (0, 1),
        (-5, 1),
        (10_000, MAX_TTL_DAYS),
    ],
)
def test_the_lifetime_is_bounded(asked: int | None, expected: int) -> None:
    """"Never expires" is not on offer: a forgotten link has to stop working by itself."""
    assert clamp_ttl(asked) == expected


# -- creating -----------------------------------------------------------------


async def test_create_stores_only_the_hash() -> None:
    """A stolen database must yield no working links."""
    svc = _svc()
    app_id = uuid.uuid4()
    row, token = await svc.create(app_id, actor="me", now=NOW)

    assert row.token_hash == tokens.hash_token(token, PEPPER)
    # The plaintext is nowhere on the row.
    assert token.encode() not in bytes(row.token_hash)
    assert row.created_by == "me"
    assert row.expires_at == NOW + timedelta(days=DEFAULT_TTL_DAYS)


async def test_creating_a_link_to_nothing_is_not_found() -> None:
    """A typo in the id must read as "no such application", not as a broken server.

    Without the check the INSERT trips the foreign key and the caller gets a 500 on a
    route that advertises 404.
    """
    with pytest.raises(NotFoundError):
        await _svc_without_application().create(uuid.uuid4(), actor="me", now=NOW)


async def test_create_honours_a_requested_lifetime_within_the_bound() -> None:
    row, _ = await _svc().create(uuid.uuid4(), actor="me", ttl_days=3, now=NOW)
    assert row.expires_at == NOW + timedelta(days=3)


# -- resolving ----------------------------------------------------------------


async def test_resolve_finds_a_live_link() -> None:
    row = _share()
    assert await _svc(row).resolve("t", now=NOW) is row


async def test_an_unknown_token_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _svc(None).resolve("nope", now=NOW)


async def test_an_expired_link_answers_the_same_as_an_unknown_one() -> None:
    """Never "this link expired": that tells a stranger they found a real one."""
    row = _share(expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(NotFoundError):
        await _svc(row).resolve("t", now=NOW)


async def test_a_revoked_link_answers_the_same_as_an_unknown_one() -> None:
    row = _share(revoked_at=NOW - timedelta(days=1))
    with pytest.raises(NotFoundError):
        await _svc(row).resolve("t", now=NOW)


async def test_the_expiry_boundary_is_exclusive() -> None:
    # At exactly the expiry the link is gone. Erring towards closed is the right side.
    row = _share(expires_at=NOW)
    with pytest.raises(NotFoundError):
        await _svc(row).resolve("t", now=NOW)


async def test_a_wrong_token_does_not_resolve_a_row_that_exists() -> None:
    """The lookup is by hash, so a near-miss finds nothing rather than the wrong row."""
    row = _share()
    svc = ShareService(_Session(None), pepper=PEPPER)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.resolve("wrong", now=NOW)
    assert row.revoked_at is None


# -- revoking -----------------------------------------------------------------


async def test_revoke_stamps_the_time() -> None:
    row = _share()
    out = await _svc(row).revoke(row.id, application_id=row.application_id, now=NOW)
    assert out.revoked_at == NOW


async def test_revoking_twice_keeps_the_first_timestamp() -> None:
    first = NOW - timedelta(days=1)
    row = _share(revoked_at=first)
    out = await _svc(row).revoke(row.id, application_id=row.application_id, now=NOW)
    assert out.revoked_at == first


async def test_revoking_an_unknown_share_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _svc(None).revoke(uuid.uuid4(), application_id=uuid.uuid4(), now=NOW)


# -- the public view ----------------------------------------------------------


class _App:
    def __init__(self, data: dict[str, object]) -> None:
        self.id = uuid.uuid4()
        self.data = data
        self.amount = None
        self.currency = None
        self.created_at = NOW


def _field(key: str, *, pii: bool = False) -> FormFieldDef:
    return FormFieldDef.model_validate(
        {"key": key, "type": "text", "label": {"de": key.title()}, "isPII": pii}
    )


def test_the_public_view_drops_every_pii_field() -> None:
    """The same rule the gremium PDF applies, read from the same definitions."""
    view = build_public_view(
        _App({"title": "Fest", "zweck": "Musik", "iban": "DE00"}),  # type: ignore[arg-type]
        fields=[_field("zweck"), _field("iban", pii=True)],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    labels = [label for label, _ in view.fields]
    assert "Zweck" in labels
    assert "Iban" not in labels
    assert all("DE00" not in value for _, value in view.fields)


def test_the_public_view_skips_empty_answers() -> None:
    view = build_public_view(
        _App({"title": "Fest", "a": "", "b": None, "c": [], "d": "x"}),  # type: ignore[arg-type]
        fields=[_field(k) for k in ("a", "b", "c", "d")],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert [label for label, _ in view.fields] == ["D"]


def test_an_application_without_a_title_still_has_a_heading() -> None:
    # A blank <h1> would make the preview a bare URL.
    view = build_public_view(
        _App({}),  # type: ignore[arg-type]
        fields=[],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.title


# -- the rendered page --------------------------------------------------------


def _view(**over: object) -> PublicApplication:
    base: dict[str, object] = {
        "title": "Anschaffung Beamer",
        "type_name": "Anschaffung",
        "gremium_name": "StuPa",
        "state_label": None,
        "amount": "4200.00",
        "currency": "EUR",
        "created_at": NOW,
        "fields": [("Zweck", "Musik")],
    }
    base.update(over)
    return PublicApplication(**base)  # type: ignore[arg-type]


def test_the_preview_carries_the_title_and_nothing_about_the_application() -> None:
    """The og: text lands permanently on a chat server we do not control."""
    html = render_share_page(_view(), app_name="STUPA", canonical_url="https://x/s/t")
    head = html.split("</head>")[0]

    assert 'property="og:title" content="Anschaffung Beamer — STUPA"' in head
    # The amount is on the page but must not be in the preview.
    assert "4200" not in head
    assert "Musik" not in head


def test_the_page_asks_not_to_be_indexed() -> None:
    # For whoever holds the URL, not for everyone who searches the applicant's name.
    html = render_share_page(_view(), app_name="STUPA", canonical_url="https://x/s/t")
    assert 'name="robots" content="noindex, nofollow"' in html


def test_every_value_is_escaped() -> None:
    """The page is hand-written HTML, so escaping is the one thing that must not slip."""
    html = render_share_page(
        _view(
            title='<script>alert(1)</script>',
            gremium_name='" onload="x',
            fields=[("<b>k</b>", "<img src=x onerror=y>")],
        ),
        app_name="STUPA",
        canonical_url="https://x/s/t",
    )
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html
    assert 'onload="x' not in html
    assert "&lt;script&gt;" in html


def test_a_missing_optional_leaves_its_row_out_rather_than_printing_none() -> None:
    html = render_share_page(
        _view(gremium_name=None, type_name=None, amount=None, currency=None),
        app_name="STUPA",
        canonical_url="https://x/s/t",
    )
    assert "None" not in html


# -- flattening one answer ----------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "shown"),
    [
        (True, "Ja"),
        (False, "Nein"),
        (["a", "b"], "a, b"),
        ([True, False], "Ja, Nein"),
        (42, "42"),
    ],
)
def test_an_answer_is_flattened_to_one_readable_line(answer: object, shown: str) -> None:
    view = build_public_view(
        _App({"title": "T", "k": answer}),  # type: ignore[arg-type]
        fields=[_field("k")],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.fields == [("K", shown)]


def test_a_structured_answer_prints_nothing_rather_than_a_guess() -> None:
    """A dict has no sensible one-line form, and guessing one risks printing a key
    nobody meant to publish."""
    view = build_public_view(
        _App({"title": "T", "k": {"iban": "DE00"}}),  # type: ignore[arg-type]
        fields=[_field("k")],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.fields == [("K", "")]

