"""Capture on behalf of an applicant (#11): router, service and mail without a database.

The integration suite (`tests/integration/.../test_on_behalf.py`) covers the real
database paths. These tests pin the wiring: the permission gate, the body cap, the
schema rules, the hand-off to the normal create, and the link of the mail.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.applications import router as router_mod
from app.modules.applications.router import (
    get_applications_service,
    get_capture_mail_sender,
)
from app.modules.applications.schemas import (
    ApplicantCandidateOut,
    ApplicationOut,
    OnBehalfCreate,
)
from app.modules.applications.service import ApplicationsService
from app.modules.applications.service.create import Capture
from app.modules.auth.principal import Principal
from app.modules.notifications import captured as captured_mod
from app.modules.notifications.mail import MailMessage
from app.modules.notifications.templates_catalogue import CATALOGUE_BY_KEY
from app.shared.errors import ValidationProblem

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
_PERM = "application.create_on_behalf"


class _FakeApp:
    def __init__(self) -> None:
        self.id = uuid4()


class _FakeService:
    def __init__(self) -> None:
        self.payload: OnBehalfCreate | None = None
        self.kwargs: dict[str, Any] = {}
        self.query: str | None = None

    async def create_on_behalf(self, payload: OnBehalfCreate, **kwargs: Any) -> tuple[Any, str]:
        self.payload = payload
        self.kwargs = kwargs
        return _FakeApp(), "applicant@example.org"

    async def search_applicants(self, query: str) -> list[ApplicantCandidateOut]:
        self.query = query
        return [ApplicantCandidateOut(id=uuid4(), displayName="Anna", email="anna@example.org")]


@pytest.fixture
def service() -> _FakeService:
    return _FakeService()


@pytest.fixture
def mails() -> list[tuple[str, UUID, bool]]:
    return []


@pytest.fixture
def api(service: _FakeService, mails: list[tuple[str, UUID, bool]]) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_applications_service] = lambda: service

    async def _sender(_settings: Any, email: str, app_id: UUID, guest: bool, _pool: Any) -> None:
        mails.append((email, app_id, guest))

    application.dependency_overrides[get_capture_mail_sender] = lambda: _sender
    application.dependency_overrides[get_current_applicant] = lambda: None
    return application


def _as(api: FastAPI, *perms: str) -> None:
    api.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="clerk", permissions=set(perms)
    )


def _guest(**extra: Any) -> dict[str, Any]:
    return {
        "typeId": str(uuid4()),
        "data": {"title": "Papier"},
        "applicantName": "Gisela",
        "applicantEmail": "gisela@example.org",
        **extra,
    }


def test_route_creates_and_mails_a_guest(
    api: FastAPI, service: _FakeService, mails: list[tuple[str, UUID, bool]]
) -> None:
    _as(api, _PERM)
    resp = TestClient(api).post("/api/applications/on-behalf", json=_guest(intake="per PDF"))
    assert resp.status_code == 201, resp.text
    app_id = UUID(resp.json()["applicationId"])
    assert service.payload is not None
    assert service.payload.intake == "per PDF"
    assert service.kwargs["actor"] == "clerk"
    assert isinstance(service.kwargs["today"], date)
    assert service.kwargs["dispatcher"] is not None
    assert mails == [("applicant@example.org", app_id, True)]


def test_route_mails_an_account_with_the_normal_link(
    api: FastAPI, mails: list[tuple[str, UUID, bool]]
) -> None:
    _as(api, _PERM)
    body = {"typeId": str(uuid4()), "data": {}, "applicantPrincipalId": str(uuid4())}
    resp = TestClient(api).post("/api/applications/on-behalf", json=body)
    assert resp.status_code == 201, resp.text
    assert mails[0][2] is False


def test_route_needs_the_permission(api: FastAPI, service: _FakeService) -> None:
    _as(api, "application.manage")
    client = TestClient(api)
    resp = client.post("/api/applications/on-behalf", json=_guest())
    assert resp.status_code == 403
    assert resp.headers["content-type"] == "application/problem+json"
    assert client.get("/api/applications/on-behalf/applicants?q=an").status_code == 403
    api.dependency_overrides[get_current_principal] = lambda: None
    assert client.post("/api/applications/on-behalf", json=_guest()).status_code == 401
    assert service.payload is None


def test_route_caps_the_data(api: FastAPI, service: _FakeService) -> None:
    _as(api, _PERM)
    body = _guest(data={"blob": "x" * 200_000})
    resp = TestClient(api).post("/api/applications/on-behalf", json=body)
    assert resp.status_code == 413
    assert service.payload is None


def test_route_caps_the_data_after_parsing(api: FastAPI, service: _FakeService) -> None:
    # The early cap reads the UTF-8 body; the authoritative check measures the escaped
    # JSON of `data`, where one "€" (3 bytes) takes 6 characters.
    _as(api, _PERM)
    body = _guest(data={"blob": "€" * 15_000})
    resp = TestClient(api).post("/api/applications/on-behalf", json=body)
    assert resp.status_code == 413
    assert service.payload is None


def test_search_route(api: FastAPI, service: _FakeService) -> None:
    _as(api, _PERM)
    resp = TestClient(api).get("/api/applications/on-behalf/applicants?q=an")
    assert resp.status_code == 200
    assert resp.json()[0]["displayName"] == "Anna"
    assert service.query == "an"


@pytest.mark.parametrize(
    "body",
    [
        # An account and a guest at once.
        {"applicantPrincipalId": str(uuid4()), "applicantEmail": "a@example.org"},
        # No applicant.
        {},
        # A guest without a name.
        {"applicantEmail": "a@example.org", "applicantName": " "},
        # A guest without an e-mail.
        {"applicantName": "A"},
    ],
)
def test_schema_needs_exactly_one_applicant(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        OnBehalfCreate.model_validate({"typeId": str(uuid4()), "data": {}, **body})


# --- service -------------------------------------------------------------------------


class _Row:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)

    def __getattr__(self, name: str) -> Any:  # only for a missing attribute
        raise AttributeError(name)


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    def __init__(self, *, get: Any = None, rows: list[Any] | None = None) -> None:
        self._get = get
        self._rows = rows or []
        self.statements: list[Any] = []

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._get

    async def scalars(self, stmt: Any) -> _Scalars:
        self.statements.append(stmt)
        return _Scalars(self._rows)


class _Recorder(ApplicationsService):
    """The service with a recording `create`, so the test sees the hand-off."""

    async def create(self, payload: Any, **kwargs: Any) -> tuple[Any, str]:  # type: ignore[override]
        self.created = (payload, kwargs)
        return _FakeApp(), str(payload.applicant_email)


def _payload(**extra: Any) -> OnBehalfCreate:
    return OnBehalfCreate.model_validate({**_guest(), **extra})


async def test_guest_capture_hands_off_to_the_normal_create() -> None:
    svc = _Recorder(_Session())  # type: ignore[arg-type]
    _, email = await svc.create_on_behalf(
        _payload(intake="  ", applicantName=" Gisela "), actor="clerk", today=date(2026, 10, 5)
    )
    assert email == "gisela@example.org"
    payload, kwargs = svc.created
    assert payload.applicant_name == "Gisela"
    assert kwargs["actor"] == "clerk"
    assert kwargs["email_confirmed"] is True
    assert kwargs["capture"] == Capture(
        owner_sub=None,
        applicant_principal_id=None,
        received_on=date(2026, 10, 5),
        intake=None,
    )


async def test_account_capture_takes_the_account() -> None:
    pid = uuid4()
    row = _Row(sub="anna-sub", email="anna@example.org", display_name=None, active=True)
    svc = _Recorder(_Session(get=row))  # type: ignore[arg-type]
    body = {"typeId": str(uuid4()), "data": {}, "applicantPrincipalId": str(pid)}
    await svc.create_on_behalf(
        OnBehalfCreate.model_validate({**body, "receivedOn": "2026-09-01", "intake": "Mail"}),
        actor="clerk",
        today=date(2026, 10, 5),
    )
    payload, kwargs = svc.created
    assert payload.applicant_email == "anna@example.org"
    assert payload.applicant_name is None
    assert kwargs["capture"].owner_sub == "anna-sub"
    assert kwargs["capture"].applicant_principal_id == pid
    assert kwargs["capture"].received_on == date(2026, 9, 1)
    assert kwargs["capture"].intake == "Mail"


@pytest.mark.parametrize(
    "row",
    [
        None,
        _Row(sub="x", email="x@example.org", display_name="X", active=False),
        _Row(sub="x", email=None, display_name="X", active=True),
    ],
)
async def test_unusable_account_answers_422(row: Any) -> None:
    svc = _Recorder(_Session(get=row))  # type: ignore[arg-type]
    body = {"typeId": str(uuid4()), "data": {}, "applicantPrincipalId": str(uuid4())}
    with pytest.raises(ValidationProblem) as exc:
        await svc.create_on_behalf(
            OnBehalfCreate.model_validate(body), actor="clerk", today=date(2026, 10, 5)
        )
    assert exc.value.code == "applicant_unavailable"


async def test_future_received_date_answers_422() -> None:
    svc = _Recorder(_Session())  # type: ignore[arg-type]
    with pytest.raises(ValidationProblem) as exc:
        await svc.create_on_behalf(
            _payload(receivedOn="2026-10-06"), actor="clerk", today=date(2026, 10, 5)
        )
    assert exc.value.code == "received_on_in_future"


async def test_applicant_search() -> None:
    rows = [_Row(id=uuid4(), display_name="Anna", email="anna@example.org")]
    session = _Session(rows=rows)
    svc = ApplicationsService(session)  # type: ignore[arg-type]
    assert await svc.search_applicants(" a ") == []
    assert session.statements == []
    hits = await svc.search_applicants("an")
    assert [h.email for h in hits] == ["anna@example.org"]
    assert len(session.statements) == 1


# --- detail ----------------------------------------------------------------------------


def test_application_out_carries_the_capture() -> None:
    out = ApplicationOut.model_validate(
        {
            "id": str(uuid4()),
            "typeId": str(uuid4()),
            "data": {},
            "version": 1,
            "createdAt": _NOW.isoformat(),
            "updatedAt": _NOW.isoformat(),
            "capture": {
                "capturedBy": {"kind": "gremium", "displayName": "StuPa"},
                "capturedAt": _NOW.isoformat(),
                "receivedOn": "2026-10-01",
                "intake": "per PDF",
            },
        }
    )
    dumped = out.model_dump(by_alias=True, mode="json")
    assert dumped["capture"]["receivedOn"] == "2026-10-01"
    assert dumped["capture"]["capturedBy"]["kind"] == "gremium"


# --- mail ------------------------------------------------------------------------------


def test_mail_template_is_in_the_catalogue() -> None:
    spec = CATALOGUE_BY_KEY["application_captured"]
    assert spec.subject_i18n is captured_mod.APPLICATION_CAPTURED_SUBJECT
    assert spec.body_i18n is captured_mod.APPLICATION_CAPTURED_BODY
    assert set(spec.subject_i18n) == {"de", "en"}


def test_format_date() -> None:
    assert captured_mod._format_date(None, "de") == ""  # noqa: SLF001
    assert captured_mod._format_date(date(2026, 10, 1), "de") == "01.10.2026"  # noqa: SLF001
    assert captured_mod._format_date(date(2026, 10, 1), "en") == "2026-10-01"  # noqa: SLF001


class _Queue:
    def __init__(self) -> None:
        self.messages: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.messages.append(msg)


class _MailSession:
    """The session of the mail task: the application, the name, no template override."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.committed = False

    async def __aenter__(self) -> _MailSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, model: Any, _pk: Any) -> Any:
        return self.app if model.__name__ == "Application" else _Row(name="StuPa")

    async def scalar(self, _stmt: Any) -> Any:
        return None

    async def scalars(self, _stmt: Any) -> Any:
        return _ScalarsFirst()

    async def execute(self, _stmt: Any) -> Any:
        return _Rows()

    async def commit(self) -> None:
        self.committed = True


class _ScalarsFirst:
    def first(self) -> None:
        return None

    def all(self) -> list[Any]:
        return []


class _Rows:
    def first(self) -> None:
        return None


@pytest.mark.parametrize("guest", [False, True])
async def test_mail_links(monkeypatch: pytest.MonkeyPatch, guest: bool) -> None:
    from app.modules.auth import service as auth_service
    from app.settings import load_settings

    app = _Row(
        id=uuid4(),
        gremium_id=uuid4(),
        data={"title": "Papier"},
        received_on=date(2026, 10, 1),
        capture_intake=None,
    )
    session = _MailSession(app)
    monkeypatch.setattr(captured_mod, "get_sessionmaker", lambda: lambda: session)

    async def _magic(
        _db: Any, _settings: Any, *, email: str, application_id: Any, deliver: Any
    ) -> None:
        await deliver(email, f"https://x/antrag/{application_id}#t=tok")

    monkeypatch.setattr(auth_service, "request_magic_link", _magic)
    queue = _Queue()
    settings = load_settings(public_base_url="https://x/")
    await captured_mod.notify_application_captured(
        queue=queue, settings=settings, application_id=app.id, email="a@example.org", guest=guest
    )
    (msg,) = queue.messages
    if guest:
        assert f"https://x/antrag/{app.id}#t=tok" in msg.text
        assert session.committed is True
    else:
        assert f"https://x/applications/{app.id}" in msg.text
        assert session.committed is False
    assert "StuPa" in msg.text


async def test_mail_without_application_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import load_settings

    session = _MailSession(None)
    monkeypatch.setattr(captured_mod, "get_sessionmaker", lambda: lambda: session)
    queue = _Queue()
    await captured_mod.notify_application_captured(
        queue=queue, settings=load_settings(), application_id=uuid4(), email="a@b.de", guest=False
    )
    assert queue.messages == []


async def test_mail_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import load_settings

    def _boom() -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(captured_mod, "get_sessionmaker", _boom)
    await captured_mod.notify_application_captured(
        queue=None, settings=load_settings(), application_id=uuid4(), email="a@b.de", guest=False
    )


async def test_deliver_capture_mail_wraps_the_notifier(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def _notify(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(router_mod, "notify_application_captured", _notify)
    app_id = uuid4()
    await router_mod._deliver_capture_mail(  # noqa: SLF001
        object(), "a@example.org", app_id, True, None  # type: ignore[arg-type]
    )
    assert calls[0]["application_id"] == app_id
    assert calls[0]["guest"] is True
    assert calls[0]["queue"] is None
