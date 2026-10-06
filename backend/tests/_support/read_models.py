"""Integration helpers for the application read models (A3, A4, A9, A11, A12, O21).

The helpers seed one world against a real schema:

* the Gremium ``StuPa`` with a member who reads through the Gremium read scope
  (a view cost centre of the Gremium) and has no global read permission,
* an application type with the fields ``title``, ``iban`` (``isPII``) and ``note``,
* the active flow ``eingang`` -> ``pruefung`` -> ``genehmigt`` with two labelled
  manual transitions,
* the principal rows of a member and of the logged-in creator, with display names.

The ``engine`` fixture truncates the application and flow tables only. Every key
with a unique constraint in ``gremium``, ``principal`` and ``budget`` therefore
carries a fresh tag.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_applicant, get_current_principal
from app.modules.admin.models import (
    ApplicationType,
    Gremium,
    GremiumMembership,
    GremiumRole,
)
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Applicant, Principal
from app.modules.budget.tree_models import Budget
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.flow.service import FlowService
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.shared.config_schemas import FormFieldDef
from tests._support.guest_apps import build_api, guest_settings

GREMIUM_NAME = "StuPa"
MEMBER_NAME = "Max Mitglied"
OWNER_NAME = "Olga Antrag"
IBAN = "DE02120300000000202051"


@dataclass(frozen=True)
class ReadSeed:
    gremium_id: uuid.UUID
    type_id: uuid.UUID
    budget_id: uuid.UUID
    eingang_id: uuid.UUID
    pruefung_id: uuid.UUID
    genehmigt_id: uuid.UUID
    to_review_id: uuid.UUID
    approve_id: uuid.UUID
    member_sub: str
    owner_sub: str


def form_fields() -> list[FormFieldDef]:
    return [
        FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
        FormFieldDef.model_validate(
            {"key": "iban", "type": "text", "label": {"de": "IBAN"}, "isPII": True}
        ),
        FormFieldDef(key="note", type="text", label={"de": "Notiz"}),
    ]


async def seed_read_world(maker: async_sessionmaker[AsyncSession]) -> ReadSeed:
    """Seed the Gremium, the member, the type, the cost centre and the flow."""
    tag = uuid.uuid4().hex[:8]
    member_sub = f"member-{tag}"
    owner_sub = f"owner-{tag}"
    async with maker() as session:
        gremium = Gremium(name=GREMIUM_NAME, slug=f"stupa-{tag}")
        session.add(gremium)
        await session.flush()
        member = PrincipalRow(sub=member_sub, display_name=MEMBER_NAME)
        owner = PrincipalRow(sub=owner_sub, display_name=OWNER_NAME)
        role = GremiumRole(
            gremium_id=gremium.id,
            key="member",
            name_i18n={"de": "Mitglied"},
            permissions=["vote.cast"],
        )
        session.add_all([member, owner, role])
        await session.flush()
        session.add(
            GremiumMembership(
                principal_id=member.id,
                gremium_id=gremium.id,
                gremium_role_id=role.id,
                valid_from=None,
                valid_until=None,
            )
        )
        budget = Budget(
            parent_id=None,
            key=f"RM{tag}",
            path_key=f"RM{tag}",
            name="Lesesicht",
            view_gremium_id=gremium.id,
        )
        app_type = ApplicationType(
            gremium_id=gremium.id, key=f"t-{tag}", name_i18n={}, has_budget=False
        )
        session.add_all([budget, app_type])
        await session.commit()
        await FormsService(session).create_form_version(
            app_type.id, FormVersionCreate(fields=form_fields(), activate=True), "tester"
        )

        flow = FlowVersion(version=1, active=True, editor_layout={})
        session.add(flow)
        await session.flush()
        eingang = State(
            flow_version_id=flow.id,
            key="eingang",
            label_i18n={"de": "Eingang"},
            edit_allowed=True,
            is_initial=True,
        )
        pruefung = State(
            flow_version_id=flow.id,
            key="pruefung",
            label_i18n={"de": "In Prüfung"},
            edit_allowed=True,
        )
        genehmigt = State(
            flow_version_id=flow.id,
            key="genehmigt",
            label_i18n={"de": "Genehmigt"},
            edit_allowed=False,
        )
        session.add_all([eingang, pruefung, genehmigt])
        await session.flush()
        to_review = Transition(
            flow_version_id=flow.id,
            from_state_id=eingang.id,
            to_state_id=pruefung.id,
            label_i18n={"de": "Zur Prüfung", "en": "To review"},
            actions=[],
            order=0,
        )
        approve = Transition(
            flow_version_id=flow.id,
            from_state_id=pruefung.id,
            to_state_id=genehmigt.id,
            label_i18n={"de": "Genehmigen", "en": "Approve"},
            actions=[],
            order=1,
        )
        session.add_all([to_review, approve])
        await session.commit()
        return ReadSeed(
            gremium_id=gremium.id,
            type_id=app_type.id,
            budget_id=budget.id,
            eingang_id=eingang.id,
            pruefung_id=pruefung.id,
            genehmigt_id=genehmigt.id,
            to_review_id=to_review.id,
            approve_id=approve.id,
            member_sub=member_sub,
            owner_sub=owner_sub,
        )


async def create_app(
    maker: async_sessionmaker[AsyncSession],
    seed: ReadSeed,
    *,
    actor: str,
    title: str = "Antrag",
    in_read_scope: bool = True,
) -> uuid.UUID:
    """Create a confirmed application with an IBAN and put it in the Gremium read scope.

    ``actor="applicant"`` gives a guest submission. The helper confirms it, so the
    principal routes see it too.
    """
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": {"title": title, "iban": IBAN, "note": "erste Notiz"},
            "applicantEmail": "antrag@example.org",
            "applicantName": "Anna Antrag",
            "lang": "de",
        }
    )
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(payload, actor=actor)
        row = await session.get(Application, app.id)
        assert row is not None
        if row.email_confirmed_at is None:
            row.email_confirmed_at = datetime.now(UTC)
        if in_read_scope:
            row.budget_id = seed.budget_id
        await session.commit()
        return app.id


def staff(seed: ReadSeed) -> Principal:
    """A member who may fire transitions and edit, without a read permission."""
    return Principal(
        sub=seed.member_sub,
        display_name=MEMBER_NAME,
        roles=["reviewer"],
        permissions={"application.transition", "application.manage"},
    )


async def fire(
    maker: async_sessionmaker[AsyncSession],
    app_id: uuid.UUID,
    transition_id: uuid.UUID,
    principal: Principal,
) -> None:
    async with maker() as session:
        await FlowService(session).fire(app_id, transition_id, principal)


async def patch(
    maker: async_sessionmaker[AsyncSession],
    app_id: uuid.UUID,
    data: dict[str, object],
    *,
    changed_by: str,
) -> None:
    async with maker() as session:
        await ApplicationsService(session).patch(app_id, data, changed_by=changed_by)


def as_principal(api: FastAPI, principal: Principal) -> None:
    api.dependency_overrides[get_current_principal] = lambda: principal
    api.dependency_overrides[get_current_applicant] = lambda: None


def as_applicant(api: FastAPI, app_id: uuid.UUID) -> None:
    api.dependency_overrides[get_current_principal] = lambda: None
    api.dependency_overrides[get_current_applicant] = lambda: Applicant(
        application_id=str(app_id), scope="edit"
    )


def get_json(api: FastAPI, path: str) -> object:
    with TestClient(api) as client:
        resp = client.get(path)
    assert resp.status_code == 200, resp.text
    return resp.json()


def build_read_api(db_url: str, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Build the app against the test database, without mail or rate limits."""
    return build_api(db_url, guest_settings(db_url), monkeypatch)
