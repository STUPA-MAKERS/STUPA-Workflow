"""A Haushaltsplan is decided in a meeting: as an agenda item with one vote.

A plan version that waits for a Gremium goes on the agenda of a meeting of that Gremium.
The vote on that item opens only while the step waits. An accepted vote passes the step,
and a refused vote sends the version back to the draft.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_principal
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.budget.plan_models import BudgetPlanLine, BudgetPlanVersion
from app.modules.budget.plan_schemas import PlanLineSet, PlanStateSet
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.files.storage import ObjectStorage
from app.modules.meetings.models import MeetingAgendaItem
from app.modules.pdf.typst_client import TypstClient
from app.modules.protocol.service import ProtocolService
from app.modules.voting.models import Vote
from app.modules.voting.service import VotingService
from tests.integration.modules.budget.test_budget_plan import (
    _balanced_draft,
    _steps,
    _tree,
    _version,
)
from tests.integration.modules.livevote.conftest import Seed, audit_actions, seed

pytestmark = pytest.mark.integration

_TITLE = "Haushaltsplan VS-Mittel 2026: Beschluss"


async def _waiting(
    maker: async_sessionmaker[AsyncSession], gremium_id: uuid.UUID, *, ask: bool = True
) -> uuid.UUID:
    """Write a balanced plan whose one step names the Gremium, and ask for its decision."""
    async with maker() as session:
        t = await _tree(session)
        await _steps(t, "Beschluss", gremium_id=gremium_id)
        vid = _version(await _balanced_draft(t)).id
        if ask:
            await t.svc.request_step(vid)
        await session.commit()
    return vid


async def _state(maker: async_sessionmaker[AsyncSession], vid: uuid.UUID) -> str:
    async with maker() as session:
        return (await session.get_one(BudgetPlanVersion, vid)).state


def _offered(client: TestClient, s: Seed) -> dict[str, Any]:
    resp = client.get(f"/api/meetings/{s.meeting_id}/agenda/assignable-plans")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _add(client: TestClient, s: Seed, vid: uuid.UUID) -> dict[str, object]:
    resp = client.post(f"/api/meetings/{s.meeting_id}/agenda", json={"planVersionId": str(vid)})
    assert resp.status_code == 200, resp.text
    return next(i for i in resp.json() if i["planVersionId"] == str(vid))


async def test_the_agenda_offers_the_waiting_plans_of_its_gremium(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/finance/budget/000838: the lead adds a waiting plan as an agenda item, once."""
    s = await seed(maker, status="planned", items=0)
    other = await seed(maker, status="planned", items=0)
    closed = await seed(maker, status="closed", items=0)
    vid = await _waiting(maker, s.gremium_id)
    draft = await _waiting(maker, s.gremium_id, ask=False)
    with TestClient(api) as client:
        offered = _offered(client, s)["plans"]
        waiting = [p for p in offered if not p["reading"]]
        assert [(p["planVersionId"], p["title"]) for p in waiting] == [(str(vid), _TITLE)]
        assert str(draft) in {p["planVersionId"] for p in offered if p["reading"]}
        offered = waiting
        assert (offered[0]["budgetName"], offered[0]["fiscalYear"]) == ("VS-Mittel", "2026")
        assert (offered[0]["number"], offered[0]["step"]) == (0, "Beschluss")
        elsewhere = _offered(client, other)["plans"]
        assert elsewhere == []
        assert (_offered(client, s)["decides"], _offered(client, other)["decides"]) == (True, False)

        item = _add(client, s, vid)
        assert (item["title"], item["applicationId"]) == (_TITLE, None)
        left = _offered(client, s)["plans"]
        assert str(vid) not in {p["planVersionId"] for p in left}

        twice = client.post(
            f"/api/meetings/{s.meeting_id}/agenda", json={"planVersionId": str(vid)}
        )
        assert (twice.status_code, twice.json()["code"]) == (409, "plan_already_on_agenda")
        for meeting_id, version, status, code in (
            (other.meeting_id, vid, 409, "plan_step_not_waiting"),
            (closed.meeting_id, vid, 409, "plan_step_not_waiting"),
            (s.meeting_id, uuid.uuid4(), 404, None),
        ):
            refused = client.post(
                f"/api/meetings/{meeting_id}/agenda", json={"planVersionId": str(version)}
            )
            assert refused.status_code == status, refused.text
            assert code is None or refused.json()["code"] == code

        plan = client.get(f"/api/budget-plan-versions/{vid}/plan").json()
        assert [m["id"] for m in plan["versions"][-1]["meetings"]] == [str(s.meeting_id)]

        api.dependency_overrides[get_current_principal] = lambda: Principal(
            sub="member", groups={vote_group_key(s.gremium_id)}
        )
        reader = client.get(f"/api/meetings/{s.meeting_id}/agenda/assignable-plans")
        assert reader.status_code == 403
    entry = (await audit_actions(maker, target_id=s.meeting_id))[-1]
    assert (entry.action, entry.data["planVersionId"]) == ("agenda_item_add", str(vid))


async def test_a_plan_on_the_agenda_of_a_closed_meeting_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/finance/budget/000838: a closed meeting takes no plan."""
    s = await seed(maker, status="closed", items=0)
    vid = await _waiting(maker, s.gremium_id)
    with TestClient(api) as client:
        resp = client.post(
            f"/api/meetings/{s.meeting_id}/agenda", json={"planVersionId": str(vid)}
        )
    assert (resp.status_code, resp.json()["code"]) == (409, "meeting_closed"), resp.text


async def test_the_item_of_a_plan_takes_one_motion_of_the_members(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/finance/budget/000838: no election, no poll, no guests and no second vote."""
    s = await seed(maker, status="planned", items=0)
    vid = await _waiting(maker, s.gremium_id)
    with TestClient(api) as client:
        item = _add(client, s, vid)
        base = {"agendaItemId": item["id"], "question": "Plan?", "draft": True}
        for extra, code in (
            ({"kind": "election", "seats": 1, "candidates": [{"name": "A"}, {"name": "B"}]},
             "plan_item_motion_only"),
            (
                {
                    "kind": "poll",
                    "poll": {"mode": "single", "options": [{"label": "A"}, {"label": "B"}]},
                },
                "plan_item_motion_only",
            ),
            ({"guestsVote": True}, "guests_vote_unavailable"),
        ):
            refused = client.post(f"/api/meetings/{s.meeting_id}/votes", json={**base, **extra})
            assert refused.status_code == 422, refused.text
            assert refused.json()["code"] == code

        made = client.post(f"/api/meetings/{s.meeting_id}/votes", json=base)
        assert made.status_code == 200, made.text
        [vote] = made.json()["votes"]
        assert (vote["status"], vote["guestsVote"]) == ("draft", False)
        async with maker() as session:
            row = await session.get_one(Vote, uuid.UUID(vote["id"]))
            assert (row.plan_version_id, row.application_id) == (vid, None)
        second = client.post(f"/api/meetings/{s.meeting_id}/votes", json=base)
        assert (second.status_code, second.json()["code"]) == (409, "agenda_decision_vote_exists")

        async with maker() as session:
            await BudgetTreeService(session, actor="tester").set_plan_state(
                vid, PlanStateSet(state="draft")
            )
            await session.commit()
            assert await session.get(Vote, uuid.UUID(vote["id"])) is None
            assert await session.get(MeetingAgendaItem, uuid.UUID(str(item["id"]))) is not None
        late = client.post(f"/api/meetings/{s.meeting_id}/votes", json=base)
        assert (late.status_code, late.json()["code"]) == (409, "plan_step_not_waiting")


@pytest.mark.parametrize(("choice", "state"), [("yes", "in_force_ready"), ("no", "draft")])
async def test_the_vote_of_the_meeting_decides_the_step(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, choice: str, state: str
) -> None:
    """An accepted vote passes the step, a refused vote sends the version back to the draft.

    Rules: §F/finance/budget/000838, §F/finance/budget/000826.
    """
    s = await seed(maker, status="live", items=0)
    vid = await _waiting(maker, s.gremium_id)
    with TestClient(api) as client:
        item = _add(client, s, vid)
        made = client.post(
            f"/api/meetings/{s.meeting_id}/votes",
            json={"agendaItemId": item["id"], "question": "Plan?", "draft": True},
        )
        [vote] = made.json()["votes"]
        vote_id = uuid.UUID(vote["id"])
        async with maker() as session:
            await VotingService(session).open(vote_id, now=datetime.now(UTC), actor="mgr")
        blocked = client.delete(f"/api/meetings/{s.meeting_id}/agenda/{item['id']}")
        assert blocked.status_code == 409
    async with maker() as session:
        voting = VotingService(session)
        await voting.cast(
            vote_id,
            Principal(sub="v1", groups={vote_group_key(s.gremium_id)}),
            choice,
            now=datetime.now(UTC),
        )
        await voting.close(vote_id, Principal(sub="mgr", roles=["admin"]))
        version = await session.get_one(BudgetPlanVersion, vid)
        await session.refresh(version)
        if state == "draft":
            assert (version.state, version.steps) == ("draft", [])
        else:
            assert version.state == "in_progress"
            assert version.steps[0]["passedAt"] is not None
            assert version.steps[0]["voteId"] == str(vote_id)
        rows = (
            await session.scalars(
                select(MeetingAgendaItem).where(MeetingAgendaItem.plan_version_id == vid)
            )
        ).all()
        assert len(rows) == 1


async def test_a_removed_plan_item_goes_into_another_meeting(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/finance/budget/000838: the step still waits after its agenda item is removed."""
    s = await seed(maker, status="planned", items=0)
    vid = await _waiting(maker, s.gremium_id)
    with TestClient(api) as client:
        item = _add(client, s, vid)
        removed = client.delete(f"/api/meetings/{s.meeting_id}/agenda/{item['id']}")
        assert removed.status_code == 200, removed.text
        assert removed.json() == []
        assert await _state(maker, vid) == "in_progress"
        again = _add(client, s, vid)
        assert again["id"] != item["id"]


async def test_a_draft_is_an_agenda_item_for_a_reading(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/finance/budget/000876: a draft goes on the agenda once, and takes no vote."""
    s = await seed(maker, status="planned", items=0)
    draft = await _waiting(maker, s.gremium_id, ask=False)
    with TestClient(api) as client:
        offered = _offered(client, s)["plans"]
        [row] = [p for p in offered if p["planVersionId"] == str(draft)]
        assert (row["reading"], row["step"]) == (True, "Lesung")
        assert row["title"] == "Haushaltsplan VS-Mittel 2026: Lesung"

        item = _add(client, s, draft)
        assert (item["title"], item["planReading"]) == (row["title"], True)
        assert await _state(maker, draft) == "draft"
        left = _offered(client, s)["plans"]
        assert str(draft) not in {p["planVersionId"] for p in left}
        twice = client.post(
            f"/api/meetings/{s.meeting_id}/agenda", json={"planVersionId": str(draft)}
        )
        assert (twice.status_code, twice.json()["code"]) == (409, "plan_already_on_agenda")
        vote = client.post(
            f"/api/meetings/{s.meeting_id}/votes",
            json={"agendaItemId": item["id"], "question": "Plan?", "draft": True},
        )
        assert (vote.status_code, vote.json()["code"]) == (409, "plan_step_not_waiting")
        other = await seed(maker, status="planned", items=0)
        elsewhere = client.post(
            f"/api/meetings/{other.meeting_id}/agenda", json={"planVersionId": str(draft)}
        )
        assert (elsewhere.status_code, elsewhere.json()["code"]) == (409, "plan_step_not_waiting")

        async with maker() as session:
            await BudgetTreeService(session, actor="tester").request_step(draft)
            await session.commit()
        [asked] = [
            i
            for i in client.get(f"/api/meetings/{s.meeting_id}/agenda").json()
            if i["planVersionId"] == str(draft)
        ]
        assert asked["planReading"] is False


def _pdf() -> bytes:
    """Return a PDF of one empty page, as the render service gives one for a plan."""
    out = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=842, height=595)
    writer.write(out)
    return out.getvalue()


class _Storage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]


class _Typst:
    """Keeps each request. A plan gives a real PDF, because the platform stores it."""

    def __init__(self) -> None:
        self.plans: list[str] = []
        self.protocols: list[str] = []

    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        config: Mapping[str, object] | None = None,
        assets: Mapping[str, bytes] | None = None,
    ) -> bytes:
        if variant != "plan":
            self.protocols.append(markdown)
            return b"%PDF-protocol"
        self.plans.append(json.dumps(config, ensure_ascii=False))
        return _pdf()


async def _set_first_expense(
    maker: async_sessionmaker[AsyncSession], vid: uuid.UUID, amount: str
) -> None:
    """Change the Ansatz of one leaf line of a draft."""
    async with maker() as session:
        line = (
            await session.scalars(
                select(BudgetPlanLine)
                .where(BudgetPlanLine.version_id == vid, BudgetPlanLine.amount == Decimal(60))
                .limit(1)
            )
        ).one()
        await BudgetTreeService(session, actor="tester").set_line(
            vid, line.budget_id, PlanLineSet(amount=Decimal(amount))
        )
        await session.commit()


async def test_the_protocol_appends_the_plans_of_its_agenda(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """A voted plan is appended as the vote saw it, a draft for a reading as it is now.

    Rule: §F/finance/budget/000876.
    """
    s = await seed(maker, status="live", items=1, protocol="draft")
    voted = await _waiting(maker, s.gremium_id)
    reading = await _waiting(maker, s.gremium_id, ask=False)
    with TestClient(api) as client:
        item = _add(client, s, voted)
        read_item = _add(client, s, reading)
        made = client.post(
            f"/api/meetings/{s.meeting_id}/votes",
            json={"agendaItemId": item["id"], "question": "Plan?", "draft": True},
        )
        vote_id = uuid.UUID(made.json()["votes"][0]["id"])
    async with maker() as session:
        voting = VotingService(session)
        await voting.open(vote_id, now=datetime.now(UTC), actor="mgr")
        await voting.cast(
            vote_id,
            Principal(sub="v1", groups={vote_group_key(s.gremium_id)}),
            "no",
            now=datetime.now(UTC),
        )
        await voting.close(vote_id, Principal(sub="mgr", roles=["admin"]))
    assert await _state(maker, voted) == "draft"
    await _set_first_expense(maker, voted, "11.11")
    await _set_first_expense(maker, reading, "22.22")

    storage, typst = _Storage(), _Typst()
    assert s.protocol_id is not None
    async with maker() as session:
        svc = ProtocolService(
            session, storage=cast("ObjectStorage", storage), typst=cast("TypstClient", typst)
        )
        await svc.finalize(s.protocol_id, now=datetime.now(UTC))
    async with maker() as session:
        rows = {
            row.id: row
            for row in (
                await session.scalars(
                    select(MeetingAgendaItem).where(MeetingAgendaItem.meeting_id == s.meeting_id)
                )
            ).all()
        }
        plain, of_vote, of_reading = (
            rows[s.item_ids[0]],
            rows[uuid.UUID(str(item["id"]))],
            rows[uuid.UUID(str(read_item["id"]))],
        )
        assert plain.plan_document_id is None
        assert of_vote.plan_document_id is not None
        assert of_reading.plan_document_id is not None
    by_vote, by_reading = typst.plans
    assert "60,00" in by_vote and "11,11" not in by_vote
    assert "22,22" in by_reading
    assert '"mark": "Beschluss"' in by_vote and '"mark": "Entwurf"' in by_reading
    internal = typst.protocols[0]
    for row in (of_vote, of_reading):
        assert f"(/api/media/documents/{row.plan_document_id})" in internal
        assert f"media/documents/{row.plan_document_id}" in storage.blobs
    assert "Haushaltsplan_VS-Mittel_2026_Entwurf.pdf" in internal
