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
from app.modules.flow.models import FlowVersion, State
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
            {"key": "draft", "label": {"de": "Entwurf"}, "isInitial": True, "color": "#4a90d9"},
            {"key": "review", "label": {"de": "Prüfung"}, "color": "#4a90d9"},
        ],
        "transitions": [
            {
                "from": "draft",
                "to": "review",
                "label": {"de": "Einreichen"},
                "guard": {"hasField": "title"},
                "actions": ([{"type": "notify", "event": "status_changed"}] if with_action else []),
            }
        ],
    }


# --------------------------------------------------------------- flow-versions
def _global_graph(*, with_accepted: bool = True) -> dict:
    states = [{"key": "created", "label": {"de": "Erstellt"}, "isInitial": True}]
    if with_accepted:
        states.append({"key": "accepted", "label": {"de": "Angenommen"}})
    states.append({"key": "rejected", "label": {"de": "Abgelehnt"}})
    transitions = [{"from": "created", "to": "rejected", "label": {"de": "ab"}}]
    if with_accepted:
        transitions.append({"from": "created", "to": "accepted", "label": {"de": "an"}})
    return {"states": states, "transitions": transitions}


async def test_global_flow_new_version_per_save_app_follows_newest(
    session: AsyncSession,
) -> None:
    """Jeder Save legt eine NEUE, unveränderliche FlowVersion an (#config-versioning):
    frühere Versionen bleiben erhalten; laufende Anträge folgen per State-KEY der
    jüngsten (aktiven) Version — sind also NICHT gepinnt; ein entfernter Key ⇒ Initial.
    """
    from app.modules.applications.models import Application
    from app.modules.forms.models import FormVersion

    svc = ConfigService(session)
    g1 = await svc.create_global_flow_version(
        FlowVersionCreate.model_validate({"graph": _global_graph()}), _ACTOR
    )
    accepted = (
        await session.scalars(
            select(State).where(State.flow_version_id == g1.id, State.key == "accepted")
        )
    ).one()

    # Antrag im (im neuen Graphen entfallenden) State »accepted« anlegen.
    app_type = await _make_type(session)
    fv = FormVersion(application_type_id=app_type.id, version=1)
    session.add(fv)
    await session.flush()
    app = Application(
        type_id=app_type.id, form_version_id=fv.id, flow_version_id=g1.id,
        current_state_id=accepted.id, data={},
    )
    session.add(app)
    await session.commit()

    # Erneut speichern OHNE »accepted« → NEUE Version; die alte bleibt erhalten.
    g2 = await svc.create_global_flow_version(
        FlowVersionCreate.model_validate({"graph": _global_graph(with_accepted=False)}),
        _ACTOR,
    )
    assert g2.id != g1.id  # neue, unveränderliche Version (kein In-place-Reuse)

    # Append-only: beide Versionen existieren weiter, genau eine ist aktiv (g2).
    n_global = await session.scalar(select(func.count()).select_from(FlowVersion))
    assert n_global == 2
    n_active = await session.scalar(
        select(func.count())
        .select_from(FlowVersion)
        .where(FlowVersion.active.is_(True))
    )
    assert n_active == 1

    # Antrag folgt der jüngsten Version; entfernter State-Key ⇒ deren Initial-State.
    new_initial = (
        await session.scalars(
            select(State).where(
                State.flow_version_id == g2.id, State.is_initial.is_(True)
            )
        )
    ).one()
    await session.refresh(app)
    assert app.flow_version_id == g2.id
    assert app.current_state_id == new_initial.id


async def test_global_flow_save_keeps_prior_states_and_timeline(
    session: AsyncSession,
) -> None:
    """Ein Save, der einen State weglässt, LÖSCHT die alte Version nicht (#config-
    versioning): deren State-Zeilen — und damit die ``status_event``-Timeline — bleiben
    gültig. Kein FK-Bruch, kein Repointing nötig (anders als im alten In-place-Flow)."""
    from app.modules.applications.models import Application, StatusEvent
    from app.modules.forms.models import FormVersion

    svc = ConfigService(session)
    g1 = await svc.create_global_flow_version(
        FlowVersionCreate.model_validate({"graph": _global_graph()}), _ACTOR
    )
    accepted = (
        await session.scalars(
            select(State).where(State.flow_version_id == g1.id, State.key == "accepted")
        )
    ).one()

    app_type = await _make_type(session)
    fv = FormVersion(application_type_id=app_type.id, version=1)
    session.add(fv)
    await session.flush()
    app = Application(
        type_id=app_type.id, form_version_id=fv.id, flow_version_id=g1.id,
        current_state_id=accepted.id, data={},
    )
    session.add(app)
    await session.flush()
    # Timeline-Eintrag auf »accepted« (bleibt in der alten Version erhalten).
    ev = StatusEvent(application_id=app.id, from_state_id=None, to_state_id=accepted.id)
    session.add(ev)
    await session.commit()

    # »accepted« im neuen Graphen weglassen → neue Version; alte behält »accepted«.
    await svc.create_global_flow_version(
        FlowVersionCreate.model_validate({"graph": _global_graph(with_accepted=False)}),
        _ACTOR,
    )

    # Timeline bleibt unverändert gültig: »accepted« existiert weiter (in g1).
    await session.refresh(ev)
    assert ev.to_state_id == accepted.id
    still_there = await session.scalar(
        select(func.count()).select_from(State).where(State.id == accepted.id)
    )
    assert still_there == 1


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

    # #38: löschbar — außer den geschützten admin/member.
    await svc.delete_role(created.id, _ACTOR)
    assert key not in {r.key for r in await svc.list_roles()}
    admin = next(r for r in await svc.list_roles() if r.key == "admin")
    with pytest.raises(ConflictError):
        await svc.delete_role(admin.id, _ACTOR)


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
