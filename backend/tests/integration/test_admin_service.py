"""Integration (echte Postgres, testcontainers): Admin-/Config-Service (T-24).

Beweist gegen ein echtes Schema: Flow-Versions-Anlage (Graph→state/transition,
Versionszählung, Aktiv-Eindeutigkeit via partial-unique), gremium/application-type/
role/webhook-CRUD inkl. Konflikte, RBAC-Vertretung (role_assignment/group_mapping)
und den Site-Config-Draft/Activate-Zyklus (#21) — jeweils mit Audit-Eintrag.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.branding import Branding
from app.modules.admin.models import (
    ApplicationType,
    Gremium,
    SiteConfigVersion,
    Webhook,
)
from app.modules.admin.schemas import (
    ApplicationTypeCreate,
    ApplicationTypeUpdate,
    FlowVersionCreate,
    GremiumCreate,
    GremiumUpdate,
    GroupMappingCreate,
    RoleAssignmentCreate,
    RoleCreate,
    RoleUpdate,
    WebhookCreate,
    WebhookUpdate,
)
from app.modules.admin.service import ConfigService
from app.modules.admin.site_config_service import SiteConfigService
from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal, Role
from app.modules.flow.models import FlowVersion, State, Transition
from app.shared.errors import ConflictError, NotFoundError

pytestmark = pytest.mark.integration

_ACTOR = "oidc|admin"


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


@pytest.fixture(autouse=True)
def _clean_admin(migrated: tuple[str, str]) -> Iterator[None]:
    """Admin-Tabellen je Test leeren (über die Kern-Truncation des ``engine``-Fixtures
    hinaus). Rollen-Seeds bleiben; neue Rollen tragen eindeutige Keys."""
    eng = create_engine(migrated[0])
    with eng.begin() as c:
        c.execute(
            text(
                "TRUNCATE webhook, webhook_delivery, role_assignment, group_mapping, "
                "site_config_version RESTART IDENTITY CASCADE"
            )
        )
    eng.dispose()
    yield


async def _make_type(session: AsyncSession) -> ApplicationType:
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{uuid.uuid4()}", name_i18n={"de": "Antrag"}
    )
    session.add(app_type)
    await session.commit()
    return app_type


def _graph(*, with_action: bool = True) -> dict:
    return {
        "states": [
            {"key": "draft", "label": {"de": "Entwurf"}, "isInitial": True, "category": "open"},
            {"key": "review", "label": {"de": "Prüfung"}, "category": "running"},
        ],
        "transitions": [
            {
                "from": "draft",
                "to": "review",
                "label": {"de": "Einreichen"},
                "guard": {"fieldsComplete": True},
                "actions": ([{"type": "notify", "event": "status_changed"}] if with_action else []),
            }
        ],
    }


# --------------------------------------------------------------- flow-versions
async def test_create_flow_version_persists_graph_and_activates(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = ConfigService(session)
    out = await svc.create_flow_version(
        app_type.id, FlowVersionCreate.model_validate({"graph": _graph()}), _ACTOR
    )
    assert out.version == 1 and out.active is True

    states = (
        await session.scalars(select(State).where(State.flow_version_id == out.id))
    ).all()
    assert {s.key for s in states} == {"draft", "review"}
    initial = [s for s in states if s.is_initial]
    assert len(initial) == 1 and initial[0].key == "draft"

    trans = (
        await session.scalars(
            select(Transition).where(Transition.flow_version_id == out.id)
        )
    ).all()
    assert len(trans) == 1
    by_key = {s.id: s.key for s in states}
    assert by_key[trans[0].from_state_id] == "draft"
    assert by_key[trans[0].to_state_id] == "review"
    assert trans[0].guard == {"fieldsComplete": True}

    refreshed = await session.get(ApplicationType, app_type.id)
    assert refreshed is not None and refreshed.active_flow_version_id == out.id

    # Audit-Eintrag (Aktivierung).
    actions = (
        await session.scalars(
            select(AuditEntry.action).where(AuditEntry.target_type == "flow_version")
        )
    ).all()
    assert "config_activation" in actions


async def test_flow_version_bump_keeps_single_active(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = ConfigService(session)
    v1 = await svc.create_flow_version(
        app_type.id, FlowVersionCreate.model_validate({"graph": _graph()}), _ACTOR
    )
    v2 = await svc.create_flow_version(
        app_type.id, FlowVersionCreate.model_validate({"graph": _graph(with_action=False)}), _ACTOR
    )
    assert v2.version == 2

    active = (
        await session.scalars(
            select(FlowVersion).where(
                FlowVersion.application_type_id == app_type.id,
                FlowVersion.active.is_(True),
            )
        )
    ).all()
    assert len(active) == 1 and active[0].id == v2.id
    old = await session.get(FlowVersion, v1.id)
    assert old is not None and old.active is False


async def test_create_flow_version_unknown_type_404(session: AsyncSession) -> None:
    svc = ConfigService(session)
    with pytest.raises(NotFoundError):
        await svc.create_flow_version(
            uuid.uuid4(), FlowVersionCreate.model_validate({"graph": _graph()}), _ACTOR
        )


# --------------------------------------------------------------- gremium
async def test_gremium_crud_and_slug_conflict(session: AsyncSession) -> None:
    svc = ConfigService(session)
    slug = f"asta-{uuid.uuid4().hex[:8]}"
    created = await svc.create_gremium(
        GremiumCreate(name="AStA", slug=slug, cdVariant="asta"), _ACTOR
    )
    assert created.cd_variant == "asta"
    with pytest.raises(ConflictError):
        await svc.create_gremium(GremiumCreate(name="Dup", slug=slug), _ACTOR)
    updated = await svc.update_gremium(
        created.id, GremiumUpdate(name="AStA neu"), _ACTOR
    )
    assert updated.name == "AStA neu"


# --------------------------------------------------------------- application-type
async def test_application_type_crud_and_conflict(session: AsyncSession) -> None:
    svc = ConfigService(session)
    key = f"grant-{uuid.uuid4().hex[:8]}"
    created = await svc.create_application_type(
        ApplicationTypeCreate.model_validate(
            {
                "key": key,
                "nameI18n": {"de": "Förderantrag"},
                "hasBudget": True,
                "comparisonOffers": {"required": True, "minCount": 3},
            }
        ),
        _ACTOR,
    )
    assert created.has_budget is True
    assert created.comparison_offers is not None and created.comparison_offers["minCount"] == 3
    with pytest.raises(ConflictError):
        await svc.create_application_type(
            ApplicationTypeCreate.model_validate({"key": key, "nameI18n": {"de": "X"}}), _ACTOR
        )
    updated = await svc.update_application_type(
        created.id, ApplicationTypeUpdate(hasBudget=False), _ACTOR
    )
    assert updated.has_budget is False


# --------------------------------------------------------------- roles / rbac
async def test_role_crud_and_listing(session: AsyncSession) -> None:
    svc = ConfigService(session)
    key = f"role-{uuid.uuid4().hex[:8]}"
    created = await svc.create_role(
        RoleCreate(key=key, label={"de": "Sonderrolle"}, permissions=["vote.cast", "audit.read"]),
        _ACTOR,
    )
    assert set(created.permissions) == {"vote.cast", "audit.read"}
    with pytest.raises(ConflictError):
        await svc.create_role(RoleCreate(key=key), _ACTOR)
    updated = await svc.update_role(created.id, RoleUpdate(permissions=["budget.manage"]), _ACTOR)
    assert updated.permissions == ["budget.manage"]
    listed = await svc.list_roles()
    keys = {r.key for r in listed}
    assert key in keys and "admin" in keys  # neue + geseedete Rollen


async def test_role_assignment_and_group_mapping(session: AsyncSession) -> None:
    svc = ConfigService(session)
    principal = Principal(sub=f"u-{uuid.uuid4()}", email=None, display_name="U")
    session.add(principal)
    await session.flush()
    role = (await session.scalars(select(Role).where(Role.key == "member"))).first()
    assert role is not None

    assignment = await svc.create_role_assignment(
        RoleAssignmentCreate.model_validate(
            {
                "principalId": str(principal.id),
                "roleId": str(role.id),
                "delegateVoting": True,
                "validUntil": "2026-12-31T23:59:00+00:00",
            }
        ),
        _ACTOR,
    )
    assert assignment.delegate_voting is True
    assert assignment.granted_by == _ACTOR
    assert assignment.valid_until is not None

    # unbekannter Principal → 404
    with pytest.raises(NotFoundError):
        await svc.create_role_assignment(
            RoleAssignmentCreate.model_validate(
                {"principalId": str(uuid.uuid4()), "roleId": str(role.id)}
            ),
            _ACTOR,
        )

    mapping = await svc.create_group_mapping(
        GroupMappingCreate.model_validate({"oidcGroup": "fsr-info", "roleId": str(role.id)}),
        _ACTOR,
    )
    assert mapping.oidc_group == "fsr-info"
    assert len(await svc.list_role_assignments()) == 1
    assert len(await svc.list_group_mappings()) == 1


# --------------------------------------------------------------- webhooks
async def test_webhook_crud_secret_not_exposed(session: AsyncSession, engine: Engine) -> None:
    svc = ConfigService(session)
    created = await svc.create_webhook(
        WebhookCreate.model_validate(
            {
                "name": "n8n",
                "url": "https://hooks.x/abc",
                "events": ["status_changed", "vote_closed"],
            }
        ),
        _ACTOR,
    )
    assert created.active is True and "secret" not in created.model_dump()

    # secret wurde serverseitig erzeugt (DB-Spalte), aber nie ausgeliefert.
    row = await session.get(Webhook, created.id)
    assert row is not None and row.secret is not None and len(row.secret) == 32

    updated = await svc.update_webhook(created.id, WebhookUpdate(active=False), _ACTOR)
    assert updated.active is False
    assert len(await svc.list_webhooks()) == 1
    with pytest.raises(NotFoundError):
        await svc.update_webhook(uuid.uuid4(), WebhookUpdate(active=True), _ACTOR)


# --------------------------------------------------------------- site-config
async def test_site_config_draft_activate_cycle(session: AsyncSession) -> None:
    svc = SiteConfigService(session)
    empty = await svc.get()
    assert empty.version == 0 and empty.has_draft_changes is False

    b1 = Branding.model_validate({"copyright": {"de": "© 2026 StuPa"}})
    after_draft = await svc.put_draft(b1, _ACTOR)
    assert after_draft.has_draft_changes is True
    assert after_draft.version == 0  # noch nicht aktiviert

    activated = await svc.activate(_ACTOR)
    assert activated.version == 1 and activated.has_draft_changes is False
    assert activated.active.copyright == {"de": "© 2026 StuPa"}

    # zweiter Draft oberhalb der aktiven Version
    b2 = Branding.model_validate({"copyright": {"de": "© 2027"}})
    await svc.put_draft(b2, _ACTOR)
    mid = await svc.get()
    assert mid.version == 1 and mid.has_draft_changes is True
    assert mid.active.copyright == {"de": "© 2026 StuPa"}
    assert mid.draft.copyright == {"de": "© 2027"}

    final = await svc.activate(_ACTOR)
    assert final.version == 2

    pub = await svc.public()
    assert pub.version == 2 and pub.branding.copyright == {"de": "© 2027"}

    # genau eine aktive Version (partial-unique)
    actives = (
        await session.scalars(
            select(func.count())
            .select_from(SiteConfigVersion)
            .where(SiteConfigVersion.active.is_(True))
        )
    ).all()
    assert actives[0] == 1

    # Aktivierung ohne offenen Draft → Conflict
    with pytest.raises(ConflictError):
        await svc.activate(_ACTOR)

    # Audit: Aktivierung protokolliert
    acts = (
        await session.scalars(
            select(AuditEntry.action).where(AuditEntry.target_type == "site_config")
        )
    ).all()
    assert acts.count("config_activation") == 2
