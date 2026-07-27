"""E2E seed (T-40): deterministic fixtures against the *real* compose stack.

The one-shot service ``seed`` runs this module on the backend image. It starts after
``migrate`` and as soon as ``api`` is healthy. It writes no production code and no
migration code. It uses the app modules only, against the fresh DB that
``alembic upgrade head`` migrated.

The seed is idempotent for every run against a fresh ``down -v`` DB. It creates:

* An **active form version** and an **active flow version** for the default application
  type ``foerderantrag`` that migration ``0018`` seeds. Without them ``POST /applications``
  fails in `get_effective_form` and `_initial_state`, so *every* E2E scenario depends on
  them. Flow: ``entwurf`` (initial, editable) -> ``pruefung`` (locked) ->
  ``angenommen`` / ``abgelehnt``.
* An **admin Principal**, an **admin RoleAssignment** and an **AuthSession**. The
  bootstrap admin works through the OIDC login only (service.py), and the gating stack
  runs *no* Keycloak. This script therefore mints a valid server session with the app
  function ``create_principal_session``, which knows ``SESSION_SECRET``, and writes the
  ``ap_session`` cookie. This is NO production backdoor. Only a test seed calls the
  normal signing function, in the same way as the ``force_login`` of Django.
* A **budget pot** for the ``/budget/pots`` view.

Output: ``${E2E_ARTIFACTS}/e2e.json`` (bind-mounted) with the cookie name and value, the
type, Gremium and pot IDs, and the flow state keys. Playwright ``global-setup`` reads it.
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
from app.modules.auth.models import AuthSession, Principal, Role, RoleAssignment
from app.modules.auth.sessions import create_principal_session
from app.modules.budget.models import BudgetPot
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.settings import get_settings
from app.shared.config_schemas import FormFieldDef

ADMIN_SUB = "e2e-admin"
ADMIN_EMAIL = "admin@e2e.test"
ADMIN_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")  # 0003_seed_roles
ARTIFACTS = pathlib.Path(os.environ.get("E2E_ARTIFACTS", "/artifacts"))


def _i18n(de: str, en: str) -> dict[str, str]:
    return {"de": de, "en": en}


async def _default_type(session) -> ApplicationType:
    """Get the default application type ``foerderantrag``, or the oldest type as fallback."""
    row = (
        await session.execute(select(ApplicationType).where(ApplicationType.key == "foerderantrag"))
    ).scalar_one_or_none()
    if row is None:
        row = (
            await session.execute(select(ApplicationType).order_by(ApplicationType.created_at))
        ).scalars().first()
    if row is None:
        raise SystemExit("seed: kein ApplicationType vorhanden — lief 0018?")
    return row


async def _ensure_form(session, type_id: uuid.UUID) -> None:
    """Create the active form version, but only when no version is active yet."""
    existing = (
        await session.execute(
            select(ApplicationType.active_form_version_id).where(ApplicationType.id == type_id)
        )
    ).scalar_one()
    if existing is not None:
        return
    fields = [
        FormFieldDef(
            key="titel",
            type="text",
            label=_i18n("Titel des Antrags", "Application title"),
            required=True,
        ),
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
    await FormsService(session).create_form_version(
        type_id, FormVersionCreate(fields=fields, activate=True)
    )


async def _ensure_flow(session, type_id: uuid.UUID) -> None:
    """Create the active flow version with its states and transitions, if none is active."""
    active = (
        await session.execute(
            select(ApplicationType.active_flow_version_id).where(ApplicationType.id == type_id)
        )
    ).scalar_one()
    if active is not None:
        return

    flow = FlowVersion(application_type_id=type_id, version=1, active=True)
    session.add(flow)
    await session.flush()

    entwurf = State(
        flow_version_id=flow.id, key="entwurf", label_i18n=_i18n("Entwurf", "Draft"),
        category="open", edit_allowed=True, is_initial=True,
    )
    pruefung = State(
        flow_version_id=flow.id, key="pruefung", label_i18n=_i18n("In Prüfung", "Under review"),
        category="running", edit_allowed=False, is_initial=False,
    )
    angenommen = State(
        flow_version_id=flow.id, key="angenommen", label_i18n=_i18n("Angenommen", "Approved"),
        category="closed", edit_allowed=False, is_initial=False,
    )
    abgelehnt = State(
        flow_version_id=flow.id, key="abgelehnt", label_i18n=_i18n("Abgelehnt", "Rejected"),
        category="closed", edit_allowed=False, is_initial=False,
    )
    session.add_all([entwurf, pruefung, angenommen, abgelehnt])
    await session.flush()

    session.add_all(
        [
            Transition(
                flow_version_id=flow.id, from_state_id=entwurf.id, to_state_id=pruefung.id,
                label_i18n=_i18n("Zur Prüfung", "Submit for review"), order=0,
            ),
            Transition(
                flow_version_id=flow.id, from_state_id=pruefung.id, to_state_id=angenommen.id,
                label_i18n=_i18n("Annehmen", "Approve"), order=1,
            ),
            Transition(
                flow_version_id=flow.id, from_state_id=pruefung.id, to_state_id=abgelehnt.id,
                label_i18n=_i18n("Ablehnen", "Reject"), order=2,
            ),
        ]
    )

    app_type = (
        await session.execute(select(ApplicationType).where(ApplicationType.id == type_id))
    ).scalar_one()
    app_type.active_flow_version_id = flow.id


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

    # Migration 0003 creates the admin role. Check for it defensively.
    role = (
        await session.execute(select(Role).where(Role.id == ADMIN_ROLE_ID))
    ).scalar_one_or_none()
    if role is None:
        role = (
            await session.execute(select(Role).where(Role.key == "admin"))
        ).scalar_one_or_none()
    if role is None:
        raise SystemExit("seed: admin-Rolle fehlt — lief 0003?")

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
            RoleAssignment(principal_id=principal.id, role_id=role.id, granted_by="e2e-seed")
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
        app_type = await _default_type(session)
        await _ensure_form(session, app_type.id)
        await _ensure_flow(session, app_type.id)
        pot_id = await _ensure_budget_pot(session, app_type.gremium_id) if app_type.gremium_id else None
        admin_cookie = await _ensure_admin_session(session, settings)
        await session.commit()

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "sessionCookieName": settings.session_cookie_name,
        "adminCookie": admin_cookie,
        "applicantEmail": "antragsteller@e2e.test",
        "typeId": str(app_type.id),
        "gremiumId": str(app_type.gremium_id) if app_type.gremium_id else None,
        "budgetPotId": str(pot_id) if pot_id else None,
        "states": {
            "initial": "entwurf",
            "locked": "pruefung",
        },
        "fieldKeys": ["titel", "beschreibung", "anhang"],
    }
    (ARTIFACTS / "e2e.json").write_text(json.dumps(payload, indent=2))
    print("seed: ok ->", ARTIFACTS / "e2e.json")


if __name__ == "__main__":
    asyncio.run(main())
