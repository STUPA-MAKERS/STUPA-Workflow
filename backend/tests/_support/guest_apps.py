"""Integration helpers for applications without an account (Z1).

The helpers seed a gremium, an application type with an active form and an active
flow `eingang` (edit allowed) -> `gesperrt` (edit locked). They create applications
through the service, issue magic links and redeem them. The flow has no actions and
no deadlines, so the helpers need no dispatcher.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import get_session
from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth import service as auth_service
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.settings import Settings, get_settings, load_settings
from app.shared.config_schemas import FormFieldDef

GUEST_EMAIL = "gast@example.org"


@dataclass(frozen=True)
class GuestSeed:
    gremium_id: uuid.UUID
    type_id: uuid.UUID
    open_state_id: uuid.UUID
    locked_state_id: uuid.UUID
    transition_id: uuid.UUID


def guest_settings(db_url: str) -> Settings:
    return load_settings(
        database_url=db_url,
        session_secret="session-secret-guest-links-0001",
        magic_link_secret="magic-link-secret-guest-links01",
        cookie_secure=False,
        rate_limit_enabled=False,
    )


async def seed_guest_flow(maker: async_sessionmaker[AsyncSession]) -> GuestSeed:
    """Create a gremium, a type with a form, and the flow `eingang` -> `gesperrt`.

    The transition `eingang` -> `gesperrt` is manual and has no guard.
    """
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        gremium = Gremium(name="G", slug=f"g-{tag}")
        session.add(gremium)
        await session.flush()
        app_type = ApplicationType(
            gremium_id=gremium.id, key=f"t-{tag}", name_i18n={}, has_budget=False
        )
        session.add(app_type)
        await session.commit()
        await FormsService(session).create_form_version(
            app_type.id,
            FormVersionCreate(
                fields=[
                    FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True)
                ],
                activate=True,
            ),
            "tester",
        )
        flow = FlowVersion(version=1, active=True, editor_layout={})
        session.add(flow)
        await session.flush()
        open_state = State(
            flow_version_id=flow.id,
            key="eingang",
            label_i18n={"de": "Eingang"},
            edit_allowed=True,
            is_initial=True,
        )
        locked = State(
            flow_version_id=flow.id,
            key="gesperrt",
            label_i18n={"de": "Gesperrt"},
            edit_allowed=False,
        )
        session.add_all([open_state, locked])
        await session.flush()
        transition = Transition(
            flow_version_id=flow.id,
            from_state_id=open_state.id,
            to_state_id=locked.id,
            label_i18n={"de": "Sperren"},
            guard=None,
            actions=[],
            order=0,
        )
        session.add(transition)
        await session.commit()
        return GuestSeed(
            gremium_id=gremium.id,
            type_id=app_type.id,
            open_state_id=open_state.id,
            locked_state_id=locked.id,
            transition_id=transition.id,
        )


def guest_payload(type_id: uuid.UUID, email: str = GUEST_EMAIL) -> ApplicationCreate:
    return ApplicationCreate.model_validate(
        {
            "typeId": str(type_id),
            "data": {"title": "Gastantrag"},
            "applicantEmail": email,
            "lang": "de",
        }
    )


async def create_guest_application(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed, email: str = GUEST_EMAIL
) -> uuid.UUID:
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(guest_payload(seed.type_id, email))
        return app.id


async def issue_magic_token(
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    app_id: uuid.UUID,
    email: str = GUEST_EMAIL,
) -> str:
    """Request a magic link for the application and return its plaintext token."""
    links: list[str] = []

    def _deliver(_email: str, link: str) -> None:
        links.append(link)

    async with maker() as session:
        await auth_service.request_magic_link(
            session, settings, email=email, application_id=app_id, deliver=_deliver
        )
        await session.commit()
    (link,) = links
    match = re.search(r"#t=(.+)$", link)
    assert match is not None
    return match.group(1)


async def redeem(maker: async_sessionmaker[AsyncSession], settings: Settings, token: str) -> str:
    """Redeem a token and return the scope of the new applicant session."""
    async with maker() as session:
        _, scope, _ = await auth_service.verify_magic_link(session, settings, token=token)
        await session.commit()
    return scope


def build_api(db_url: str, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Build the app with its own pool-free engine for the TestClient event loop."""
    import app.main as main_mod

    request_maker = async_sessionmaker(
        create_async_engine(db_url, poolclass=NullPool), expire_on_commit=False
    )

    async def _request_session() -> AsyncIterator[AsyncSession]:
        async with request_maker() as db:
            yield db

    monkeypatch.setattr(main_mod, "get_sessionmaker", lambda: request_maker)
    application = main_mod.create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_session] = _request_session
    return application
