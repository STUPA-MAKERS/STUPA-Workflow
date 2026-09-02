"""Router tests for share links: the gates, not the rendering.

`test_application_share` covers the service and the page. What is left, and what only a
router test can answer, is who reaches which route. A share link is the one route on this
platform that answers without a principal, so the two questions here are:

* who may CREATE one — a permission of its own, never the read permission, and never an
  applicant holding a magic link;
* what the PUBLIC route answers for a token that is unknown, expired, revoked or simply
  not token-shaped — always the same 404, never a hint that the link was ever real.

No database. `get_session` is overridden with a fake that serves the few reads these
routes make.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal, get_session
from app.main import create_app
from app.modules.applications.models import Application, ApplicationShare
from app.modules.auth import tokens
from app.modules.auth.principal import Applicant, Principal
from app.modules.forms.models import FormField
from app.settings import load_settings

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
PEPPER = load_settings().magic_link_secret


class _Rows:
    """What `session.scalars` gives back: iterable, and `.all()`-able."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def __iter__(self):  # noqa: ANN204
        return iter(self._rows)

    def all(self) -> list[object]:
        return self._rows

    def first(self) -> object | None:
        # The site-config lookup for the branding name reads one row this way.
        return self._rows[0] if self._rows else None


class _Result:
    """What `session.execute` gives the audit chain: a previous hash, or none."""

    def scalar_one_or_none(self) -> None:
        return None


class _FakeSession:
    """Serves the handful of reads the share routes make, and records the writes."""

    def __init__(
        self,
        *,
        share: ApplicationShare | None = None,
        objects: dict[type, object] | None = None,
        fields: list[object] | None = None,
    ) -> None:
        self.share = share
        self.objects = objects or {}
        # `create` looks the application up before it mints anything. Pass
        # `objects={Application: None}` to test the route for an id that is not there.
        self.objects.setdefault(Application, _App())
        self.fields = fields or []
        self.added: list[Any] = []
        self.committed = False

    async def execute(self, _stmt: object) -> _Result:
        return _Result()

    async def scalar(self, _stmt: object) -> object:
        return self.share

    async def scalars(self, stmt: Any) -> _Rows:
        """Answer by what is being selected.

        Three callers read through this: the listing reads shares, the public page reads
        form fields, and the branding name reads the site config. Answering the same rows
        to all three fed form fields to whichever asked first.
        """
        entity = stmt.column_descriptions[0]["entity"]
        if entity is FormField:
            return _Rows(self.fields)
        if entity is ApplicationShare:
            return _Rows([r for r in (self.share,) if r])
        # No active site config: the page falls back to the default name.
        return _Rows([])

    async def get(self, model: type, _pk: object) -> object | None:
        return self.objects.get(model)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        # Stand in for the server defaults: `id` is `gen_random_uuid()` and `created_at`
        # is `now()`, so a real INSERT is what fills them in.
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "created_at", None) is None:
                obj.created_at = NOW

    async def commit(self) -> None:
        self.committed = True


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def app(session: _FakeSession) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_session] = lambda: session
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _stored_share(application_id: uuid.UUID) -> ApplicationShare:
    """A share row as the database hands it back: id and timestamp already assigned."""
    row = ApplicationShare(
        application_id=application_id,
        token_hash=tokens.hash_token("t", PEPPER),
        expires_at=NOW + timedelta(days=1),
    )
    row.id = uuid.uuid4()
    row.created_at = NOW
    return row


def _as_principal(app: FastAPI, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="office", roles=["office"], permissions=set(perms)
    )
    app.dependency_overrides[get_current_applicant] = lambda: None


def _as_applicant(app: FastAPI, application_id: uuid.UUID) -> None:
    app.dependency_overrides[get_current_principal] = lambda: None
    app.dependency_overrides[get_current_applicant] = lambda: Applicant(
        application_id=str(application_id), scope="edit"
    )


# -- creating -----------------------------------------------------------------


def test_reading_an_application_does_not_let_you_publish_it(
    app: FastAPI, client: TestClient
) -> None:
    """The whole reason `application.share` is its own key.

    Everyone in a committee can read; deciding a record may be read by anyone holding a
    URL is a different decision, and it is not implied by managing the application either.
    """
    _as_principal(app, "application.read", "application.manage")
    r = client.post(f"/api/applications/{uuid.uuid4()}/shares", json={})
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


def test_an_applicant_cannot_publish_their_own_application(
    app: FastAPI, client: TestClient
) -> None:
    """A magic-link holder authenticates for one application and may edit it.

    Publishing it is a decision about the committee's record. If this route accepted an
    applicant token, anyone who was ever mailed a link could put the application on the
    open internet.
    """
    app_id = uuid.uuid4()
    _as_applicant(app, app_id)
    assert client.post(f"/api/applications/{app_id}/shares", json={}).status_code == 401


def test_nobody_at_all_cannot_publish(client: TestClient) -> None:
    assert client.post(f"/api/applications/{uuid.uuid4()}/shares", json={}).status_code == 401


def test_creating_returns_the_token_once_in_a_full_url(
    app: FastAPI, client: TestClient, session: _FakeSession
) -> None:
    """The plaintext lives in this response and nowhere else — not even in the row."""
    _as_principal(app, "application.share")
    r = client.post(f"/api/applications/{uuid.uuid4()}/shares", json={"label": "Fachschaft"})
    assert r.status_code == 201
    body = r.json()

    assert body["url"].startswith("http")
    token = body["url"].rsplit("/s/", 1)[1]
    assert len(token) >= 32
    assert body["label"] == "Fachschaft"
    assert body["revokedAt"] is None

    row = next(o for o in session.added if isinstance(o, ApplicationShare))
    assert row.token_hash == tokens.hash_token(token, PEPPER)
    # The plaintext is nowhere on the stored row.
    assert token.encode() not in bytes(row.token_hash)
    assert session.committed


def test_creating_is_audited_without_the_token(
    app: FastAPI, client: TestClient, session: _FakeSession
) -> None:
    """Publishing a record is a moment someone will ask about later.

    The entry must not carry the token: the audit log is built to be read, and a copy of
    the secret in it would be a second way in.
    """
    _as_principal(app, "application.share")
    r = client.post(f"/api/applications/{uuid.uuid4()}/shares", json={})
    token = r.json()["url"].rsplit("/s/", 1)[1]

    entry = next(o for o in session.added if getattr(o, "action", None) == "application_share")
    assert token not in repr(entry.data)


def test_minting_a_link_to_an_application_that_is_not_there_is_a_404(
    app: FastAPI, client: TestClient
) -> None:
    """A typo in the id must not surface as a foreign-key 500."""
    app.dependency_overrides[get_session] = lambda: _FakeSession(objects={Application: None})
    _as_principal(app, "application.share")
    r = client.post(f"/api/applications/{uuid.uuid4()}/shares", json={})
    assert r.status_code == 404


def test_a_lifetime_beyond_the_bound_is_refused_rather_than_clamped(
    app: FastAPI, client: TestClient
) -> None:
    """A caller asking for ten years has misunderstood; answering 201 would hide that."""
    _as_principal(app, "application.share")
    r = client.post(f"/api/applications/{uuid.uuid4()}/shares", json={"ttlDays": 4000})
    assert r.status_code == 422


# -- listing and revoking -----------------------------------------------------


def test_listing_never_hands_back_a_token(app: FastAPI, client: TestClient) -> None:
    """The server holds a hash. Even if it could reconstruct one, it would not."""
    app_id = uuid.uuid4()
    row = _stored_share(app_id)
    app.dependency_overrides[get_session] = lambda: _FakeSession(share=row)
    _as_principal(app, "application.share")

    r = client.get(f"/api/applications/{app_id}/shares")
    assert r.status_code == 200
    assert r.json()[0]["url"] is None


def test_listing_needs_the_share_permission(app: FastAPI, client: TestClient) -> None:
    # Who published this, and is the link still live, is part of the same decision.
    _as_principal(app, "application.read")
    assert client.get(f"/api/applications/{uuid.uuid4()}/shares").status_code == 403


def test_revoking_needs_the_share_permission(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.read")
    r = client.delete(f"/api/applications/{uuid.uuid4()}/shares/{uuid.uuid4()}")
    assert r.status_code == 403


def test_revoking_a_link_that_is_not_there_is_a_404(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.share")
    r = client.delete(f"/api/applications/{uuid.uuid4()}/shares/{uuid.uuid4()}")
    assert r.status_code == 404


def test_revoking_stamps_the_row_and_audits(app: FastAPI, client: TestClient) -> None:
    app_id = uuid.uuid4()
    row = _stored_share(app_id)
    fake = _FakeSession(share=row)
    app.dependency_overrides[get_session] = lambda: fake
    _as_principal(app, "application.share")

    r = client.delete(f"/api/applications/{app_id}/shares/{row.id}")
    assert r.status_code == 200
    assert r.json()["revokedAt"] is not None
    assert any(getattr(o, "action", None) == "application_share_revoke" for o in fake.added)
    assert fake.committed


# -- the public page ----------------------------------------------------------


class _App:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.type_id = uuid.uuid4()
        self.gremium_id = None
        self.form_version_id = uuid.uuid4()
        self.data = {"title": "Anschaffung Beamer", "zweck": "Musik"}
        self.amount = None
        self.currency = None
        self.lang = "de"
        self.created_at = NOW


class _FieldRow:
    def __init__(self, key: str, *, pii: bool = False) -> None:
        self.key = key
        self.type = "text"
        self.label_i18n = {"de": key.title()}
        self.help_i18n = None
        self.required = False
        self.validation = None
        self.visible_if = None
        self.compute = None
        self.options = None
        self.is_pii = pii
        self.is_promoted = False
        self.promote_target = None


def _live_share() -> ApplicationShare:
    row = _stored_share(uuid.uuid4())
    row.expires_at = datetime.now(UTC) + timedelta(days=1)
    return row


def _public_client(
    share: ApplicationShare | None, *, missing_application: bool = False
) -> TestClient:
    application = create_app()
    fake = _FakeSession(
        share=share,
        objects={Application: None if missing_application else _App()},
        fields=[_FieldRow("zweck"), _FieldRow("iban", pii=True)],
    )
    application.dependency_overrides[get_session] = lambda: fake
    return TestClient(application)


def test_the_public_page_needs_no_login() -> None:
    """The point of the feature. Anyone holding the URL, and nobody else, gets the page."""
    r = _public_client(_live_share()).get("/s/" + "x" * 32)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Anschaffung Beamer" in r.text


def test_the_preview_carries_the_branding_name_not_the_api_title() -> None:
    """`settings.app_name` is the FastAPI title and reads "Antragsplattform API". The
    og:title lands permanently on a chat server, so it takes the configured name."""
    r = _public_client(_live_share()).get("/s/" + "x" * 32)
    assert "Antragsplattform API" not in r.text
    assert "STUPA Antragsplattform" in r.text


def test_the_public_page_drops_pii_fields() -> None:
    r = _public_client(_live_share()).get("/s/" + "x" * 32)
    assert "Zweck" in r.text
    assert "Iban" not in r.text


def test_the_public_page_carries_its_own_policy() -> None:
    """Without one the API-wide `default-src 'none'` applies and the page arrives as raw
    unstyled markup."""
    r = _public_client(_live_share()).get("/s/" + "x" * 32)
    csp = r.headers["content-security-policy"]
    assert csp.startswith("default-src 'none'")
    assert "style-src 'sha256-" in csp


def test_the_public_page_refuses_to_be_indexed_or_cached_by_a_proxy() -> None:
    """A shared cache holding this page would serve it to someone who never had the link."""
    r = _public_client(_live_share()).get("/s/" + "x" * 32)
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert "no-store" in r.headers["cache-control"]
    assert r.headers["referrer-policy"] == "no-referrer"


def test_an_unknown_token_is_a_404() -> None:
    assert _public_client(None).get("/s/" + "x" * 32).status_code == 404


@pytest.mark.parametrize(
    "over",
    [
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        {"revoked_at": NOW},
    ],
    ids=["expired", "revoked"],
)
def test_a_dead_link_answers_exactly_like_an_unknown_one(over: dict[str, object]) -> None:
    """Never 410. "This link expired" tells a stranger they found a real one."""
    row = _live_share()
    for k, v in over.items():
        setattr(row, k, v)
    assert _public_client(row).get("/s/" + "x" * 32).status_code == 404


@pytest.mark.parametrize("token", ["short", "has spaces", "a/../b", "x" * 200])
def test_a_token_that_is_not_token_shaped_never_reaches_the_database(token: str) -> None:
    """A rejected shape costs no round trip, so a scanner cannot use this as a query
    generator."""
    r = _public_client(None).get(f"/s/{token}")
    assert r.status_code in (404, 422)


def test_a_link_whose_application_is_already_gone_is_a_404() -> None:
    """The row cascades with the application, so this is a race rather than a state —
    and it answers exactly like an unknown token, giving away nothing about what was
    there a moment ago."""
    r = _public_client(_live_share(), missing_application=True).get("/s/" + "x" * 32)
    assert r.status_code == 404
