"""Integration (real Postgres, testcontainers): admin and config service (T-24).

The tests run against a real schema. Flow version creation maps the graph to state and
transition rows. The version counter grows, and a partial unique index keeps exactly
one version active. CRUD for Gremium, application type, role and webhook reports a
conflict on a duplicate key. RBAC delegation runs through `role_assignment` and
`group_mapping`. The site-config draft and activate cycle (#21) produces a new active
version. Each of these steps writes an audit entry.
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
    """Empty the admin tables for each test.

    This truncation adds to the core truncation of the `engine` fixture. The seeded
    roles stay. New roles carry unique keys.
    """
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
    """Prove that every save creates a NEW, immutable FlowVersion (#config-versioning).

    Earlier versions stay. Open applications follow the newest active version by state
    KEY, so they are NOT pinned. A key that the new version drops sends the application
    to the initial state.
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

    # Create an application in state "accepted". The new graph drops that state.
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

    # Save again WITHOUT "accepted". This makes a NEW version and keeps the old one.
    g2 = await svc.create_global_flow_version(
        FlowVersionCreate.model_validate({"graph": _global_graph(with_accepted=False)}),
        _ACTOR,
    )
    assert g2.id != g1.id  # a new immutable version, no in-place reuse

    # Append-only: both versions still exist and exactly one is active (g2).
    n_global = await session.scalar(select(func.count()).select_from(FlowVersion))
    assert n_global == 2
    n_active = await session.scalar(
        select(func.count())
        .select_from(FlowVersion)
        .where(FlowVersion.active.is_(True))
    )
    assert n_active == 1

    # The application follows the newest version. A dropped state key maps to its
    # initial state.
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
    """A save that omits a state does NOT delete the old version (#config-versioning).

    The state rows of the old version stay valid, and so does the `status_event`
    timeline. No foreign key breaks and no row needs a new target. The old in-place
    flow needed both.
    """
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
    # Timeline entry that points to "accepted". The old version keeps that state.
    ev = StatusEvent(application_id=app.id, from_state_id=None, to_state_id=accepted.id)
    session.add(ev)
    await session.commit()

    # Omit "accepted" in the new graph. The old version still holds it.
    await svc.create_global_flow_version(
        FlowVersionCreate.model_validate({"graph": _global_graph(with_accepted=False)}),
        _ACTOR,
    )

    # The timeline stays valid because "accepted" still exists in g1.
    await session.refresh(ev)
    assert ev.to_state_id == accepted.id
    still_there = await session.scalar(
        select(func.count()).select_from(State).where(State.id == accepted.id)
    )
    assert still_there == 1


async def test_gremium_crud_and_slug_conflict(session: AsyncSession) -> None:
    svc = ConfigService(session)
    slug = f"asta-{uuid.uuid4().hex[:8]}"
    created = await svc.create_gremium(
        GremiumCreate(name="AStA", slug=slug), _ACTOR
    )
    assert created.cd_variant_id is None
    with pytest.raises(ConflictError):
        await svc.create_gremium(GremiumCreate(name="Dup", slug=slug), _ACTOR)
    updated = await svc.update_gremium(
        created.id, GremiumUpdate(name="AStA neu"), _ACTOR
    )
    assert updated.name == "AStA neu"


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
    updated = await svc.update_role(
        created.id, RoleUpdate(permissions=["budget.structure"]), _ACTOR
    )
    assert updated.permissions == ["budget.structure"]
    listed = await svc.list_roles()
    keys = {r.key for r in listed}
    assert key in keys and "admin" in keys  # the new role and the seeded roles

    # #38: a role is deletable, except the protected admin and member roles.
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

    # An unknown principal gives 404.
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

    # The server creates the secret in the DB column but never returns it.
    row = await session.get(Webhook, created.id)
    assert row is not None and row.secret is not None and len(row.secret) == 32

    updated = await svc.update_webhook(created.id, WebhookUpdate(active=False), _ACTOR)
    assert updated.active is False
    assert len(await svc.list_webhooks()) == 1
    with pytest.raises(NotFoundError):
        await svc.update_webhook(uuid.uuid4(), WebhookUpdate(active=True), _ACTOR)


async def test_site_config_draft_activate_cycle(session: AsyncSession) -> None:
    svc = SiteConfigService(session)
    empty = await svc.get()
    assert empty.version == 0 and empty.has_draft_changes is False

    b1 = Branding.model_validate({"copyright": {"de": "© 2026 StuPa"}})
    after_draft = await svc.put_draft(b1, _ACTOR)
    assert after_draft.has_draft_changes is True
    assert after_draft.version == 0  # not activated yet

    activated = await svc.activate(_ACTOR)
    assert activated.version == 1 and activated.has_draft_changes is False
    assert activated.active.copyright == {"de": "© 2026 StuPa"}

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

    # Exactly one active version, held by the partial unique index.
    actives = (
        await session.scalars(
            select(func.count())
            .select_from(SiteConfigVersion)
            .where(SiteConfigVersion.active.is_(True))
        )
    ).all()
    assert actives[0] == 1

    # Activation without an open draft raises a conflict.
    with pytest.raises(ConflictError):
        await svc.activate(_ACTOR)

    # Every activation writes an audit entry.
    acts = (
        await session.scalars(
            select(AuditEntry.action).where(AuditEntry.target_type == "site_config")
        )
    ).all()
    assert acts.count("config_activation") == 2
