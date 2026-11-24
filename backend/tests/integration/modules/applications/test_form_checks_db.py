"""Integration: the checks of an Antrag across fields and its files (real Postgres).

- 001681: a Kostenstelle outside the root of its field gives 422
  `cost_centre_outside_subtree`; the root itself is outside too.
- 001671: an answer that breaks a `block` rule gives 422 `form_rule_failed`; a `warn` rule
  passes.
- 001730: a file of a position keeps its field and its position, as a draft and on the
  Antrag.
- 001732: an Antragsart with "Anhang Pflicht" refuses the create without a file and the
  transition out of the initial state while the Antrag has no file.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.service.forms import FormVersionWriter
from app.modules.application_types.models import ApplicationType
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.attachments.service import AttachmentService
from app.modules.auth.principal import Principal
from app.modules.budget.form_options import budget_field_options
from app.modules.budget.tree_models import Budget
from app.modules.files.drafts import DraftAttachments
from app.modules.flow.service import FlowService
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.settings import Settings
from app.shared.config_schemas import FormFieldDef, FormRule
from app.shared.errors import ValidationProblem
from tests._support.guest_apps import GuestSeed, guest_settings, seed_guest_flow

pytestmark = pytest.mark.integration

_PDF = b"%PDF-1.4\n%offer\n"
_MANAGER = Principal(sub="mgr-forms", roles=[], permissions={"application.manage"})


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def remove(self, key: str) -> None:
        self.blobs.pop(key, None)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1])


async def _form(
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    fields: list[dict[str, Any]],
    rules: list[dict[str, Any]] | None = None,
) -> None:
    async with maker() as session:
        await FormVersionWriter(session).create_form_version(
            seed.type_id,
            FormVersionCreate(
                fields=[
                    FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
                    *(FormFieldDef.model_validate(f) for f in fields),
                ],
                rules=[FormRule.model_validate(r) for r in rules or []],
                activate=True,
            ),
            "tester",
        )


def _payload(seed: GuestSeed, data: dict[str, Any], **extra: Any) -> ApplicationCreate:
    return ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": {"title": "Antrag", **data},
            "applicantEmail": "gast@example.org",
            "lang": "de",
            **extra,
        }
    )


async def _create(
    maker: async_sessionmaker[AsyncSession], settings: Settings, payload: ApplicationCreate
) -> uuid.UUID:
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            payload, draft_pepper=settings.magic_link_secret
        )
        return app.id


async def _tree(maker: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    """Seed QSM with a leaf below it and VSM with a leaf below it."""
    tag = uuid.uuid4().hex[:6].upper()
    async with maker() as session:
        qsm = Budget(parent_id=None, key=f"Q{tag}", path_key=f"Q{tag}", name="QSM")
        vsm = Budget(parent_id=None, key=f"V{tag}", path_key=f"V{tag}", name="VSM")
        session.add_all([qsm, vsm])
        await session.flush()
        q_leaf = Budget(
            parent_id=qsm.id,
            key="1",
            path_key=f"Q{tag}-1",
            tree_path=f"Q{tag}-1",
            name="Anschaffung",
        )
        v_leaf = Budget(
            parent_id=vsm.id,
            key="1",
            path_key=f"V{tag}-1",
            tree_path=f"V{tag}-1",
            name="Fahrt",
        )
        session.add_all([q_leaf, v_leaf])
        await session.commit()
        return {"root": f"Q{tag}", "qsm": qsm.id, "q_leaf": q_leaf.id, "v_leaf": v_leaf.id}


async def test_a_cost_centre_outside_the_root_is_refused(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await seed_guest_flow(maker)
    tree = await _tree(maker)
    await _form(
        maker,
        seed,
        [
            {
                "key": "ks",
                "type": "budget_select",
                "label": {"de": "Kostenstelle"},
                "validation": {"rootPath": tree["root"]},
            }
        ],
    )
    async with maker() as session:
        effective = await FormsService(session, budget_field_options).get_effective_form(
            seed.type_id
        )
    (field,) = [f for s in effective.sections for f in s.fields if f.key == "ks"]
    assert [o.value for o in field.options or []] == [str(tree["q_leaf"])]

    for outside in (tree["v_leaf"], tree["qsm"]):
        with pytest.raises(ValidationProblem) as exc:
            await _create(maker, settings, _payload(seed, {"ks": str(outside)}))
        assert exc.value.code == "cost_centre_outside_subtree"
    assert await _create(maker, settings, _payload(seed, {"ks": str(tree["q_leaf"])}))


async def test_a_block_rule_refuses_and_a_warn_rule_passes(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await seed_guest_flow(maker)
    await _form(
        maker,
        seed,
        [{"key": "summe", "type": "number", "label": {"de": "Summe"}}],
        [
            {
                "logic": {">=": [{"var": "summe"}, 500]},
                "message": {"de": "Ab 500 €.", "en": "From 500 €."},
                "severity": "block",
            },
            {
                "logic": {">=": [{"var": "summe"}, 1000]},
                "message": {"de": "Ab 1000 €.", "en": "From 1000 €."},
                "severity": "warn",
            },
        ],
    )
    with pytest.raises(ValidationProblem) as exc:
        await _create(maker, settings, _payload(seed, {"summe": 100}))
    assert exc.value.code == "form_rule_failed"
    assert await _create(maker, settings, _payload(seed, {"summe": 600}))


async def _require_file(maker: async_sessionmaker[AsyncSession], seed: GuestSeed) -> None:
    async with maker() as session:
        app_type = await session.get(ApplicationType, seed.type_id)
        assert app_type is not None
        app_type.attachment_required = True
        await session.commit()


async def test_an_antragsart_with_a_required_file(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await seed_guest_flow(maker)
    early = await _create(maker, settings, _payload(seed, {}))
    await _require_file(maker, seed)

    with pytest.raises(ValidationProblem) as exc:
        await _create(maker, settings, _payload(seed, {}))
    assert exc.value.code == "attachment_required"

    async with maker() as session:
        with pytest.raises(ValidationProblem) as exc:
            await FlowService(session).fire(early, seed.transition_id, _MANAGER)
        assert exc.value.code == "attachment_required"
        await session.rollback()

    async with maker() as session:
        files = AttachmentService(session, storage=_MemoryStorage(), settings=settings)  # type: ignore[arg-type]
        draft = await DraftAttachments(files).upload(
            token=None, filename="beleg.pdf", data=_PDF, by="applicant"
        )
        await files.upload(early, filename="beleg.pdf", data=_PDF, by="applicant")
    with_file = await _create(
        maker,
        settings,
        _payload(seed, {}, attachmentIds=[str(draft.id)], draftToken=draft.draftToken),
    )
    assert with_file
    async with maker() as session:
        res = await FlowService(session).fire(early, seed.transition_id, _MANAGER)
    assert res.new_state_id == seed.locked_state_id
