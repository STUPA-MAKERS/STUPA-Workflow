"""Unit-Tests der DSGVO/Privacy-Services (ohne DB).

Deckt PrincipalService (Erasure), ErasureRequestService (Queue: create/list/get/
execute/reject inkl. Guards), PrivacySettingsService (Single-Row mit Seed-Fallback)
und AuskunftService (PII-Sammlung Art. 15). Session über ``privacy_fakes.FakeSession``;
``audit_record`` läuft echt gegen den Fake (Advisory-Lock + Genesis = Defaults).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.modules.applications import service as applications_service
from app.modules.applications.models import Applicant, Application, SubmissionVersion
from app.modules.auth.models import Principal
from app.modules.privacy.models import ErasureRequest, PrivacySettings
from app.modules.privacy.service import (
    AuskunftService,
    ErasureRequestService,
    PrincipalService,
    PrivacySettingsService,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests._support.privacy_fakes import fake_session, result

_AT = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)


def _principal(**over: object) -> Principal:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "sub": "kc-123",
        "email": "user@example.org",
        "display_name": "User Example",
        "calendar_token": "tok",
        "oidc_groups": ["g1"],
        "active": True,
    }
    defaults.update(over)
    return Principal(**defaults)


def _erasure(**over: object) -> ErasureRequest:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "subject_type": "applicant",
        "application_id": uuid4(),
        "principal_id": None,
        "email": "a@example.org",
        "status": "open",
        "requested_by": "applicant",
    }
    defaults.update(over)
    return ErasureRequest(**defaults)


# --------------------------------------------------------------- PrincipalService
async def test_principal_erase_clears_pii_and_deactivates() -> None:
    principal = _principal()
    db = fake_session(gets=[principal])
    result_principal = await PrincipalService(db).erase(principal.id, actor="admin")
    assert result_principal is principal
    assert principal.email is None
    assert principal.display_name is None
    assert principal.calendar_token is None
    assert principal.oidc_groups is None
    assert principal.active is False
    # sub bleibt als Pseudonym erhalten (Audit-Kette/Keycloak-Verknüpfung).
    assert principal.sub == "kc-123"
    assert db.committed == 1
    # audit_record hängt einen Eintrag an.
    assert any(getattr(o, "action", None) == "principal_erased" for o in db.added)


async def test_principal_erase_unknown_raises_not_found() -> None:
    db = fake_session(gets=[None])
    with pytest.raises(NotFoundError):
        await PrincipalService(db).erase(uuid4(), actor="admin")


async def test_principal_erase_commit_false_flushes_only() -> None:
    principal = _principal()
    db = fake_session(gets=[principal])
    await PrincipalService(db).erase(principal.id, actor="admin", commit=False)
    assert db.committed == 0
    assert db.flushed >= 1


# ---------------------------------------------------------- PrivacySettingsService
async def test_settings_get_returns_existing_row() -> None:
    row = PrivacySettings(id=1, default_retention_months=36)
    db = fake_session(gets=[row])
    got = await PrivacySettingsService(db).get()
    assert got is row
    assert db.added == []  # Seed-Fallback nicht getriggert


async def test_settings_get_seeds_when_missing() -> None:
    db = fake_session(gets=[None])
    got = await PrivacySettingsService(db).get()
    assert isinstance(got, PrivacySettings)
    assert got.id == 1
    assert db.added == [got]
    assert db.flushed == 1


async def test_settings_update_persists_value() -> None:
    row = PrivacySettings(id=1, default_retention_months=24)
    db = fake_session(gets=[row])
    updated = await PrivacySettingsService(db).update(default_retention_months=12)
    assert updated.default_retention_months == 12
    assert db.committed == 1
    assert row in db.refreshed


# ------------------------------------------------------- ErasureRequestService.create
async def test_create_applicant_requires_application_id() -> None:
    db = fake_session()
    with pytest.raises(ValidationProblem):
        await ErasureRequestService(db).create(subject_type="applicant")


async def test_create_principal_requires_principal_id() -> None:
    db = fake_session()
    with pytest.raises(ValidationProblem):
        await ErasureRequestService(db).create(subject_type="principal")


async def test_create_applicant_unknown_application_raises_not_found() -> None:
    db = fake_session(gets=[None])  # Application existiert nicht
    with pytest.raises(NotFoundError):
        await ErasureRequestService(db).create(
            subject_type="applicant", application_id=uuid4()
        )


async def test_create_applicant_backfills_email_from_applicant() -> None:
    app_id = uuid4()
    db = fake_session(
        gets=[Application(id=app_id)],  # Existenzprüfung
        scalar=["found@example.org"],  # Applicant.email-Lookup
    )
    request = await ErasureRequestService(db).create(
        subject_type="applicant", application_id=app_id
    )
    assert request.email == "found@example.org"
    assert request.status == "open"
    assert db.committed == 1
    assert any(
        getattr(o, "action", None) == "erasure_requested" for o in db.added
    )


async def test_create_principal_records_requested_by() -> None:
    db = fake_session()
    request = await ErasureRequestService(db).create(
        subject_type="principal",
        principal_id=uuid4(),
        requested_by="admin-1",
    )
    assert request.requested_by == "admin-1"
    assert request.principal_id is not None


async def test_create_applicant_keeps_explicit_email() -> None:
    app_id = uuid4()
    db = fake_session(gets=[Application(id=app_id)])
    request = await ErasureRequestService(db).create(
        subject_type="applicant",
        application_id=app_id,
        email="explicit@example.org",
    )
    # Explizite Mail bleibt — kein Backfill-Lookup nötig.
    assert request.email == "explicit@example.org"


# --------------------------------------------------------- ErasureRequestService.list/get
async def test_list_all() -> None:
    rows = [_erasure(), _erasure()]
    db = fake_session(scalars=[result(*rows)])
    got = await ErasureRequestService(db).list()
    assert got == rows


async def test_list_filtered_by_status() -> None:
    rows = [_erasure(status="executed")]
    db = fake_session(scalars=[result(*rows)])
    got = await ErasureRequestService(db).list(status="executed")
    assert got == rows


async def test_get_returns_row() -> None:
    row = _erasure()
    db = fake_session(gets=[row])
    assert await ErasureRequestService(db).get(row.id) is row


# ------------------------------------------------------- ErasureRequestService.execute
async def test_execute_applicant_dispatches_anonymize(monkeypatch) -> None:
    calls: list[tuple[UUID, str, object, bool]] = []

    async def fake_anonymize(_self, application_id, *, files, actor, commit):  # type: ignore[no-untyped-def]
        # files (hier None) + commit=False belegen den Dispatch-Pfad.
        calls.append((application_id, actor, files, commit))

    monkeypatch.setattr(
        applications_service.ApplicationsService, "anonymize", fake_anonymize
    )
    request = _erasure(subject_type="applicant")
    db = fake_session(gets=[request])
    out = await ErasureRequestService(db).execute(request.id, actor="admin")
    assert out.status == "executed"
    assert out.handled_by == "admin"
    assert out.handled_at is not None
    # Anonymisierung dispatcht atomar (commit=False) auf die richtige Application.
    assert calls == [(request.application_id, "admin", None, False)]
    assert db.committed == 1


async def test_execute_principal_dispatches_erase() -> None:
    principal = _principal()
    request = _erasure(
        subject_type="principal", application_id=None, principal_id=principal.id
    )
    # _require_open get, dann PrincipalService.erase get.
    db = fake_session(gets=[request, principal])
    out = await ErasureRequestService(db).execute(request.id, actor="dpo")
    assert out.status == "executed"
    assert principal.active is False
    assert principal.email is None


async def test_execute_unknown_raises_not_found() -> None:
    db = fake_session(gets=[None])
    with pytest.raises(NotFoundError):
        await ErasureRequestService(db).execute(uuid4(), actor="admin")


async def test_execute_already_handled_raises_conflict() -> None:
    request = _erasure(status="executed")
    db = fake_session(gets=[request])
    with pytest.raises(ConflictError) as exc:
        await ErasureRequestService(db).execute(request.id, actor="admin")
    assert exc.value.code == "erasure_not_open"


async def test_execute_no_resolvable_subject_raises_conflict() -> None:
    # applicant ohne application_id (DB-Inkonsistenz) → kein Subjekt auflösbar.
    request = _erasure(subject_type="applicant", application_id=None)
    db = fake_session(gets=[request])
    with pytest.raises(ConflictError) as exc:
        await ErasureRequestService(db).execute(request.id, actor="admin")
    assert exc.value.code == "erasure_no_subject"


# -------------------------------------------------------- ErasureRequestService.reject
async def test_reject_sets_status_and_reason() -> None:
    request = _erasure()
    db = fake_session(gets=[request])
    out = await ErasureRequestService(db).reject(
        request.id, actor="admin", reason="not a valid request"
    )
    assert out.status == "rejected"
    assert out.handled_by == "admin"
    assert out.reason == "not a valid request"
    assert db.committed == 1


async def test_reject_unknown_raises_not_found() -> None:
    db = fake_session(gets=[None])
    with pytest.raises(NotFoundError):
        await ErasureRequestService(db).reject(uuid4(), actor="admin")


async def test_reject_already_handled_raises_conflict() -> None:
    request = _erasure(status="rejected")
    db = fake_session(gets=[request])
    with pytest.raises(ConflictError):
        await ErasureRequestService(db).reject(request.id, actor="admin")


# ---------------------------------------------------------------- AuskunftService
async def test_auskunft_empty_when_no_applicant_or_principal() -> None:
    db = fake_session(scalars=[result()], scalar=[None])  # keine Applicants, kein Principal
    data = await AuskunftService(db).collect("nobody@example.org")
    assert data["email"] == "nobody@example.org"
    assert data["applications"] == []
    assert data["versions"] == []
    assert data["principal"] is None


async def test_auskunft_collects_applications_versions_principal() -> None:
    app_id = uuid4()
    type_id = uuid4()
    state_id = "s-1"
    applicant = Applicant(application_id=app_id, email="x@example.org", name="X Person")
    application = Application(
        id=app_id, type_id=type_id, current_state_id=state_id, created_at=_AT, data={"k": "v"}
    )
    version = SubmissionVersion(
        application_id=app_id, version=1, changed_by="x", at=_AT, data={"k": "v"}
    )
    principal = _principal(email="x@example.org", last_login=_AT)
    db = fake_session(
        scalars=[
            result(applicant),  # applicants
            result(application),  # apps
            result(version),  # versions
        ],
        execute=[
            result((type_id, {"de": "Typ"})),  # type_names
            result((state_id, {"de": "Eingereicht"})),  # state_labels
        ],
        scalar=[principal],  # principal row
    )
    data = await AuskunftService(db).collect("x@example.org", locale="de")
    assert len(data["applications"]) == 1
    app_row = data["applications"][0]
    assert app_row["typeName"] == "Typ"
    assert app_row["status"] == "Eingereicht"
    assert app_row["applicantName"] == "X Person"
    assert len(data["versions"]) == 1
    assert data["versions"][0]["changedBy"] == "x"
    assert data["principal"]["email"] == "x@example.org"
    assert data["principal"]["sub"] == "kc-123"


async def test_auskunft_i18n_falls_back_and_handles_missing_state() -> None:
    app_id = uuid4()
    type_id = uuid4()
    applicant = Applicant(application_id=app_id, email="y@example.org", name="Y")
    # current_state_id None → state_labels-Query wird übersprungen.
    application = Application(
        id=app_id, type_id=type_id, current_state_id=None, created_at=_AT, data={}
    )
    db = fake_session(
        scalars=[
            result(applicant),
            result(application),
            result(),  # keine Versionen
        ],
        execute=[result((type_id, {"en": "Type"}))],  # nur EN → Fallback de→en
        scalar=[None],
    )
    data = await AuskunftService(db).collect("y@example.org", locale="de")
    assert data["applications"][0]["typeName"] == "Type"  # de fehlt → en
    assert data["applications"][0]["status"] == ""  # kein State
    assert data["versions"] == []
