"""Integration (echte Postgres, testcontainers): DSGVO/Privacy-Services (#PII-Re-Add).

Beweist gegen ein echtes Schema (data-model §1, security.md §4):
Principal-Erasure (Art. 17), Löschantrags-Queue (open→executed|rejected),
Anonymisierung räumt Magic-Links + Anhänge ab, der Aufbewahrungs-Cron
(``process_retention``) anonymisiert fällige terminale Anträge + purged
abgelaufene Auth-Artefakte (Budget-Zeilen bleiben unangetastet) und die
DSGVO-Auskunft (Art. 15) trägt alle PII zu einer E-Mail zusammen.

Die Type-/App-Seed-Helfer stammen aus dem applications-Service-Integrationstest.
(das ``note``-Feld ist dort bereits ``isPII``); sie werden hier wiederverwendet, nicht
dupliziert.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.models import (
    Applicant,
    Application,
    MagicLink,
)
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.auth import sessions
from app.modules.auth.models import ApplicantSession, AuthSession, Principal
from app.modules.budget.tree_models import Budget
from app.modules.files.models import Attachment
from app.modules.privacy.models import ErasureRequest, PrivacySettings
from app.modules.privacy.service import (
    AuskunftService,
    ErasureRequestService,
    PrincipalService,
    PrivacySettingsService,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from app.shared.xlsx import build_auskunft_workbook
from tests.integration.conftest import clear_privacy_tables
from tests.integration.modules.applications.test_applications_service import (
    _create_payload,
    _seed_type,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    clear_privacy_tables(engine)  # principal/auth_session/erasure_request/settings isolieren
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _seed_principal(
    session: AsyncSession, *, email: str | None = "u@example.org"
) -> Principal:
    principal = Principal(
        sub=f"kc-{uuid.uuid4()}",
        email=email,
        display_name="Max Mustermann",
        oidc_groups=["staff"],
        calendar_token=f"tok-{uuid.uuid4()}",
        active=True,
    )
    session.add(principal)
    await session.flush()
    return principal


async def _audit_actions_for(
    session: AsyncSession, target_id: str
) -> set[str]:
    rows = (
        await session.scalars(
            select(AuditEntry.action).where(AuditEntry.target_id == target_id)
        )
    ).all()
    return set(rows)


# --------------------------------------------------------------------------- #
# 1 — PrincipalService.erase
# --------------------------------------------------------------------------- #
async def test_principal_erase_clears_pii_keeps_sub(session: AsyncSession) -> None:
    principal = await _seed_principal(session)
    other = await _seed_principal(session, email="keep@example.org")
    original_sub = principal.sub

    own_session = AuthSession(
        sid=f"sid-{uuid.uuid4()}",
        principal_id=principal.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    other_session = AuthSession(
        sid=f"sid-{uuid.uuid4()}",
        principal_id=other.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    session.add_all([own_session, other_session])
    await session.commit()

    await PrincipalService(session).erase(principal.id, actor="admin")

    await session.refresh(principal)
    assert principal.email is None
    assert principal.display_name is None
    assert principal.oidc_groups is None
    assert principal.calendar_token is None
    assert principal.active is False
    assert principal.sub == original_sub  # Pseudonym bleibt

    own = (
        await session.scalars(
            select(AuthSession).where(AuthSession.principal_id == principal.id)
        )
    ).all()
    assert own == []  # eigene Sessions verworfen
    survivor = (
        await session.scalars(
            select(AuthSession).where(AuthSession.principal_id == other.id)
        )
    ).all()
    assert len(survivor) == 1  # fremde Session bleibt

    assert "principal_erased" in await _audit_actions_for(session, str(principal.id))


# --------------------------------------------------------------------------- #
# 2 — Erasure-Lifecycle: Antragsteller → execute (Anonymisierung)
# --------------------------------------------------------------------------- #
async def test_erasure_applicant_execute(session: AsyncSession) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))

    erasure = ErasureRequestService(session)
    req = await erasure.create(
        subject_type="applicant", application_id=app.id, requested_by="x"
    )
    assert req.status == "open"
    # EmailStr lowercased nur die Domain; der Local-Part bleibt wie eingegeben.
    assert req.email == "Antrag@example.org"  # aus dem Applicant nachgezogen
    assert "erasure_requested" in await _audit_actions_for(session, str(req.id))

    executed = await erasure.execute(req.id, actor="admin")
    assert executed.status == "executed"
    assert executed.handled_by == "admin"
    assert executed.handled_at is not None

    applicant = (
        await session.execute(select(Applicant).where(Applicant.application_id == app.id))
    ).scalar_one()
    assert applicant.email is None
    assert applicant.anonymized_at is not None

    refreshed = await session.get(Application, app.id)
    assert refreshed is not None
    assert refreshed.data.get("note") is None  # PII gescrubbt

    assert "anonymization" in await _audit_actions_for(session, str(app.id))
    assert "erasure_executed" in await _audit_actions_for(session, str(req.id))

    # zweites Ausführen → ConflictError (nicht mehr 'open')
    with pytest.raises(ConflictError):
        await erasure.execute(req.id, actor="admin")


async def test_anonymize_revokes_applicant_sessions(session: AsyncSession) -> None:
    """Kill-Switch (ISSUE_TOKEN): Anonymisierung widerruft offene Applicant-Sessions —
    ein vor der Löschung ausgegebener Magic-Link-Token greift danach nicht mehr."""
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))
    await sessions.create_applicant_session(
        session,
        secret="x" * 16,
        application_id=app.id,
        scope="edit",
        expires_at=datetime.now(UTC) + timedelta(hours=12),
    )
    await session.commit()

    await svc.anonymize(app.id, actor="admin")

    rows = (
        await session.execute(
            select(ApplicantSession).where(ApplicantSession.application_id == app.id)
        )
    ).scalars().all()
    assert rows  # Zeile bleibt (Audit), ist aber widerrufen
    assert all(r.revoked_at is not None for r in rows)


# --------------------------------------------------------------------------- #
# 3 — Erasure-Lifecycle: Principal → reject (Subjekt bleibt unangetastet)
# --------------------------------------------------------------------------- #
async def test_erasure_principal_reject(session: AsyncSession) -> None:
    principal = await _seed_principal(session, email="bleibt@example.org")
    await session.commit()

    erasure = ErasureRequestService(session)
    req = await erasure.create(subject_type="principal", principal_id=principal.id)
    assert req.status == "open"

    rejected = await erasure.reject(req.id, actor="admin", reason="nope")
    assert rejected.status == "rejected"
    assert rejected.reason == "nope"
    assert rejected.handled_by == "admin"
    assert "erasure_rejected" in await _audit_actions_for(session, str(req.id))

    await session.refresh(principal)
    assert principal.email == "bleibt@example.org"  # NICHT gelöscht
    assert principal.active is True


# --------------------------------------------------------------------------- #
# 4 — anonymize entfernt Magic-Links + Anhänge
# --------------------------------------------------------------------------- #
async def test_anonymize_drops_magic_links_and_attachments(session: AsyncSession) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))

    session.add(
        MagicLink(
            application_id=app.id,
            token_hash=b"x",
            scope="edit",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    session.add(
        Attachment(
            application_id=app.id,
            filename="beleg.pdf",
            mime="application/pdf",
            size=123,
            storage_key="k",
        )
    )
    await session.commit()

    await svc.anonymize(app.id)

    links = await session.scalar(
        select(func.count())
        .select_from(MagicLink)
        .where(MagicLink.application_id == app.id)
    )
    attachments = await session.scalar(
        select(func.count())
        .select_from(Attachment)
        .where(Attachment.application_id == app.id)
    )
    assert links == 0
    assert attachments == 0


# --------------------------------------------------------------------------- #
# 5 — Aufbewahrungs-Cron (process_retention)
# --------------------------------------------------------------------------- #
async def test_retention_cron(migrated: tuple[str, str], session: AsyncSession) -> None:
    from worker.retention import process_retention

    app_type, draft, _ = await _seed_type(session)
    # `draft` ist initial+editierbar; einen terminalen Status ergänzen.
    draft.is_terminal = True  # initial-State zugleich terminal — reicht für den Sweep
    await session.commit()

    svc = ApplicationsService(session)

    # (a) terminaler Antrag, lange her → fällig → wird anonymisiert.
    due_app, _ = await svc.create(_create_payload(app_type.id))
    # (b) terminaler Antrag, frisch → NICHT fällig.
    fresh_terminal, _ = await svc.create(_create_payload(app_type.id))

    # `updated_at` hat onupdate=now → per explizitem UPDATE (über die Session) backdaten.
    old = datetime.now(UTC) - timedelta(days=3 * 365)
    await session.execute(
        update(Application).where(Application.id == due_app.id).values(updated_at=old)
    )

    # (c) abgelaufene Auth-Session + benutzter Magic-Link → werden gepurged.
    principal = await _seed_principal(session)
    expired_session = AuthSession(
        sid=f"sid-{uuid.uuid4()}",
        principal_id=principal.id,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    session.add(expired_session)
    session.add(
        MagicLink(
            application_id=fresh_terminal.id,
            token_hash=f"used-{uuid.uuid4()}".encode(),
            scope="edit",
            expires_at=datetime.now(UTC) + timedelta(days=10),
            used_at=datetime.now(UTC) - timedelta(days=1),
        )
    )

    # (d) Budget-Zeile (Finanz-Aufbewahrung) → MUSS unangetastet bleiben.
    budget = Budget(
        key=f"b-{uuid.uuid4()}",
        path_key=f"VS-{uuid.uuid4()}",
        name="Kostenstelle",
    )
    session.add(budget)
    await session.commit()
    # IDs jetzt festhalten — nach ``expire_all()`` würde ein Attribut-Zugriff auf die
    # ORM-Objekte eine (unzulässige) Lazy-IO außerhalb des Greenlet-Kontexts auslösen.
    budget_id = budget.id
    expired_session_id = expired_session.id
    due_app_id = due_app.id
    fresh_terminal_id = fresh_terminal.id

    maker = async_sessionmaker(
        create_async_engine(migrated[1]), expire_on_commit=False
    )
    summary = await process_retention({"retention_sessionmaker": maker})
    assert isinstance(summary, str)

    # Der Worker schrieb über eine eigene Engine — die Identity-Map dieser Session
    # hält veraltete Kopien; verwerfen, damit alle Reads frisch aus der DB kommen.
    session.expire_all()

    # fälliger Antrag anonymisiert …
    due_applicant = (
        await session.execute(
            select(Applicant).where(Applicant.application_id == due_app_id)
        )
    ).scalar_one()
    assert due_applicant.anonymized_at is not None
    assert due_applicant.email is None

    # … frischer terminaler Antrag NICHT.
    fresh_applicant = (
        await session.execute(
            select(Applicant).where(Applicant.application_id == fresh_terminal_id)
        )
    ).scalar_one()
    assert fresh_applicant.anonymized_at is None

    # abgelaufene Session + benutzter Magic-Link weg.
    surviving_session = await session.scalar(
        select(func.count())
        .select_from(AuthSession)
        .where(AuthSession.id == expired_session_id)
    )
    assert surviving_session == 0
    remaining_links = await session.scalar(
        select(func.count())
        .select_from(MagicLink)
        .where(MagicLink.application_id == fresh_terminal_id)
    )
    assert remaining_links == 0

    # Budget unangetastet.
    assert await session.get(Budget, budget_id) is not None


# --------------------------------------------------------------------------- #
# 6 — DSGVO-Auskunft (Art. 15)
# --------------------------------------------------------------------------- #
async def test_auskunft_collect_and_workbook(session: AsyncSession) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, email = await svc.create(_create_payload(app_type.id))
    await svc.patch(
        app.id,
        {"title": "Geändert", "cost": "150.00", "note": "geheim2"},
        changed_by="applicant",
    )

    result = await AuskunftService(session).collect(email)
    assert result["email"] == email

    app_ids = {a["id"] for a in result["applications"]}
    assert app.id in app_ids
    found = next(a for a in result["applications"] if a["id"] == app.id)
    assert found["data"]["title"] == "Geändert"

    versions = [v for v in result["versions"] if v["applicationId"] == app.id]
    assert {v["version"] for v in versions} == {1, 2}

    assert result["principal"] is None  # kein Login-Subjekt zu dieser Mail

    blob = build_auskunft_workbook(**result)
    assert isinstance(blob, bytes)
    assert len(blob) > 0


# --------------------------------------------------------------------------- #
# 6b — Auskunft ohne Treffer (kein Applicant): leere Reihen, aber valide Mappe
# --------------------------------------------------------------------------- #
async def test_auskunft_collect_no_match(session: AsyncSession) -> None:
    result = await AuskunftService(session).collect("niemand@example.org")
    assert result["applications"] == []
    assert result["versions"] == []
    assert result["principal"] is None
    blob = build_auskunft_workbook(**result)
    assert isinstance(blob, bytes)
    assert len(blob) > 0


# --------------------------------------------------------------------------- #
# 6c — PrincipalService.erase auf einen unbekannten Principal → NotFoundError
# --------------------------------------------------------------------------- #
async def test_principal_erase_unknown_raises(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await PrincipalService(session).erase(uuid.uuid4(), actor="admin")


# --------------------------------------------------------------------------- #
# 6d — execute auf einen Antrag ohne auflösbares Subjekt → ConflictError
# --------------------------------------------------------------------------- #
async def test_erasure_execute_no_resolvable_subject(session: AsyncSession) -> None:
    # Per ON-DELETE-SET-NULL kann ein offener Antrag ohne FK-Subjekt zurückbleiben;
    # hier direkt eingefügt (am ``create``-Validator vorbei), um den Pfad zu treffen.
    orphan = ErasureRequest(subject_type="applicant", application_id=None, status="open")
    session.add(orphan)
    await session.commit()
    with pytest.raises(ConflictError):
        await ErasureRequestService(session).execute(orphan.id, actor="admin")


# --------------------------------------------------------------------------- #
# 7 — PrivacySettingsService: Re-Seed bei fehlender Single-Row + Round-Trip
# --------------------------------------------------------------------------- #
async def test_settings_get_recreates_missing_singleton(session: AsyncSession) -> None:
    # Defensiver Pfad: die Seed-Zeile (id=1) fehlt → get() legt sie neu an.
    await session.execute(delete(PrivacySettings).where(PrivacySettings.id == 1))
    await session.commit()
    assert await session.get(PrivacySettings, 1) is None

    svc = PrivacySettingsService(session)
    settings = await svc.get()
    assert settings.id == 1
    # Default-Aufbewahrung (server_default 24) liegt an.
    assert settings.default_retention_months == 24

    updated = await svc.update(default_retention_months=6)
    assert updated.default_retention_months == 6

    # frisch aus der DB (eigene Session-Abfrage, kein expired-Attr-Zugriff).
    await session.refresh(settings)
    assert settings.default_retention_months == 6


# --------------------------------------------------------------------------- #
# 8 — ErasureRequestService.execute für ein PRINCIPAL-Subjekt
# --------------------------------------------------------------------------- #
async def test_erasure_principal_execute(session: AsyncSession) -> None:
    principal = await _seed_principal(session, email="weg@example.org")
    await session.commit()
    pid = principal.id

    erasure = ErasureRequestService(session)
    req = await erasure.create(subject_type="principal", principal_id=pid)
    assert req.status == "open"

    executed = await erasure.execute(req.id, actor="admin")
    assert executed.status == "executed"
    assert executed.handled_by == "admin"

    await session.refresh(principal)
    assert principal.email is None
    assert principal.active is False

    actions = await _audit_actions_for(session, str(req.id))
    assert "erasure_executed" in actions
    assert "principal_erased" in await _audit_actions_for(session, str(pid))


# --------------------------------------------------------------------------- #
# 9 — ErasureRequestService.create: Validierung der Subjekt-IDs
# --------------------------------------------------------------------------- #
async def test_erasure_create_validation(session: AsyncSession) -> None:
    erasure = ErasureRequestService(session)
    with pytest.raises(ValidationProblem):
        await erasure.create(subject_type="applicant")  # ohne application_id
    with pytest.raises(ValidationProblem):
        await erasure.create(subject_type="principal")  # ohne principal_id


# --------------------------------------------------------------------------- #
# 10 — AuskunftService.collect: Treffer in BEIDEN Quellen (Applicant + Principal)
# --------------------------------------------------------------------------- #
async def test_auskunft_collect_applicant_and_principal(session: AsyncSession) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    app, email = await svc.create(_create_payload(app_type.id))
    # zweite Version → Versionshistorie len>=2
    await svc.patch(
        app.id,
        {"title": "v2", "cost": "200.00", "note": "neu"},
        changed_by="applicant",
    )
    # Login-Subjekt MIT derselben E-Mail → principal-Zweig nicht None.
    await _seed_principal(session, email=email)
    await session.commit()

    result = await AuskunftService(session).collect(email)
    assert result["email"] == email
    assert {a["id"] for a in result["applications"]} >= {app.id}
    versions = [v for v in result["versions"] if v["applicationId"] == app.id]
    assert len(versions) >= 2
    assert {v["version"] for v in versions} == {1, 2}

    assert result["principal"] is not None
    assert result["principal"]["email"] == email

    blob = build_auskunft_workbook(**result)
    assert isinstance(blob, bytes)
    assert len(blob) > 0
