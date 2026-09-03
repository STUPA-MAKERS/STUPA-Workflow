"""E2E seed (T-40): deterministic fixtures against the *real* compose stack.

The one-shot service ``seed`` runs this module on the backend image. It starts after
``migrate`` and as soon as ``api`` is healthy. It writes no production code and no
migration code. It uses the app modules only, against the DB that
``alembic upgrade head`` migrated.

The seed is idempotent. It runs against a fresh ``down -v`` DB and against a DB that
already holds data. It creates what is missing and reuses what is there. It never
deactivates or replaces an existing application type, form version or flow version.
It creates:

* The application type ``foerderantrag``. No migration seeds a type, so the seed
  creates one and attaches it to a seeded Gremium (migration ``0002`` seeds StuPa with
  the slug ``stupa`` and AStA with the slug ``asta``).
* An **active form version** for that type. Without it ``POST /applications`` fails in
  `get_effective_form`, so *every* E2E scenario depends on it. The server prepends the
  system field ``title`` to every effective form, so the seed does not define it.
* The **active global flow version**. Since migration ``0019`` one graph serves all
  application types, so the flow has no per-type binding. Graph: ``entwurf`` (initial,
  editable) -> ``pruefung`` (locked) -> ``angenommen`` / ``abgelehnt`` (both terminal).
* An **admin Principal**, an **admin RoleAssignment** and an **AuthSession**. The
  bootstrap admin works through the OIDC login only (service.py), and the gating stack
  runs *no* Keycloak. This script therefore mints a valid server session with the app
  function ``create_principal_session``, which knows ``SESSION_SECRET``, and writes the
  ``ap_session`` cookie. This is NO production backdoor. Only a test seed calls the
  normal signing function, in the same way as the ``force_login`` of Django.
* A **budget pot** for the ``/budget/pots`` view.

Output: ``${E2E_ARTIFACTS}/e2e.json`` (bind-mounted) with the cookie name and value, the
type, Gremium and pot IDs, the flow state keys and the form field keys. Playwright
``global-setup`` reads it.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import get_sessionmaker
from app.modules.admin.models import ApplicationType, Gremium
from app.modules.admin.schemas import ApplicationTypeCreate, FlowVersionCreate
from app.modules.admin.service import ConfigService
from app.modules.auth.models import Principal, Role, RoleAssignment
from app.modules.auth.sessions import create_principal_session
from app.modules.budget.models import BudgetPot
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.models import FormField
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.settings import get_settings
from app.shared.config_schemas import FlowGraph, FormFieldDef

ACTOR = "e2e-seed"
ADMIN_SUB = "e2e-admin"
ADMIN_EMAIL = "admin@e2e.test"
ADMIN_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")  # 0002_seed
TYPE_KEY = "foerderantrag"
# Preferred Gremium of the seeded type, in this order. Migration 0002 seeds both.
GREMIUM_SLUGS = ("stupa", "asta")
INITIAL_STATE = "entwurf"
LOCKED_STATE = "pruefung"

ARTIFACTS = pathlib.Path(os.environ.get("E2E_ARTIFACTS", "/artifacts"))


def _i18n(de: str, en: str) -> dict[str, str]:
    return {"de": de, "en": en}


async def _seeded_gremium(session) -> Gremium:
    """Return the StuPa Gremium, else AStA, else the oldest one.

    Raises:
        SystemExit: The database holds no Gremium at all.
    """
    for slug in GREMIUM_SLUGS:
        row = (
            await session.execute(select(Gremium).where(Gremium.slug == slug))
        ).scalar_one_or_none()
        if row is not None:
            return row
    row = (
        await session.execute(select(Gremium).order_by(Gremium.created_at))
    ).scalars().first()
    if row is None:
        raise SystemExit("seed: kein Gremium vorhanden — lief 0002?")
    return row


async def _ensure_type(session, gremium_id: uuid.UUID) -> ApplicationType:
    """Return the application type ``foerderantrag`` and create it when it is missing.

    No migration seeds an application type, so a fresh DB has none. An existing type
    stays untouched, including a NULL ``gremium_id``: the seed must not rewrite the
    config of a stack that already holds data.
    """
    row = (
        await session.execute(select(ApplicationType).where(ApplicationType.key == TYPE_KEY))
    ).scalar_one_or_none()
    if row is None:
        row = (
            await session.execute(select(ApplicationType).order_by(ApplicationType.created_at))
        ).scalars().first()
    if row is not None:
        return row

    created = await ConfigService(session).create_application_type(
        ApplicationTypeCreate.model_validate(
            {
                "key": TYPE_KEY,
                "nameI18n": _i18n("Förderantrag", "Funding application"),
                "gremiumId": str(gremium_id),
                "hasBudget": False,
            }
        ),
        ACTOR,
    )
    return (
        await session.execute(select(ApplicationType).where(ApplicationType.id == created.id))
    ).scalar_one()


async def _ensure_form(session, type_id: uuid.UUID) -> list[str]:
    """Make sure the type has an active form version, then return its field keys.

    An already active version is reused as it is. The returned keys describe what the
    Playwright specs can fill in, so they always come from the version in the DB.
    """
    active_id = (
        await session.execute(
            select(ApplicationType.active_form_version_id).where(ApplicationType.id == type_id)
        )
    ).scalar_one()
    if active_id is None:
        # No `titel` field: the server prepends the mandatory system field `title` to
        # every effective form. A second title field would duplicate it in the wizard
        # and would make the first text input ambiguous for the specs.
        fields = [
            FormFieldDef(
                key="beschreibung",
                type="textarea",
                label=_i18n("Beschreibung", "Description"),
                required=False,
            ),
            FormFieldDef(
                key="anhang",
                type="file",
                label=_i18n("Anhang (optional)", "Attachment (optional)"),
                required=False,
            ),
        ]
        created = await FormsService(session).create_form_version(
            type_id, FormVersionCreate(fields=fields, activate=True), ACTOR
        )
        active_id = created.id

    keys = (
        await session.execute(
            select(FormField.key)
            .where(FormField.form_version_id == active_id)
            .order_by(FormField.order)
        )
    ).scalars().all()
    return list(keys)


def _seed_flow_graph() -> FlowGraph:
    """Build the global graph: one initial state, every state reachable."""
    return FlowGraph.model_validate(
        {
            "states": [
                {
                    "key": INITIAL_STATE,
                    "label": _i18n("Entwurf", "Draft"),
                    "editAllowed": True,
                    "isInitial": True,
                    "color": "#94a3b8",
                },
                {
                    "key": LOCKED_STATE,
                    "label": _i18n("In Prüfung", "Under review"),
                    "editAllowed": False,
                    "color": "#f59e0b",
                },
                {
                    "key": "angenommen",
                    "label": _i18n("Angenommen", "Approved"),
                    "editAllowed": False,
                    "isTerminal": True,
                    "color": "#16a34a",
                },
                {
                    "key": "abgelehnt",
                    "label": _i18n("Abgelehnt", "Rejected"),
                    "editAllowed": False,
                    "isTerminal": True,
                    "color": "#dc2626",
                },
            ],
            "transitions": [
                {
                    "from": INITIAL_STATE,
                    "to": LOCKED_STATE,
                    "label": _i18n("Zur Prüfung", "Submit for review"),
                },
                {
                    "from": LOCKED_STATE,
                    "to": "angenommen",
                    "label": _i18n("Annehmen", "Approve"),
                },
                {
                    "from": LOCKED_STATE,
                    "to": "abgelehnt",
                    "label": _i18n("Ablehnen", "Reject"),
                },
            ],
        }
    )


async def _ensure_flow(session) -> dict[str, str]:
    """Make sure one active global flow version exists, then report its state keys.

    Since migration ``0019`` the flow is a single global graph. It has no
    ``application_type_id``, and the application type no longer points at a flow
    version. An active version is reused, so a stack that already holds applications
    keeps its states and its history.

    Returns:
        The keys the artifact carries: ``initial`` and ``locked``.
    """
    version_id = await session.scalar(
        select(FlowVersion.id).where(FlowVersion.active.is_(True)).limit(1)
    )
    if version_id is None:
        created = await ConfigService(session).create_global_flow_version(
            FlowVersionCreate(graph=_seed_flow_graph(), activate=True), ACTOR
        )
        version_id = created.id

    states = (
        await session.execute(select(State).where(State.flow_version_id == version_id))
    ).scalars().all()
    initial = next((s.key for s in states if s.is_initial), INITIAL_STATE)
    # The "locked" state is where the applicant may no longer edit. Prefer the seeded
    # key, then any non-terminal locked state, so a hand-built flow still resolves.
    locked = next(
        (s.key for s in states if s.key == LOCKED_STATE and not s.edit_allowed),
        next(
            (s.key for s in states if not s.edit_allowed and not s.is_terminal),
            next((s.key for s in states if not s.edit_allowed), initial),
        ),
    )
    return {"initial": initial, "locked": locked}


async def _ensure_budget_pot(session, gremium_id: uuid.UUID) -> uuid.UUID:
    existing = (
        await session.execute(select(BudgetPot).where(BudgetPot.name == "E2E-Topf"))
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    pot = BudgetPot(
        gremium_id=gremium_id, name="E2E-Topf", total=10000, currency="EUR",
        period="2026", active=True,
    )
    session.add(pot)
    await session.flush()
    return pot.id


async def _ensure_admin_session(session, settings) -> str:
    """Make sure the admin Principal and its RoleAssignment exist, then mint a session.

    Returns:
        The signed session cookie value.
    """
    principal = (
        await session.execute(select(Principal).where(Principal.sub == ADMIN_SUB))
    ).scalar_one_or_none()
    if principal is None:
        principal = Principal(sub=ADMIN_SUB, email=ADMIN_EMAIL, display_name="E2E Admin")
        session.add(principal)
        await session.flush()

    # Migration 0002 creates the admin role. Check for it defensively.
    role = (
        await session.execute(select(Role).where(Role.id == ADMIN_ROLE_ID))
    ).scalar_one_or_none()
    if role is None:
        role = (
            await session.execute(select(Role).where(Role.key == "admin"))
        ).scalar_one_or_none()
    if role is None:
        raise SystemExit("seed: admin-Rolle fehlt — lief 0002?")

    assignment = (
        await session.execute(
            select(RoleAssignment).where(
                RoleAssignment.principal_id == principal.id,
                RoleAssignment.role_id == role.id,
            )
        )
    ).scalar_one_or_none()
    if assignment is None:
        session.add(
            RoleAssignment(principal_id=principal.id, role_id=role.id, granted_by=ACTOR)
        )
        await session.flush()

    cookie = await create_principal_session(
        session,
        secret=settings.session_secret,
        principal_id=principal.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        refresh_token=None,
        id_token=None,
    )
    return cookie


async def main() -> None:
    settings = get_settings()
    maker = get_sessionmaker()
    async with maker() as session:
        gremium = await _seeded_gremium(session)
        app_type = await _ensure_type(session, gremium.id)
        field_keys = await _ensure_form(session, app_type.id)
        states = await _ensure_flow(session)
        # The pot needs a Gremium. An existing type may carry none, so fall back to the
        # seeded one instead of rewriting the type.
        pot_gremium_id = app_type.gremium_id or gremium.id
        pot_id = await _ensure_budget_pot(session, pot_gremium_id)
        admin_cookie = await _ensure_admin_session(session, settings)
        await session.commit()

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "sessionCookieName": settings.session_cookie_name,
        "adminCookie": admin_cookie,
        "applicantEmail": "antragsteller@e2e.test",
        "typeId": str(app_type.id),
        "gremiumId": str(pot_gremium_id),
        "budgetPotId": str(pot_id),
        "states": states,
        "fieldKeys": field_keys,
    }
    (ARTIFACTS / "e2e.json").write_text(json.dumps(payload, indent=2))
    print("seed: ok ->", ARTIFACTS / "e2e.json")


if __name__ == "__main__":
    asyncio.run(main())
