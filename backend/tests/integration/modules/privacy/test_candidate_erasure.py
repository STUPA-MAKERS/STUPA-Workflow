"""F2 · Erasure of a principal from the candidate lists, against a real Postgres.

``PrincipalService.erase`` replaces the name of each candidacy of the principal who was
not elected with ``Gelöscht``, in ``vote.config`` (JSONB) and in the election callouts
of the protocol text and the agenda item bodies. An elected candidacy keeps the name,
the ballots and the stored results stay. Two elections of the meeting share the head
line of their callout (no question, so both read ``**Wahlgang**``): the person lost
the one and won the other, so only the callout of the lost election changes. A third
election names an old account that an admin merged into the erased one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import Gremium
from app.modules.auth.models import Principal
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.privacy.service import PrincipalService
from app.modules.protocol.markdown import build_election_snippet
from app.modules.protocol.models import Protocol
from app.modules.protocol.service import election_snippet_of
from app.modules.voting.erasure import ERASED_CANDIDATE_NAME
from app.modules.voting.models import Ballot, Vote
from app.modules.voting.schemas import ElectionResultOut
from app.modules.voting.tally import encode_election_choice
from app.shared.config_schemas import ElectionConfig
from tests.integration.conftest import clear_privacy_tables

pytestmark = pytest.mark.integration

NAME = "Max Muster"
OLD_NAME = "Max Alt"


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # ``engine`` truncates meeting, vote, ballot, protocol and the audit chain;
    # the helper truncates the principals.
    clear_privacy_tables(engine)
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


def _config(*candidates: tuple[str, str, uuid.UUID]) -> dict[str, Any]:
    return ElectionConfig.model_validate(
        {
            "seats": 1,
            "secret": False,
            "candidates": [
                {"id": cid, "name": name, "principalId": str(pid)} for cid, name, pid in candidates
            ],
        }
    ).model_dump(by_alias=True, mode="json")


def _callout(config: dict[str, Any], result: dict[str, Any]) -> str:
    """Build the internal callout as ``embed_votes`` writes it."""
    return build_election_snippet(
        election_snippet_of(
            ElectionConfig.model_validate(config),
            ElectionResultOut.model_validate(result),
            question=None,
            round_=1,
        )
    )


def _yes_no(yes: int, no: int, *, elected: bool) -> dict[str, Any]:
    return {
        "counts": {"c1": yes},
        "abstentions": 0,
        "ballots": yes + no,
        "yes": yes,
        "no": no,
        "elected": ["c1"] if elected else [],
    }


async def test_erase_replaces_only_the_names_of_lost_candidacies(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        person = Principal(sub=f"kc-{tag}", email=f"max-{tag}@x.de", display_name=NAME)
        other = Principal(sub=f"kc-o-{tag}", email=f"o-{tag}@x.de", display_name="Erika")
        session.add_all([person, other])
        await session.flush()
        old_account = Principal(
            sub=f"kc-old-{tag}",
            display_name=OLD_NAME,
            active=False,
            merged_into=person.id,
            merged_at=datetime.now(UTC),
        )
        gremium = Gremium(name="StuPa", slug=f"stupa-{tag}")
        session.add_all([old_account, gremium])
        await session.flush()
        meeting = Meeting(
            gremium_id=gremium.id,
            title="Sitzung",
            date=date(2026, 6, 20),
            start_time=time(18, 0),
            status="live",
        )
        session.add(meeting)
        await session.flush()
        item = MeetingAgendaItem(meeting_id=meeting.id, title="TOP 1", position=0)
        session.add(item)
        await session.flush()

        single = _config(("c1", NAME, person.id))
        lost_result = _yes_no(1, 4, elected=False)
        won_result = _yes_no(4, 1, elected=True)
        merged_config = _config(("c1", OLD_NAME, old_account.id), ("c2", "Erika", other.id))
        merged_result = {
            "counts": {"c1": 2, "c2": 3},
            "abstentions": 0,
            "ballots": 5,
            "elected": ["c2"],
        }

        def election(config: dict[str, Any], result: dict[str, Any], won: bool) -> Vote:
            return Vote(
                application_id=None,
                meeting_id=meeting.id,
                agenda_item_id=item.id,
                eligible_group=str(gremium.id),
                kind="election",
                question=None,
                round=1,
                config=config,
                status="closed",
                result="elected" if won else "rejected",
                election_result=result,
            )

        lost = election(single, lost_result, False)
        won = election(single, won_result, True)
        merged = election(merged_config, merged_result, True)
        session.add_all([lost, won, merged])
        await session.flush()
        for n, choice in enumerate(["yes", "no", "no", "no", "no"]):
            session.add(Ballot(vote_id=lost.id, voter_sub=f"v{n}", choice=choice))
        for n, choice in enumerate(["yes", "yes", "yes", "yes", "no"]):
            session.add(Ballot(vote_id=won.id, voter_sub=f"v{n}", choice=choice))
        for n, cid in enumerate(["c1", "c1", "c2", "c2", "c2"]):
            session.add(
                Ballot(vote_id=merged.id, voter_sub=f"v{n}", choice=encode_election_choice([cid]))
            )

        lost_callout = _callout(single, lost_result)
        won_callout = _callout(single, won_result)
        merged_callout = _callout(merged_config, merged_result)
        # Both callouts of the person open with the same head line.
        assert lost_callout.split("\n")[0] == won_callout.split("\n")[0]
        # The won callout follows the lost one without a blank line.
        markdown = f"# Sitzung\n\n{lost_callout}\n{won_callout}\n\nEnde\n"
        protocol = Protocol(meeting_id=meeting.id, gremium_id=gremium.id, markdown=markdown)
        item.body = f"Wahl:\n\n{merged_callout}\n"
        session.add(protocol)
        await session.commit()
        ids = (person.id, lost.id, won.id, merged.id, protocol.id, item.id)

    async with maker() as session:
        before = {
            (b.vote_id, b.voter_sub, b.choice) for b in (await session.scalars(select(Ballot)))
        }
        await PrincipalService(session).erase(ids[0], actor="admin")

    async with maker() as session:
        votes = {v.id: v for v in await session.scalars(select(Vote).where(Vote.id.in_(ids[1:4])))}
        lost_row, won_row, merged_row = votes[ids[1]], votes[ids[2]], votes[ids[3]]
        assert lost_row.config["candidates"][0]["name"] == ERASED_CANDIDATE_NAME
        assert lost_row.config["candidates"][0]["principalId"] == str(ids[0])
        assert won_row.config["candidates"][0]["name"] == NAME
        names = {c["id"]: c["name"] for c in merged_row.config["candidates"]}
        assert names == {"c1": ERASED_CANDIDATE_NAME, "c2": "Erika"}
        # The stored results and the ballots stay: the tally does not change.
        assert lost_row.election_result == lost_result
        assert won_row.election_result == won_result
        assert merged_row.election_result == merged_result
        after = {
            (b.vote_id, b.voter_sub, b.choice) for b in (await session.scalars(select(Ballot)))
        }
        assert after == before
        assert len(after) == 15

        stored = await session.get(Protocol, ids[4])
        assert stored is not None
        erased_callout = lost_callout.replace(NAME, ERASED_CANDIDATE_NAME)
        assert stored.markdown == f"# Sitzung\n\n{erased_callout}\n{won_callout}\n\nEnde\n"
        agenda = await session.get(MeetingAgendaItem, ids[5])
        assert agenda is not None
        assert (
            agenda.body == f"Wahl:\n\n{merged_callout.replace(OLD_NAME, ERASED_CANDIDATE_NAME)}\n"
        )
        assert OLD_NAME not in (agenda.body or "")
