"""Integration (echte Postgres, testcontainers): Gremium-Lesescope (#committee-read).

Beweist gegen ein echtes Schema, dass ein Gremium-**Mitglied** OHNE globales
``application.read`` zusätzlich zu seinen EIGENEN Anträgen auch jene lesen darf, die

* in einer Kostenstelle (Knoten ODER Vorfahre) mit ``view_gremium_id`` eines seiner
  Gremien liegen (#budget-scope), **oder**
* aktuell in einem ``vote``-State mit ``config.gremiumId`` eines seiner Gremien stehen,

und dass dieselbe Sicht für die Liste (``ApplicationsService.list_applications``) wie
für die Detailansicht (``access.require_app_read``) gilt — und Anträge fremder Gremien
in beiden Pfaden verborgen bleiben.

Test-Isolation: die ``engine``-Fixture trunkiert nur die Antrags-/Flow-Tabellen, NICHT
``budget``/``principal``/``gremium`` — deshalb tragen alle dort eindeutig-beschränkten
Schlüssel (``path_key``, ``principal.sub``, ``slug``) ein pro Seed frisches Token.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import (
    ApplicationType,
    Gremium,
    GremiumMembership,
    GremiumRole,
)
from app.modules.applications.access import require_app_read
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import Budget
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ForbiddenError

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


def _fields() -> list[FormFieldDef]:
    return [
        FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
        FormFieldDef.model_validate(
            {
                "key": "cost",
                "type": "currency",
                "label": {"de": "Kosten"},
                "isPromoted": True,
                "promoteTarget": "amount",
            }
        ),
    ]


class _Scenario:
    """Gesäte Welt für den Lesescope-Test (alle Anträge bestätigt = sichtbar)."""

    member_sub: str
    other_sub: str
    # Anträge:
    app_cost: uuid.UUID
    app_vote: uuid.UUID
    app_own: uuid.UUID
    app_cost_other: uuid.UUID
    app_vote_other: uuid.UUID
    app_unrelated: uuid.UUID


async def _seed(session: AsyncSession) -> _Scenario:
    sc = _Scenario()
    tag = uuid.uuid4().hex[:8]  # frisch je Seed (budget/principal/gremium leaken sonst)
    sc.member_sub = f"member-{tag}"
    sc.other_sub = f"other-{tag}"

    # Zwei Gremien: der/die Nutzer:in ist NUR im ersten Mitglied.
    g_member = Gremium(name="Mitglied", slug=f"m-{tag}")
    g_other = Gremium(name="Fremd", slug=f"o-{tag}")
    session.add_all([g_member, g_other])
    await session.flush()

    # Principal + aktive (unbefristete) Mitgliedschaft im Mitglieds-Gremium.
    principal = PrincipalRow(sub=sc.member_sub, display_name="Mitglied")
    role = GremiumRole(
        gremium_id=g_member.id,
        key="member",
        name_i18n={"de": "Mitglied"},
        permissions=["vote.cast"],
    )
    session.add_all([principal, role])
    await session.flush()
    session.add(
        GremiumMembership(
            principal_id=principal.id,
            gremium_id=g_member.id,
            gremium_role_id=role.id,
            valid_from=None,
            valid_until=None,
        )
    )

    # Antragstyp + aktive Form.
    app_type = ApplicationType(
        gremium_id=g_member.id, key=f"t-{tag}", name_i18n={}, has_budget=True
    )
    session.add(app_type)
    await session.commit()
    await FormsService(session).create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True)
    )

    # Flow: Initial-State + zwei vote-States (für je ein Gremium). ``flow_version`` wird
    # je Test trunkiert → genau EIN aktiver globaler Flow, hier frisch angelegt.
    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    draft = State(
        flow_version_id=flow.id, key="draft", label_i18n={"de": "Entwurf"}, is_initial=True
    )
    vote_member = State(
        flow_version_id=flow.id,
        key="vote-member",
        label_i18n={"de": "Abstimmung (Mitglied)"},
        kind="vote",
        config={"gremiumId": str(g_member.id)},
    )
    vote_other = State(
        flow_version_id=flow.id,
        key="vote-other",
        label_i18n={"de": "Abstimmung (fremd)"},
        kind="vote",
        config={"gremiumId": str(g_other.id)},
    )
    session.add_all([draft, vote_member, vote_other])
    await session.commit()

    # Kostenstellen-Baum: je ein Top-Knoten mit view_gremium_id + ein Leaf darunter.
    # Der Leaf SELBST trägt KEIN view_gremium_id → prüft die Vorfahren-Auflösung.
    top_m = Budget(
        parent_id=None,
        key=f"VSM{tag}",
        path_key=f"VSM{tag}",
        name="Top Mitglied",
        view_gremium_id=g_member.id,
    )
    top_o = Budget(
        parent_id=None,
        key=f"VSO{tag}",
        path_key=f"VSO{tag}",
        name="Top Fremd",
        view_gremium_id=g_other.id,
    )
    session.add_all([top_m, top_o])
    await session.flush()
    leaf_m = Budget(
        parent_id=top_m.id, key="800", path_key=f"VSM{tag}-800", name="Leaf Mitglied"
    )
    leaf_o = Budget(
        parent_id=top_o.id, key="800", path_key=f"VSO{tag}-800", name="Leaf Fremd"
    )
    session.add_all([leaf_m, leaf_o])
    await session.commit()

    svc = ApplicationsService(session)

    def _payload() -> ApplicationCreate:
        return ApplicationCreate.model_validate(
            {
                "typeId": str(app_type.id),
                "data": {"title": "Antrag", "cost": "100.00"},
                "applicantEmail": "x@example.org",
            }
        )

    # actor != "applicant" ⇒ created_by + email_confirmed_at gesetzt (sichtbar).
    app_cost, _ = await svc.create(_payload(), actor=sc.other_sub)
    app_vote, _ = await svc.create(_payload(), actor=sc.other_sub)
    app_own, _ = await svc.create(_payload(), actor=sc.member_sub)
    app_cost_other, _ = await svc.create(_payload(), actor=sc.other_sub)
    app_vote_other, _ = await svc.create(_payload(), actor=sc.other_sub)
    app_unrelated, _ = await svc.create(_payload(), actor=sc.other_sub)

    # Zuordnungen setzen (Kostenstelle / vote-State) — direkt am Modell.
    app_cost.budget_id = leaf_m.id
    app_vote.current_state_id = vote_member.id
    app_cost_other.budget_id = leaf_o.id
    app_vote_other.current_state_id = vote_other.id
    await session.commit()

    sc.app_cost = app_cost.id
    sc.app_vote = app_vote.id
    sc.app_own = app_own.id
    sc.app_cost_other = app_cost_other.id
    sc.app_vote_other = app_vote_other.id
    sc.app_unrelated = app_unrelated.id
    return sc


# --------------------------------------------------------------------------- #
# Liste (Anträge-Tab)
# --------------------------------------------------------------------------- #
async def test_list_committee_scope_unions_owner_costcenter_and_vote(
    session: AsyncSession,
) -> None:
    sc = await _seed(session)
    svc = ApplicationsService(session)

    page = await svc.list_applications(
        owner_sub=sc.member_sub, committee_sub=sc.member_sub, limit=50, offset=0
    )
    got = {i.id for i in page.items}
    # Eigener + Mitglieds-Kostenstelle + Mitglieds-vote-State.
    assert got == {sc.app_own, sc.app_cost, sc.app_vote}
    # Fremde Gremien + unbeteiligter Fremd-Antrag bleiben verborgen.
    assert sc.app_cost_other not in got
    assert sc.app_vote_other not in got
    assert sc.app_unrelated not in got


async def test_list_without_committee_scope_is_owner_only(session: AsyncSession) -> None:
    sc = await _seed(session)
    svc = ApplicationsService(session)

    page = await svc.list_applications(
        owner_sub=sc.member_sub, committee_sub=None, limit=50, offset=0
    )
    assert {i.id for i in page.items} == {sc.app_own}


async def test_list_full_read_sees_all_confirmed(session: AsyncSession) -> None:
    sc = await _seed(session)
    svc = ApplicationsService(session)

    page = await svc.list_applications(owner_sub=None, committee_sub=None, limit=50, offset=0)
    got = {i.id for i in page.items}
    assert {
        sc.app_own,
        sc.app_cost,
        sc.app_vote,
        sc.app_cost_other,
        sc.app_vote_other,
        sc.app_unrelated,
    } <= got


# --------------------------------------------------------------------------- #
# Detailansicht (require_app_read) — gleiche Sicht wie die Liste
# --------------------------------------------------------------------------- #
async def test_detail_guard_grants_committee_scope(session: AsyncSession) -> None:
    sc = await _seed(session)
    member = Principal(sub=sc.member_sub, permissions=set())  # KEIN application.read

    for app_id in (sc.app_own, sc.app_cost, sc.app_vote):
        access = await require_app_read(app_id, session, member, None)
        assert access.principal is not None and access.actor == sc.member_sub


async def test_detail_guard_denies_foreign_gremium(session: AsyncSession) -> None:
    sc = await _seed(session)
    member = Principal(sub=sc.member_sub, permissions=set())

    for app_id in (sc.app_cost_other, sc.app_vote_other, sc.app_unrelated):
        with pytest.raises(ForbiddenError):
            await require_app_read(app_id, session, member, None)
