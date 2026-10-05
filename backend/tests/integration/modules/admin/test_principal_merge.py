"""Account merge ("Konten zusammenführen") against a real Postgres.

The tests seed one old principal (a Keycloak-era `sub`) with a row in every area
that references a principal, and one new principal. They prove:

* the preview counts what the merge then does, and writes nothing,
* the merge rewrites every reference, combines harmless duplicates and removes the
  sessions, tokens, memberships and the feed token of the old principal,
* each real conflict blocks the preview and the merge, and the merge then writes
  nothing,
* a secret ballot stays anonymous: only the voted marker moves,
* the old principal is locked: no login, no reactivation, no second merge,
* the displays (timeline, versions, comments, audit list, budget) follow the merge,
* the audit log keeps its rows and gets one `principal_merge` entry,
* a failure inside the merge rolls back everything,
* the routes need `admin.users.merge`.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin import principal_merge as merge_mod
from app.modules.admin.models import (
    GremiumMembership,
    GremiumRole,
    SiteConfigVersion,
)
from app.modules.admin.principal_merge import PrincipalMergeService
from app.modules.applications.models import (
    Application,
    ApplicationShare,
    Comment,
    GuestApplicationSettings,
    StatusEvent,
    SubmissionVersion,
)
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry, AuditVerification
from app.modules.audit.service import AuditService
from app.modules.auth import oidc
from app.modules.auth.models import AuthSession, Role, RoleAssignment
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oauth_models import OAuthAuthorizationCode, OAuthToken
from app.modules.auth.principal import Principal
from app.modules.auth.service import upsert_principal
from app.modules.backup.models import Backup
from app.modules.budget.tree_models import Budget, BudgetExpense, FiscalYear, Invoice
from app.modules.config_revision.models import ConfigRevision
from app.modules.delegations.models import (
    DelegationSubstitute,
    MeetingDelegation,
    SubstituteGroup,
    SubstituteGroupMember,
)
from app.modules.forms.models import FormVersion
from app.modules.livevote.models import Meeting, MeetingAttendance, ProtocolKeeperPeriod
from app.modules.notifications.models import NotificationPreference
from app.modules.privacy.models import ErasureRequest
from app.modules.protocol.models import Protocol
from app.modules.voting.models import Ballot, SecretBallot, Vote, VotedMarker
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from tests._support.guest_apps import build_api, guest_settings
from tests._support.read_models import (
    ReadSeed,
    create_app,
    fire,
    patch,
    seed_read_world,
)

pytestmark = pytest.mark.integration

OLD_NAME = "Erika Alt"
NEW_NAME = "Erika Neu"
ADMIN_SUB = "merge-admin"
_VOTE_CONFIG: dict[str, Any] = {"options": ["yes", "no", "abstain"]}


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


# The rows of a test that the `engine` fixture does not clear: the principals with their
# tokens, preferences and roles, the budget, the bookings, the backups and the site config
# versions. Without the cleanup they leak into the later tests of the session (a list of
# all invoices or of all OAuth grants then counts them).
_CREATED: list[tuple[list[uuid.UUID], list[str], uuid.UUID | None]] = []


@pytest.fixture(autouse=True)
def _cleanup(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        for ids, subs, budget_id in _CREATED:
            p = {"ids": ids, "subs": subs}
            for table, column in (
                ("oauth_token", "principal_id"),
                ("oauth_authorization_code", "principal_id"),
                ("auth_session", "principal_id"),
                ("notification_preference", "principal_id"),
                ("role_assignment", "principal_id"),
                ("gremium_membership", "principal_id"),
                ("delegation_substitute", "substitute_principal_id"),
                ("delegation_substitute", "member_principal_id"),
                ("erasure_request", "principal_id"),
            ):
                conn.execute(text(f"DELETE FROM {table} WHERE {column} = ANY(:ids)"), p)
            for table, column in (
                ("erasure_request", "requested_by"),
                ("backup", "created_by"),
                ("site_config_version", "created_by"),
                ("invoice", "actor"),
                ("budget_expense", "actor"),
            ):
                conn.execute(text(f"DELETE FROM {table} WHERE {column} = ANY(:subs)"), p)
            if budget_id is not None:
                for stmt in (
                    "DELETE FROM budget_expense WHERE budget_id = :b",
                    "DELETE FROM fiscal_year WHERE budget_id = :b",
                    "DELETE FROM budget WHERE id = :b",
                ):
                    conn.execute(text(stmt), {"b": budget_id})
    _CREATED.clear()


@dataclass
class World:
    seed: ReadSeed
    old_id: uuid.UUID
    old_sub: str
    new_id: uuid.UUID
    new_sub: str
    other_id: uuid.UUID
    gremium_id: uuid.UUID
    app_id: uuid.UUID
    meeting_id: uuid.UUID
    second_meeting_id: uuid.UUID
    open_vote_id: uuid.UUID
    secret_vote_id: uuid.UUID


def _tag() -> str:
    return uuid.uuid4().hex[:8]


async def _people(
    maker: async_sessionmaker[AsyncSession], seed: ReadSeed
) -> tuple[PrincipalRow, PrincipalRow, PrincipalRow]:
    """The old (Keycloak-era) principal, the new one and a third person."""
    tag = _tag()
    async with maker() as session:
        old = PrincipalRow(
            sub=f"e03ad7d7-{tag}",
            display_name=OLD_NAME,
            email=f"alt-{tag}@example.org",
            calendar_token=f"cal-{tag}",
            oidc_groups=[],
        )
        new = PrincipalRow(
            sub=f"authentik-{tag}", display_name=NEW_NAME, email=f"neu-{tag}@example.org"
        )
        other = PrincipalRow(sub=f"other-{tag}", display_name="Otto Andere")
        session.add_all([old, new, other])
        await session.commit()
        return old, new, other


async def _meeting(session: AsyncSession, gremium_id: uuid.UUID, title: str) -> Meeting:
    meeting = Meeting(gremium_id=gremium_id, title=title, date=date(2025, 3, 1))
    session.add(meeting)
    await session.flush()
    return meeting


async def _vote(
    session: AsyncSession,
    gremium_id: uuid.UUID,
    question: str,
    *,
    secret: bool = False,
    meeting_id: uuid.UUID | None = None,
) -> Vote:
    vote = Vote(
        eligible_group=str(gremium_id),
        question=question,
        config={**_VOTE_CONFIG, "secret": secret},
        status="closed",
        meeting_id=meeting_id,
    )
    session.add(vote)
    await session.flush()
    return vote


async def _seed(maker: async_sessionmaker[AsyncSession]) -> World:
    """Give the old principal one row in every area that references a principal."""
    seed = await seed_read_world(maker)
    old, new, other = await _people(maker, seed)
    tag = _tag()

    # Applications: creator, a transition, a version and a comment of the old account.
    app_id = await create_app(maker, seed, actor=old.sub, title="Antrag Alt")
    await fire(
        maker,
        app_id,
        seed.to_review_id,
        Principal(sub=old.sub, roles=["admin"], permissions=set()),
    )
    await patch(maker, app_id, {"title": "Antrag Alt 2"}, changed_by=old.sub)
    async with maker() as session:
        await ApplicationsService(session).add_comment(
            app_id, author=old.sub, author_kind="principal", body="Hallo", visibility="internal"
        )

    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None
        app.archived_by = old.sub
        session.add(
            ApplicationShare(
                application_id=app_id,
                token_hash=uuid.uuid4().bytes,
                expires_at=datetime.now(UTC) + timedelta(days=1),
                created_by=old.sub,
            )
        )
        session.add(GuestApplicationSettings(id=1, updated_by=old.sub))

        # Meetings, the minute-taker, a keeper period, the protocol, attendance.
        meeting = await _meeting(session, seed.gremium_id, f"Sitzung A {tag}")
        meeting.created_by = old.sub
        meeting.protokollant_id = old.id
        second = await _meeting(session, seed.gremium_id, f"Sitzung B {tag}")
        session.add_all(
            [
                ProtocolKeeperPeriod(
                    meeting_id=meeting.id, principal_id=old.id, handed_over_by=old.sub
                ),
                Protocol(meeting_id=meeting.id, gremium_id=seed.gremium_id, author=old.sub),
                MeetingAttendance(
                    meeting_id=meeting.id, principal_id=old.id, status="present", source="self"
                ),
                # A third person delegated to the old account in meeting A.
                MeetingDelegation(
                    meeting_id=meeting.id,
                    gremium_id=seed.gremium_id,
                    delegator_principal_id=other.id,
                    delegate_principal_id=old.id,
                    created_by=other.sub,
                ),
                # The old account delegated its seat to a third person in meeting B.
                MeetingDelegation(
                    meeting_id=second.id,
                    gremium_id=seed.gremium_id,
                    delegator_principal_id=old.id,
                    delegate_principal_id=other.id,
                    delegate_voting=True,
                    created_by=old.sub,
                ),
            ]
        )

        # Votes: an open ballot and a secret vote (marker + anonymous choice).
        open_vote = await _vote(session, seed.gremium_id, "Offene Frage")
        secret_vote = await _vote(session, seed.gremium_id, "Geheime Frage", secret=True)
        session.add_all(
            [
                Ballot(vote_id=open_vote.id, voter_sub=old.sub, choice="yes"),
                VotedMarker(vote_id=secret_vote.id, voter_sub=old.sub),
                SecretBallot(vote_id=secret_vote.id, choice="no"),
                Ballot(vote_id=open_vote.id, voter_sub=other.sub, choice="no"),
            ]
        )

        # Substitute pool and a faculty group.
        group = SubstituteGroup(
            gremium_id=seed.gremium_id, name_i18n={"de": "Fak"}, created_by=old.sub
        )
        session.add(group)
        await session.flush()
        session.add_all(
            [
                DelegationSubstitute(
                    gremium_id=seed.gremium_id,
                    member_principal_id=other.id,
                    substitute_principal_id=old.id,
                    created_by=old.sub,
                ),
                SubstituteGroupMember(
                    group_id=group.id,
                    principal_id=old.id,
                    gremium_id=seed.gremium_id,
                    kind="member",
                    created_by=old.sub,
                ),
            ]
        )

        # Budget: a booking and an invoice.
        budget = Budget(parent_id=None, key=f"M{tag}", path_key=f"M{tag}", name="Merge")
        session.add(budget)
        await session.flush()
        year = FiscalYear(
            budget_id=budget.id, year=2025, start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
        )
        session.add(year)
        await session.flush()
        session.add_all(
            [
                BudgetExpense(
                    budget_id=budget.id,
                    fiscal_year_id=year.id,
                    amount=Decimal("10.00"),
                    description="Kaffee",
                    actor=old.sub,
                ),
                Invoice(gross_amount=Decimal("10.00"), actor=old.sub),
            ]
        )

        # Config, roles, privacy, backups, stored audit checks.
        role = (await session.scalars(select(Role).where(Role.key == "member"))).first()
        if role is None:
            role = Role(key="member", name_i18n={"de": "Mitglied"})
            session.add(role)
            await session.flush()
        session.add_all(
            [
                SiteConfigVersion(
                    version=secrets.randbelow(10**8) + 10**6, created_by=old.sub
                ),
                ConfigRevision(
                    entity_type="flow", entity_id=f"merge-{tag}", version=1, created_by=old.sub
                ),
                FormVersion(application_type_id=seed.type_id, version=99, created_by=old.id),
                RoleAssignment(
                    principal_id=old.id, role_id=role.id, granted_by=old.sub, delegated_by=old.sub
                ),
                ErasureRequest(
                    subject_type="applicant",
                    application_id=app_id,
                    status="executed",
                    requested_by=old.sub,
                    handled_by=old.sub,
                ),
                Backup(created_by=old.sub),
                AuditVerification(
                    started_at=datetime.now(UTC),
                    valid=True,
                    checked=0,
                    trigger="manual",
                    triggered_by=old.sub,
                ),
                NotificationPreference(principal_id=old.id, kind="comment", enabled=False),
                AuthSession(
                    sid=f"sid-{tag}",
                    principal_id=old.id,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                OAuthAuthorizationCode(
                    code_hash=uuid.uuid4().bytes,
                    principal_id=old.id,
                    client_id="mcp",
                    redirect_uri="http://127.0.0.1/cb",
                    code_challenge="x",
                    scope="read",
                    expires_at=datetime.now(UTC) + timedelta(minutes=1),
                ),
                OAuthToken(
                    principal_id=old.id,
                    client_id="mcp",
                    access_token_hash=uuid.uuid4().bytes,
                    scope="read",
                ),
            ]
        )
        member_role = (
            await session.scalars(
                select(GremiumRole).where(
                    GremiumRole.gremium_id == seed.gremium_id, GremiumRole.key == "member"
                )
            )
        ).one()
        session.add(
            GremiumMembership(
                principal_id=old.id, gremium_id=seed.gremium_id, gremium_role_id=member_role.id
            )
        )
        # One audit entry of the old account. The merge must leave it as it is.
        await AuditService(session).record(
            actor=old.sub, action="login", target_type="principal", target_id=str(old.id)
        )
        await session.commit()
        _CREATED.append(([old.id, new.id, other.id], [old.sub, new.sub, other.sub], budget.id))
        return World(
            seed=seed,
            old_id=old.id,
            old_sub=old.sub,
            new_id=new.id,
            new_sub=new.sub,
            other_id=other.id,
            gremium_id=seed.gremium_id,
            app_id=app_id,
            meeting_id=meeting.id,
            second_meeting_id=second.id,
            open_vote_id=open_vote.id,
            secret_vote_id=secret_vote.id,
        )


async def _count(session: AsyncSession, column: Any, value: object) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(column.class_).where(column == value)
        )
        or 0
    )


def _areas(body: Any) -> dict[str, dict[str, int]]:
    areas = body["areas"] if isinstance(body, dict) else [a.model_dump() for a in body.areas]
    return {a["area"]: {k: a[k] for k in ("rewritten", "combined", "removed")} for a in areas}


SUB_REFS = [c for _, c in merge_mod.SUB_COLUMNS]
ID_REFS = [c for _, c in merge_mod.ID_COLUMNS]


async def test_merge_rewrites_every_area(maker: async_sessionmaker[AsyncSession]) -> None:
    w = await _seed(maker)

    async with maker() as session:
        preview = await PrincipalMergeService(session).preview(w.old_id, w.new_id)
    assert preview.can_merge is True
    assert preview.conflicts == []
    assert preview.source.display_name == OLD_NAME
    assert preview.target.display_name == NEW_NAME
    before = _areas(preview)
    # Every sub column and every id column has a row of the old account.
    async with maker() as session:
        for column in SUB_REFS:
            assert await _count(session, column, w.old_sub) >= 1, str(column)
        for column in ID_REFS:
            assert await _count(session, column, w.old_id) >= 1, str(column)
        # The preview wrote nothing.
        old = await session.get(PrincipalRow, w.old_id)
        assert old is not None and old.merged_into is None

    async with maker() as session:
        result = await PrincipalMergeService(session).merge(
            w.old_id, w.new_id, actor=ADMIN_SUB
        )
    after = _areas(result)
    assert after == before
    assert after["timeline"]["rewritten"] >= 2
    assert after["votes"] == {"rewritten": 2, "combined": 0, "removed": 0}
    assert after["sessions"] == {"rewritten": 0, "combined": 0, "removed": 3}
    assert after["memberships"]["removed"] == 1
    assert after["calendar"]["removed"] == 1

    async with maker() as session:
        for column in SUB_REFS:
            assert await _count(session, column, w.old_sub) == 0, str(column)
            assert await _count(session, column, w.new_sub) >= 1, str(column)
        for column in ID_REFS:
            assert await _count(session, column, w.old_id) == 0, str(column)
            assert await _count(session, column, w.new_id) >= 1, str(column)
        for column in (
            AuthSession.principal_id,
            OAuthToken.principal_id,
            OAuthAuthorizationCode.principal_id,
            GremiumMembership.principal_id,
        ):
            assert await _count(session, column, w.old_id) == 0, str(column)
        assert await _count(session, NotificationPreference.principal_id, w.new_id) == 1
        assert await _count(session, RoleAssignment.principal_id, w.new_id) == 1
        assert await _count(session, MeetingAttendance.principal_id, w.new_id) == 1
        assert await _count(session, DelegationSubstitute.substitute_principal_id, w.new_id) == 1
        assert await _count(session, SubstituteGroupMember.principal_id, w.new_id) == 1
        # The erasure request stays on the old account: it is the proof.
        old = await session.get(PrincipalRow, w.old_id)
        assert old is not None
        assert old.merged_into == w.new_id
        assert old.merged_at is not None
        assert old.active is False
        assert old.calendar_token is None
        # The old row keeps its name for the admin list.
        assert old.display_name == OLD_NAME

        # The audit log keeps the old rows and gets one merge entry.
        entries = (await session.scalars(select(AuditEntry).order_by(AuditEntry.id))).all()
        assert any(e.actor == w.old_sub and e.action == "login" for e in entries)
        merge_entry = [e for e in entries if e.action == "principal_merge"]
        assert len(merge_entry) == 1
        assert merge_entry[0].actor == ADMIN_SUB
        assert merge_entry[0].target_id == str(w.old_id)
        assert merge_entry[0].data["sourceId"] == str(w.old_id)
        assert merge_entry[0].data["targetId"] == str(w.new_id)
        assert merge_entry[0].data["counts"]["votes"] == {"rewritten": 2}
        verification = await AuditService(session).verify_chain()
        assert verification.valid is True
        # The config revisions are append-only too: they keep the old sub, and the
        # version sidebar resolves it to the new name.
        assert await _count(session, ConfigRevision.created_by, w.old_sub) == 1
        names = await AuditService(session).resolve_actor_names([w.old_sub])
        assert names == {w.old_sub: NEW_NAME}


async def test_secret_ballot_stays_anonymous(maker: async_sessionmaker[AsyncSession]) -> None:
    w = await _seed(maker)
    async with maker() as session:
        before = (
            await session.execute(
                text("SELECT * FROM secret_ballot WHERE vote_id = :v"), {"v": w.secret_vote_id}
            )
        ).mappings().all()
    async with maker() as session:
        await PrincipalMergeService(session).merge(w.old_id, w.new_id, actor=ADMIN_SUB)
    async with maker() as session:
        after = (
            await session.execute(
                text("SELECT * FROM secret_ballot WHERE vote_id = :v"), {"v": w.secret_vote_id}
            )
        ).mappings().all()
        marker = (
            await session.scalars(
                select(VotedMarker.voter_sub).where(VotedMarker.vote_id == w.secret_vote_id)
            )
        ).all()
    # The choice half has no identity and did not change at all.
    assert [dict(r) for r in after] == [dict(r) for r in before]
    assert all("sub" not in k and "principal" not in k for k in after[0])
    # Only the identity half (who voted) moved to the new account.
    assert marker == [w.new_sub]


async def test_duplicates_are_combined(maker: async_sessionmaker[AsyncSession]) -> None:
    w = await _seed(maker)
    async with maker() as session:
        role = (await session.scalars(select(Role).where(Role.key == "member"))).one()
        group = (
            await session.scalars(
                select(SubstituteGroup).where(SubstituteGroup.gremium_id == w.gremium_id)
            )
        ).one()
        second_group = SubstituteGroup(gremium_id=w.gremium_id, name_i18n={"de": "Fak 2"})
        session.add(second_group)
        await session.flush()
        session.add_all(
            [
                # The new account has the same rows: they win.
                NotificationPreference(principal_id=w.new_id, kind="comment", enabled=True),
                RoleAssignment(principal_id=w.new_id, role_id=role.id),
                MeetingAttendance(
                    meeting_id=w.meeting_id, principal_id=w.new_id, status="present", source="lead"
                ),
                DelegationSubstitute(
                    gremium_id=w.gremium_id,
                    member_principal_id=w.other_id,
                    substitute_principal_id=w.new_id,
                ),
                # The new account is a member in another group of the same gremium.
                SubstituteGroupMember(
                    group_id=second_group.id,
                    principal_id=w.new_id,
                    gremium_id=w.gremium_id,
                    kind="member",
                ),
                # The old account substitutes for the new one: that means nothing later.
                DelegationSubstitute(
                    gremium_id=w.gremium_id,
                    member_principal_id=w.new_id,
                    substitute_principal_id=w.old_id,
                ),
                # A gremium-wide entry of the old account moves.
                DelegationSubstitute(
                    gremium_id=w.gremium_id,
                    member_principal_id=None,
                    substitute_principal_id=w.old_id,
                ),
                # The old account is a member whom a third person substitutes.
                DelegationSubstitute(
                    gremium_id=w.gremium_id,
                    member_principal_id=w.old_id,
                    substitute_principal_id=w.other_id,
                ),
                DelegationSubstitute(
                    gremium_id=w.gremium_id,
                    member_principal_id=w.new_id,
                    substitute_principal_id=w.other_id,
                ),
            ]
        )
        assert group is not None
        await session.commit()

    async with maker() as session:
        preview = await PrincipalMergeService(session).preview(w.old_id, w.new_id)
    assert preview.conflicts == []
    async with maker() as session:
        result = await PrincipalMergeService(session).merge(w.old_id, w.new_id, actor=ADMIN_SUB)
    counts = _areas(result)
    assert counts["notifications"] == {"rewritten": 0, "combined": 1, "removed": 0}
    assert counts["roles"]["combined"] == 1
    assert counts["attendance"] == {"rewritten": 0, "combined": 1, "removed": 0}
    # Self entry + the same substitute for `other` + the member entry for `other`
    # + the faculty group member row.
    assert counts["substitutes"]["combined"] == 4
    assert counts["substitutes"]["rewritten"] >= 1
    assert _areas(preview)["substitutes"]["combined"] == 4

    async with maker() as session:
        prefs = (
            await session.scalars(
                select(NotificationPreference).where(
                    NotificationPreference.principal_id == w.new_id
                )
            )
        ).all()
        assert [(p.kind, p.enabled) for p in prefs] == [("comment", True)]
        att = (
            await session.scalars(
                select(MeetingAttendance).where(MeetingAttendance.meeting_id == w.meeting_id)
            )
        ).all()
        assert [(a.principal_id, a.source) for a in att] == [(w.new_id, "lead")]
        pool = (
            await session.execute(
                select(
                    DelegationSubstitute.member_principal_id,
                    DelegationSubstitute.substitute_principal_id,
                ).where(DelegationSubstitute.gremium_id == w.gremium_id)
            )
        ).all()
        assert sorted(pool, key=str) == sorted(
            [(w.other_id, w.new_id), (None, w.new_id), (w.new_id, w.other_id)], key=str
        )
        assert w.old_id not in {m for row in pool for m in row}
        members = (
            await session.execute(
                select(SubstituteGroupMember.principal_id, SubstituteGroupMember.group_id).where(
                    SubstituteGroupMember.gremium_id == w.gremium_id
                )
            )
        ).all()
        assert members == [(w.new_id, second_group.id)]


async def test_legacy_self_absent_attendance_becomes_a_lead_entry(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    w = await _seed(maker)
    async with maker() as session:
        # Write a row from before Z2: the NOT VALID check refuses it today.
        await session.execute(
            text(
                "ALTER TABLE meeting_attendance "
                "DROP CONSTRAINT ck_meeting_attendance_self_status"
            )
        )
        await session.execute(
            text(
                "INSERT INTO meeting_attendance (id, meeting_id, principal_id, status, source) "
                "VALUES (gen_random_uuid(), :m, :p, 'absent', 'self')"
            ),
            {"m": w.second_meeting_id, "p": w.old_id},
        )
        await session.execute(
            text(
                "ALTER TABLE meeting_attendance ADD CONSTRAINT "
                "ck_meeting_attendance_self_status "
                "CHECK (source <> 'self' OR status IN ('present','excused')) NOT VALID"
            )
        )
        await session.commit()
    async with maker() as session:
        await PrincipalMergeService(session).merge(w.old_id, w.new_id, actor=ADMIN_SUB)
    async with maker() as session:
        rows = (
            await session.execute(
                select(MeetingAttendance.status, MeetingAttendance.source).where(
                    MeetingAttendance.meeting_id == w.second_meeting_id,
                    MeetingAttendance.principal_id == w.new_id,
                )
            )
        ).all()
    assert rows == [("absent", "lead")]


async def _add(maker: async_sessionmaker[AsyncSession], *rows: object) -> None:
    async with maker() as session:
        session.add_all(list(rows))
        await session.commit()


async def _conflict_world(
    maker: async_sessionmaker[AsyncSession], kind: str
) -> tuple[World, str | None]:
    w = await _seed(maker)
    meeting_title: str | None = None
    async with maker() as session:
        meeting = await session.get(Meeting, w.second_meeting_id)
        assert meeting is not None
        meeting_title = meeting.title
    if kind == "ballot_open":
        await _add(maker, Ballot(vote_id=w.open_vote_id, voter_sub=w.new_sub, choice="no"))
        return w, "Offene Frage"
    if kind == "ballot_secret":
        await _add(maker, VotedMarker(vote_id=w.secret_vote_id, voter_sub=w.new_sub))
        return w, "Geheime Frage"
    if kind == "delegation_same_meeting":
        await _add(
            maker,
            MeetingDelegation(
                meeting_id=w.second_meeting_id,
                gremium_id=w.gremium_id,
                delegator_principal_id=w.new_id,
                delegate_principal_id=w.other_id,
            ),
        )
        return w, meeting_title
    if kind == "delegation_vote_twice":
        async with maker() as session:
            third = PrincipalRow(sub=f"third-{_tag()}", display_name="Dritte")
            fourth = PrincipalRow(sub=f"fourth-{_tag()}", display_name="Vierte")
            session.add_all([third, fourth])
            await session.flush()
            async with maker() as _:
                pass
            for delegator, delegate in ((third.id, w.old_id), (fourth.id, w.new_id)):
                session.add(
                    MeetingDelegation(
                        meeting_id=w.meeting_id,
                        gremium_id=w.gremium_id,
                        delegator_principal_id=delegator,
                        delegate_principal_id=delegate,
                        delegate_voting=True,
                    )
                )
            await session.commit()
        async with maker() as session:
            meeting = await session.get(Meeting, w.meeting_id)
            assert meeting is not None
            return w, meeting.title
    if kind == "delegation_chain":
        # The third person delegated to the new account in meeting B, where the old
        # account is a delegator.
        async with maker() as session:
            third = PrincipalRow(sub=f"third-{_tag()}", display_name="Dritte")
            session.add(third)
            await session.flush()
            session.add(
                MeetingDelegation(
                    meeting_id=w.second_meeting_id,
                    gremium_id=w.gremium_id,
                    delegator_principal_id=third.id,
                    delegate_principal_id=w.new_id,
                )
            )
            await session.commit()
        return w, meeting_title
    if kind == "delegation_to_each_other":
        await _add(
            maker,
            MeetingDelegation(
                meeting_id=w.meeting_id,
                gremium_id=w.gremium_id,
                delegator_principal_id=w.new_id,
                delegate_principal_id=w.old_id,
            ),
        )
        async with maker() as session:
            meeting = await session.get(Meeting, w.meeting_id)
            assert meeting is not None
            return w, meeting.title
    if kind == "attendance_differs":
        await _add(
            maker,
            MeetingAttendance(
                meeting_id=w.meeting_id, principal_id=w.new_id, status="excused", source="self"
            ),
        )
        async with maker() as session:
            meeting = await session.get(Meeting, w.meeting_id)
            assert meeting is not None
            return w, meeting.title
    assert kind == "erasure_open"
    await _add(maker, ErasureRequest(subject_type="principal", principal_id=w.new_id))
    return w, None


_CONFLICTS = {
    "ballot_open": "ballot_same_vote",
    "ballot_secret": "ballot_same_vote",
    "delegation_same_meeting": "delegation_same_meeting",
    "delegation_vote_twice": "delegation_vote_twice",
    "delegation_chain": "delegation_chain",
    "delegation_to_each_other": "delegation_chain",
    "attendance_differs": "attendance_differs",
    "erasure_open": "erasure_open",
}


@pytest.mark.parametrize("case", sorted(_CONFLICTS))
async def test_each_conflict_blocks_the_merge(
    maker: async_sessionmaker[AsyncSession], case: str
) -> None:
    w, label = await _conflict_world(maker, case)
    kind = _CONFLICTS[case]
    async with maker() as session:
        preview = await PrincipalMergeService(session).preview(w.old_id, w.new_id)
    assert preview.can_merge is False
    assert [(c.kind, c.label) for c in preview.conflicts] == [(kind, label)]

    async with maker() as session:
        with pytest.raises(ConflictError) as exc:
            await PrincipalMergeService(session).merge(w.old_id, w.new_id, actor=ADMIN_SUB)
    assert exc.value.code == "merge_conflict"
    assert exc.value.errors is not None
    assert [(e.field, e.msg) for e in exc.value.errors] == [(kind, label or "")]

    # Nothing changed.
    async with maker() as session:
        old = await session.get(PrincipalRow, w.old_id)
        assert old is not None and old.merged_into is None and old.active is True
        assert await _count(session, Application.created_by, w.old_sub) == 1
        assert await _count(session, AuthSession.principal_id, w.old_id) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEntry)
                .where(AuditEntry.action == "principal_merge")
            )
            == 0
        )


async def test_failure_inside_the_merge_rolls_back_everything(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await _seed(maker)

    async def boom(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("sync failed")

    monkeypatch.setattr(merge_mod, "sync_principal_memberships", boom)
    async with maker() as session:
        with pytest.raises(RuntimeError):
            await PrincipalMergeService(session).merge(w.old_id, w.new_id, actor=ADMIN_SUB)
    async with maker() as session:
        old = await session.get(PrincipalRow, w.old_id)
        assert old is not None and old.merged_into is None and old.active is True
        for column in SUB_REFS:
            assert await _count(session, column, w.new_sub) == 0, str(column)
        assert await _count(session, AuthSession.principal_id, w.old_id) == 1
        assert await _count(session, Ballot.voter_sub, w.old_sub) == 1


async def test_a_clash_written_during_the_merge_gives_409(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ballot cast after the conflict check makes the unique key fail: 409, no write."""
    w = await _seed(maker)

    async def no_conflicts(*_args: object, **_kwargs: object) -> list[object]:
        return []

    await _add(maker, Ballot(vote_id=w.open_vote_id, voter_sub=w.new_sub, choice="no"))
    monkeypatch.setattr(PrincipalMergeService, "_conflicts", no_conflicts)
    async with maker() as session:
        with pytest.raises(ConflictError) as exc:
            await PrincipalMergeService(session).merge(w.old_id, w.new_id, actor=ADMIN_SUB)
    assert exc.value.code == "merge_conflict"
    async with maker() as session:
        old = await session.get(PrincipalRow, w.old_id)
        assert old is not None and old.merged_into is None


async def test_preconditions(maker: async_sessionmaker[AsyncSession]) -> None:
    w = await _seed(maker)
    async with maker() as session:
        svc = PrincipalMergeService(session)
        with pytest.raises(ValidationProblem) as same:
            await svc.preview(w.old_id, w.old_id)
        assert same.value.code == "merge_same_principal"
        with pytest.raises(NotFoundError):
            await svc.preview(uuid.uuid4(), w.new_id)
        with pytest.raises(NotFoundError):
            await svc.preview(w.old_id, uuid.uuid4())
    async with maker() as session:
        with pytest.raises(ConflictError) as own:
            await PrincipalMergeService(session).merge(w.old_id, w.new_id, actor=w.old_sub)
        assert own.value.code == "merge_own_account"
    async with maker() as session:
        await PrincipalMergeService(session).merge(w.old_id, w.new_id, actor=ADMIN_SUB)
    async with maker() as session:
        svc = PrincipalMergeService(session)
        with pytest.raises(ConflictError) as again:
            await svc.preview(w.old_id, w.other_id)
        assert again.value.code == "principal_already_merged"
        with pytest.raises(ConflictError) as target:
            await svc.preview(w.other_id, w.old_id)
        assert target.value.code == "merge_target_merged"


async def test_earlier_merges_move_on_to_the_new_target(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    w = await _seed(maker)
    async with maker() as session:
        older = PrincipalRow(sub=f"older-{_tag()}", display_name="Ganz Alt")
        session.add(older)
        await session.commit()
        older_id = older.id
    # An even older account was merged into the old account before.
    async with maker() as session:
        await PrincipalMergeService(session).merge(older_id, w.old_id, actor=ADMIN_SUB)
    async with maker() as session:
        await PrincipalMergeService(session).merge(w.old_id, w.new_id, actor=ADMIN_SUB)
    async with maker() as session:
        older_row = await session.get(PrincipalRow, older_id)
        assert older_row is not None and older_row.merged_into == w.new_id
        names = await AuditService(session).resolve_actor_names([older_row.sub])
        assert names == {older_row.sub: NEW_NAME}


async def test_old_sub_cannot_log_in(maker: async_sessionmaker[AsyncSession]) -> None:
    w = await _seed(maker)
    async with maker() as session:
        await PrincipalMergeService(session).merge(w.old_id, w.new_id, actor=ADMIN_SUB)
    claims = oidc.OidcClaims(
        sub=w.old_sub, email="changed@example.org", name="Changed", groups=["stupa"]
    )
    async with maker() as session:
        with pytest.raises(ForbiddenError) as exc:
            await upsert_principal(session, claims)
        assert exc.value.code == "account_merged"
    async with maker() as session:
        old = await session.get(PrincipalRow, w.old_id)
        assert old is not None
        # The refused login changed nothing.
        assert old.display_name == OLD_NAME
        assert old.oidc_groups == []
        assert old.last_login is None


def _api(
    migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch, principal: Principal
) -> FastAPI:
    from app.deps import get_current_principal

    api = build_api(migrated[1], guest_settings(migrated[1]), monkeypatch)
    api.dependency_overrides[get_current_principal] = lambda: principal
    return api


_MERGE_ADMIN = Principal(
    sub=ADMIN_SUB,
    roles=[],
    permissions={"admin.users", "admin.users.merge", "audit.read", "application.read_all"},
)


async def test_routes_and_display_follow_the_merge(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = await _seed(maker)
    api = _api(migrated, monkeypatch, _MERGE_ADMIN)
    with TestClient(api) as client:
        got = client.get(
            f"/api/admin/principals/{w.old_id}/merge-preview", params={"targetId": str(w.new_id)}
        )
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["canMerge"] is True
        assert body["source"]["displayName"] == OLD_NAME
        assert {a["area"] for a in body["areas"]} == set(merge_mod.AREAS)

        done = client.post(
            f"/api/admin/principals/{w.old_id}/merge", json={"targetId": str(w.new_id)}
        )
        assert done.status_code == 200, done.text
        assert done.json()["mergedAt"]
        assert _areas(done.json()) == _areas(body)

        again = client.post(
            f"/api/admin/principals/{w.old_id}/merge", json={"targetId": str(w.new_id)}
        )
        assert again.status_code == 409
        assert again.json()["code"] == "principal_already_merged"
        assert again.headers["content-type"].startswith("application/problem+json")

        # The user list marks the old account.
        users = client.get("/api/admin/principals", params={"q": OLD_NAME}).json()
        old_row = next(u for u in users if u["id"] == str(w.old_id))
        assert old_row["mergedIntoId"] == str(w.new_id)
        assert old_row["mergedIntoName"] == NEW_NAME
        assert old_row["mergedAt"]
        assert old_row["active"] is False

        # A merged account cannot be activated again.
        react = client.patch(f"/api/admin/principals/{w.old_id}", json={"active": True})
        assert react.status_code == 409
        assert react.json()["code"] == "principal_merged"

    # Rows that still hold the old sub (the audit log, and here a comment written
    # with the old sub after the merge) show the new name.
    async with maker() as session:
        session.add(
            Comment(
                application_id=w.app_id,
                author=w.old_sub,
                author_kind="principal",
                body="spät",
                visibility="internal",
            )
        )
        session.add(
            StatusEvent(
                application_id=w.app_id, to_state_id=w.seed.pruefung_id, actor=w.old_sub
            )
        )
        session.add(
            SubmissionVersion(
                application_id=w.app_id, version=50, data={}, changed_by=w.old_sub
            )
        )
        await session.commit()

    with TestClient(api) as client:
        comments = client.get(f"/api/applications/{w.app_id}/comments").json()
        assert {c["authorInfo"]["displayName"] for c in comments} == {NEW_NAME}
        assert {c["authorInfo"]["principalId"] for c in comments} == {str(w.new_id)}
        timeline = client.get(f"/api/applications/{w.app_id}/timeline").json()
        names = {e["actorInfo"]["displayName"] for e in timeline if e["actorInfo"]}
        assert names == {NEW_NAME}
        versions = client.get(f"/api/applications/{w.app_id}/versions").json()
        assert OLD_NAME not in str(versions)
        assert NEW_NAME in str(versions)

        audit = client.get("/api/admin/audit").json()["items"]
        login = next(e for e in audit if e["action"] == "login")
        assert login["actor"] == w.old_sub
        assert login["actorName"] == NEW_NAME
        assert login["targetLabel"] == NEW_NAME
        merge_row = next(e for e in audit if e["action"] == "principal_merge")
        assert merge_row["actor"] == ADMIN_SUB
        actors = client.get("/api/admin/audit/actors").json()
        assert {"sub": w.old_sub, "name": NEW_NAME} in actors


@pytest.mark.parametrize(
    "permissions", [set(), {"admin.users"}, {"admin.users", "audit.read"}]
)
async def test_routes_need_the_merge_permission(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    permissions: set[str],
) -> None:
    w = await _seed(maker)
    api = _api(migrated, monkeypatch, Principal(sub="someone", permissions=permissions))
    with TestClient(api) as client:
        got = client.get(
            f"/api/admin/principals/{w.old_id}/merge-preview", params={"targetId": str(w.new_id)}
        )
        assert got.status_code == 403
        done = client.post(
            f"/api/admin/principals/{w.old_id}/merge", json={"targetId": str(w.new_id)}
        )
        assert done.status_code == 403
    async with maker() as session:
        old = await session.get(PrincipalRow, w.old_id)
        assert old is not None and old.merged_into is None


async def test_an_agent_token_cannot_merge(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No OAuth scope carries `admin.users.merge`, also not for an admin."""
    from app.modules.auth.oauth import SCOPES, scope_permissions

    w = await _seed(maker)
    token = Principal(
        sub=ADMIN_SUB,
        roles=["admin"],
        scope_permissions=scope_permissions(list(SCOPES)),
    )
    api = _api(migrated, monkeypatch, token)
    with TestClient(api) as client:
        done = client.post(
            f"/api/admin/principals/{w.old_id}/merge", json={"targetId": str(w.new_id)}
        )
        assert done.status_code == 403


async def test_merge_conflict_is_problem_json(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w, label = await _conflict_world(maker, "ballot_open")
    api = _api(migrated, monkeypatch, _MERGE_ADMIN)
    with TestClient(api) as client:
        done = client.post(
            f"/api/admin/principals/{w.old_id}/merge", json={"targetId": str(w.new_id)}
        )
    assert done.status_code == 409
    assert done.headers["content-type"].startswith("application/problem+json")
    body = done.json()
    assert body["code"] == "merge_conflict"
    assert body["errors"] == [{"field": "ballot_same_vote", "msg": label}]


async def test_merged_principal_gets_no_membership_and_no_bootstrap_admin(
    migrated: tuple[str, str], maker: async_sessionmaker[AsyncSession]
) -> None:
    from app.modules.admin.membership_sync import sync_all_memberships
    from app.modules.admin.models import GremiumMembershipMapping
    from app.modules.auth.bootstrap import ensure_bootstrap_admins
    from app.settings import load_settings

    w = await _seed(maker)
    async with maker() as session:
        await PrincipalMergeService(session).merge(w.old_id, w.new_id, actor=ADMIN_SUB)
    group = f"grp-{_tag()}"
    async with maker() as session:
        old = await session.get(PrincipalRow, w.old_id)
        assert old is not None
        old.oidc_groups = [group]
        session.add(GremiumMembershipMapping(oidc_group=group, gremium_id=w.gremium_id))
        await session.commit()
    async with maker() as session:
        await sync_all_memberships(session)
        settings = load_settings(
            database_url=migrated[1],
            session_secret="session-secret-merge-test-000000",
            magic_link_secret="magic-link-secret-merge-test-00",
            bootstrap_admin_subjects=w.old_sub,
        )
        granted = await ensure_bootstrap_admins(session, settings)
        await session.commit()
        assert granted == 0
        assert await _count(session, GremiumMembership.principal_id, w.old_id) == 0
        # The mapping table is not cleared between tests.
        await session.execute(
            text("DELETE FROM gremium_membership_mapping WHERE oidc_group = :g"), {"g": group}
        )
        await session.commit()
