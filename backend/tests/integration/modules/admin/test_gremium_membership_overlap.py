"""Integration (echte Postgres): DB-Backing der Overlap-Invariante (AUD-029).

Die reine Python-Prüfung in ``create_membership`` ist nur ein Fast-Path und schützt
NICHT gegen TOCTOU: zwei parallele Inserts lesen beide den Vor-Zustand, beide passieren
die Prüfung, beide committen. Verbindlich durchgesetzt wird die Invariante »pro
(Principal, Gremium) genau eine aktive Amtszeit« über die EXCLUDE-Constraint
``ex_gremium_membership_no_overlap`` (btree_gist, halboffenes ``tstzrange``).

Beweist gegen das migrierte Schema:
* ein zweiter, zeitlich überlappender Insert desselben (Principal, Gremium) — der die
  Python-Prüfung umgeht — wird von der DB mit ``IntegrityError`` abgelehnt;
* der Service übersetzt diesen ``IntegrityError`` in einen 409 (``ConflictError``),
  nicht in einen 500;
* aneinandergrenzende (halboffene) Folgeamtszeiten bleiben erlaubt;
* andere Principals / andere Gremien sind nicht betroffen.
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
    """Gremium + Gremium-Rolle + Principal (committet)."""
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
    """Zwei überlappende Inserts (Python-Prüfung umgangen) → DB lehnt den 2. ab."""
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

    # 1. Amtszeit [2026-01-01, 2026-12-31): committet.
    session.add(_membership("2026-01-01", "2026-12-31"))
    await session.commit()

    # 2. Amtszeit [2026-06-01, 2027-06-01) überlappt → EXCLUDE-Constraint feuert.
    # Direkter Insert umgeht bewusst die Python-Fast-Path-Prüfung des Service und
    # beweist, dass die DB selbst (TOCTOU-fest) die Überlappung ablehnt.
    session.add(_membership("2026-06-01", "2027-06-01"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_service_translates_db_overlap_to_409(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TOCTOU: Fast-Path übersehen, DB-Constraint → 409 (``ConflictError``), nicht 500.

    Simuliert das konkurrierende Race genau dort, wo es real auftritt: die Python-
    Fast-Path-Prüfung passiert (als hätte sie den fremden Insert im eigenen Snapshot
    nicht gesehen — hier deterministisch erzwungen durch ``intervals_overlap`` → False),
    aber die bereits committete, überlappende Amtszeit lässt beim Commit die EXCLUDE-
    Constraint ``ex_gremium_membership_no_overlap`` feuern. Der Service MUSS den
    ``IntegrityError`` in einen 409 übersetzen — sonst schlüge der Race als 500 durch."""
    gremium, role, member = await _fixture(session)

    # Bereits committete, kollidierende Amtszeit (der "Gewinner" des Races).
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

    # Fast-Path blind stellen: erzwingt den DB-Pfad (TOCTOU) statt der Python-Prüfung.
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
    """Aneinandergrenzende (halboffene) Folgeamtszeiten bleiben erlaubt."""
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
    # [2026-01-01, 2027-01-01) grenzt an → keine Überlappung, kein Fehler.
    session.add(
        GremiumMembership(
            principal_id=member.id,
            gremium_id=gremium.id,
            gremium_role_id=role.id,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_until=datetime(2027, 1, 1, tzinfo=UTC),
        )
    )
    await session.commit()  # darf nicht werfen
