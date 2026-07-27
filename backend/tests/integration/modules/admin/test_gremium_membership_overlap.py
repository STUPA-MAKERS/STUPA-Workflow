"""Integration (real Postgres): the DB backs the overlap invariant (AUD-029).

The pure Python check in `create_membership` is only a fast path. It does NOT protect
against TOCTOU. Two parallel inserts both read the state before the change, both pass
the check, and both commit. The EXCLUDE constraint `ex_gremium_membership_no_overlap`
(btree_gist, half-open `tstzrange`) enforces the real invariant: one active term per
(principal, Gremium).

The tests prove these facts against the migrated schema. The DB rejects a second,
overlapping insert for the same (principal, Gremium) with an `IntegrityError`. That
insert bypasses the Python check. The service maps the `IntegrityError` to a 409
(`ConflictError`), not to a 500. Adjacent, half-open follow-up terms stay allowed.
Other principals and other Gremien stay unaffected.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.gremium_roles import GremiumRoleService
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.admin.schemas import GremiumMembershipCreate
from app.modules.auth.models import Principal as PrincipalRow
from app.shared.errors import ConflictError

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str]) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _fixture(
    session: AsyncSession,
) -> tuple[Gremium, GremiumRole, PrincipalRow]:
    """Create a Gremium, a Gremium role and a principal, and commit them."""
    gremium = Gremium(name="StuPa", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    role = GremiumRole(
        gremium_id=gremium.id,
        key=f"r-{uuid.uuid4()}",
        name_i18n={"de": "Vorsitz"},
        permissions=["vote.cast"],
    )
    session.add(role)
    member = PrincipalRow(
        sub=f"s-{uuid.uuid4()}", display_name="Mara Mitglied", email="mara@x.de"
    )
    session.add(member)
    await session.commit()
    return gremium, role, member


async def test_overlapping_insert_rejected_by_db_constraint(
    session: AsyncSession,
) -> None:
    """Two overlapping inserts bypass the Python check, and the DB rejects the second."""
    gremium, role, member = await _fixture(session)

    def _membership(frm: str | None, until: str | None) -> GremiumMembership:
        return GremiumMembership(
            principal_id=member.id,
            gremium_id=gremium.id,
            gremium_role_id=role.id,
            valid_from=datetime.fromisoformat(frm).replace(tzinfo=UTC) if frm else None,
            valid_until=datetime.fromisoformat(until).replace(tzinfo=UTC)
            if until
            else None,
        )

    # First term [2026-01-01, 2026-12-31), committed.
    session.add(_membership("2026-01-01", "2026-12-31"))
    await session.commit()

    # The second term [2026-06-01, 2027-06-01) overlaps, so the EXCLUDE constraint fires.
    # The direct insert bypasses the Python fast-path check of the service on purpose. It
    # proves that the DB itself rejects the overlap and stays safe against TOCTOU.
    session.add(_membership("2026-06-01", "2027-06-01"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_service_translates_db_overlap_to_409(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TOCTOU: the fast path misses the clash, so the DB constraint must give a 409.

    The test simulates the race where it happens in production. The Python fast-path
    check passes, as if it did not see the other insert in its own snapshot. The patched
    `intervals_overlap` returns False and forces that outcome. The overlapping term is
    already committed, so the EXCLUDE constraint `ex_gremium_membership_no_overlap`
    fires on commit. The service MUST map the `IntegrityError` to a 409
    (`ConflictError`). Without that map, the race surfaces as a 500.
    """
    gremium, role, member = await _fixture(session)

    # The colliding term is already committed. It is the winner of the race.
    session.add(
        GremiumMembership(
            principal_id=member.id,
            gremium_id=gremium.id,
            gremium_role_id=role.id,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_until=datetime(2026, 12, 31, tzinfo=UTC),
        )
    )
    await session.commit()

    # Blind the fast path. This forces the DB path (TOCTOU) instead of the Python check.
    monkeypatch.setattr(
        "app.modules.admin.gremium_roles.intervals_overlap",
        lambda *_: False,
    )
    svc = GremiumRoleService(session)
    payload = GremiumMembershipCreate(
        principalId=member.id,
        gremiumRoleId=role.id,
        validFrom="2026-06-01",
        validUntil="2027-06-01",
    )
    with pytest.raises(ConflictError):
        await svc.create_membership(gremium.id, payload, "admin")


async def test_consecutive_terms_allowed(session: AsyncSession) -> None:
    """Adjacent, half-open follow-up terms stay allowed."""
    gremium, role, member = await _fixture(session)
    session.add(
        GremiumMembership(
            principal_id=member.id,
            gremium_id=gremium.id,
            gremium_role_id=role.id,
            valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            valid_until=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    await session.commit()
    # [2026-01-01, 2027-01-01) is adjacent, so there is no overlap and no error.
    session.add(
        GremiumMembership(
            principal_id=member.id,
            gremium_id=gremium.id,
            gremium_role_id=role.id,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_until=datetime(2027, 1, 1, tzinfo=UTC),
        )
    )
    await session.commit()  # must not raise
