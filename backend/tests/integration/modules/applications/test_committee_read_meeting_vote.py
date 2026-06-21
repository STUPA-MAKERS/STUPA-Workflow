"""Integration (echte Postgres, testcontainers): Gremium-Lesescope, Bestand-Pfad (#vote-read).

Regression für #AUD-033: ``access._committee_can_read`` (Detail) und
``ApplicationsService._committee_read_clauses`` (Liste) MÜSSEN dieselben Pfade
abdecken. Der historische Sitzungs-Vote-Pfad (»in einer Sitzung eines Mitglieds-
Gremiums abgestimmt«, ``vote → meeting.gremium_id``) war in der Detailprüfung
vorhanden, fehlte aber in der Listen-Query — ein Antrag, den ein Mitglied per
Direkt-URL öffnen durfte, tauchte nie in seiner ``GET /applications``-Liste auf.

Dieser Test beweist gegen ein echtes Schema, dass beide Pfade den per Sitzungs-Vote
zugeordneten Antrag jetzt zeigen, und dass Anträge fremder Gremien in beiden
verborgen bleiben.

Test-Isolation analog ``test_committee_read_scope``: ``budget``/``principal``/
``gremium`` werden NICHT trunkiert → eindeutige Schlüssel tragen ein pro Seed frisches
Token.
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
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.livevote.models import Meeting
from app.modules.voting.models import Vote
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
    member_sub: str
    other_sub: str
    app_voted_member: uuid.UUID
    app_voted_other: uuid.UUID
    app_unrelated: uuid.UUID


async def _seed(session: AsyncSession) -> _Scenario:
    sc = _Scenario()
    tag = uuid.uuid4().hex[:8]
    sc.member_sub = f"member-{tag}"
    sc.other_sub = f"other-{tag}"

    # Zwei Gremien; der/die Nutzer:in ist NUR im ersten Mitglied.
    g_member = Gremium(name="Mitglied", slug=f"m-{tag}")
    g_other = Gremium(name="Fremd", slug=f"o-{tag}")
    session.add_all([g_member, g_other])
    await session.flush()

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

    app_type = ApplicationType(
        gremium_id=g_member.id, key=f"t-{tag}", name_i18n={}, has_budget=True
    )
    session.add(app_type)
    await session.commit()
    await FormsService(session).create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True), "tester"
    )

    # Minimaler Flow (genau ein aktiver globaler) — die Anträge bleiben im Initial-State,
    # der KEIN vote-State ist: der Lesescope kommt hier ALLEIN aus dem Sitzungs-Vote.
    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    draft = State(
        flow_version_id=flow.id, key="draft", label_i18n={"de": "Entwurf"}, is_initial=True
    )
    session.add(draft)
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

    app_voted_member, _ = await svc.create(_payload(), actor=sc.other_sub)
    app_voted_other, _ = await svc.create(_payload(), actor=sc.other_sub)
    app_unrelated, _ = await svc.create(_payload(), actor=sc.other_sub)

    # Sitzungen je Gremium + abgeschlossene Anträgs-Votes (Bestand).
    meet_member = Meeting(gremium_id=g_member.id, title="Sitzung Mitglied", status="closed")
    meet_other = Meeting(gremium_id=g_other.id, title="Sitzung Fremd", status="closed")
    session.add_all([meet_member, meet_other])
    await session.flush()
    session.add_all(
        [
            Vote(
                application_id=app_voted_member.id,
                meeting_id=meet_member.id,
                eligible_group="member",
                config={},
                status="closed",
                result="passed",
            ),
            Vote(
                application_id=app_voted_other.id,
                meeting_id=meet_other.id,
                eligible_group="member",
                config={},
                status="closed",
                result="passed",
            ),
        ]
    )
    await session.commit()

    sc.app_voted_member = app_voted_member.id
    sc.app_voted_other = app_voted_other.id
    sc.app_unrelated = app_unrelated.id
    return sc


async def test_list_includes_historical_meeting_vote(session: AsyncSession) -> None:
    sc = await _seed(session)
    svc = ApplicationsService(session)

    page = await svc.list_applications(
        owner_sub=sc.member_sub, committee_sub=sc.member_sub, limit=50, offset=0
    )
    got = {i.id for i in page.items}
    # In einer Mitglieds-Sitzung abgestimmt → sichtbar.
    assert sc.app_voted_member in got
    # Fremde Sitzung + unbeteiligter Antrag → verborgen.
    assert sc.app_voted_other not in got
    assert sc.app_unrelated not in got


async def test_detail_and_list_agree_on_meeting_vote(session: AsyncSession) -> None:
    sc = await _seed(session)
    member = Principal(sub=sc.member_sub, permissions=set())  # KEIN application.read

    # Detail erlaubt den per Mitglieds-Sitzung abgestimmten Antrag …
    access = await require_app_read(sc.app_voted_member, session, member, None)
    assert access.principal is not None and access.actor == sc.member_sub
    # … und verweigert die Fremd-Sitzung / den unbeteiligten Antrag.
    for app_id in (sc.app_voted_other, sc.app_unrelated):
        with pytest.raises(ForbiddenError):
            await require_app_read(app_id, session, member, None)
