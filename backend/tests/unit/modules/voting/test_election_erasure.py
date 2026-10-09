"""F2 · Erasure of a principal from the candidate lists of the elections.

A candidate who was not elected (or whose election is not decided) gets the name
``Gelöscht``; an elected candidate keeps the name. The ballots, the candidate ids and
the stored result never change, so the tally stays the same.
"""

from __future__ import annotations

import copy
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.dialects import postgresql

from app.modules.voting.erasure import _MAX_PASSES, ERASED_CANDIDATE_NAME, erase_candidacies
from app.modules.voting.models import Vote
from app.shared.config_schemas import ElectionConfig
from tests._support.privacy_fakes import FakeResult, FakeSession

PID = uuid4()
OTHER = uuid4()


class _Session(FakeSession):
    """Privacy fake session that keeps the statements of ``scalars``.

    The first ``scalars`` call reads the merged accounts, each later one is a pass of
    the locked election select (an empty default ends the passes).
    """

    def __init__(self, *passes: list[Vote], merged: tuple[UUID, ...] = ()) -> None:
        super().__init__(scalars=[FakeResult(merged), *(FakeResult(p) for p in passes)])
        self.statements: list[Any] = []

    async def scalars(self, stmt: Any) -> FakeResult:
        self.statements.append(stmt)
        return await super().scalars(stmt)


def _candidates(*, mine: str = "c1") -> list[dict[str, Any]]:
    return [
        {"id": mine, "name": "Anna Erased", "principalId": str(PID)},
        {"id": "c8", "name": "Ben", "principalId": str(OTHER)},
        {"id": "c9", "name": "Cem", "principalId": None},
    ]


def _election(
    *,
    status: str = "closed",
    elected: list[str] | None = None,
    result: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    parent: UUID | None = None,
    round_: int = 1,
) -> Vote:
    stored = result
    if stored is None and elected is not None:
        stored = {"counts": {"c1": 3, "c8": 5, "c9": 1}, "elected": elected}
    return Vote(
        id=uuid4(),
        kind="election",
        status=status,
        config={"seats": 1, "candidates": candidates or _candidates(), "secret": True},
        election_result=stored,
        parent_vote_id=parent,
        round=round_,
        meeting_id=uuid4(),
        question="Wahl",
    )


def _names(vote: Vote) -> dict[str, str]:
    return {c["id"]: c["name"] for c in vote.config["candidates"]}


async def _erase(*votes: Vote) -> tuple[list[Any], _Session]:
    db = _Session(list(votes))
    changed = await erase_candidacies(db, PID)  # pyright: ignore[reportArgumentType]
    return changed, db


def _sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


async def test_query_selects_the_elections_of_the_principal_by_containment() -> None:
    _, db = await _erase()
    assert "principal.merged_into =" in _sql(db.statements[0])
    sql = _sql(db.statements[1])
    assert "vote.kind =" in sql
    assert sql.count("vote.config @>") == 1
    assert "NOT IN" not in sql
    assert "FOR UPDATE" in sql
    # The first pass found nothing, so no second pass runs.
    assert len(db.statements) == 2


async def test_elected_candidate_keeps_the_name() -> None:
    vote = _election(elected=["c1"])
    before = copy.deepcopy(vote.config)
    changed, _ = await _erase(vote)
    assert changed == []
    assert vote.config == before


async def test_not_elected_candidate_gets_the_placeholder() -> None:
    vote = _election(elected=["c8"])
    result_before = copy.deepcopy(vote.election_result)
    old = vote.config
    changed, _ = await _erase(vote)
    assert [c.vote for c in changed] == [vote]
    assert changed[0].old_config is old
    assert _names(vote) == {"c1": ERASED_CANDIDATE_NAME, "c8": "Ben", "c9": "Cem"}
    # The id, the account link and the result stay: the tally does not change.
    mine = vote.config["candidates"][0]
    assert mine["id"] == "c1"
    assert mine["principalId"] == str(PID)
    assert vote.election_result == result_before
    assert vote.config["seats"] == 1
    # The marker tells the UI to show its own label; the others carry none.
    assert mine["erased"] is True
    assert [c.get("erased") for c in vote.config["candidates"][1:]] == [None, None]
    # The old config stays as it was, for the protocol rewrite.
    assert old["candidates"][0]["name"] == "Anna Erased"
    assert "erased" not in old["candidates"][0]


async def test_open_election_is_undecided_and_gets_the_placeholder() -> None:
    vote = _election(status="open")
    changed, _ = await _erase(vote)
    assert len(changed) == 1
    assert _names(vote)["c1"] == ERASED_CANDIDATE_NAME


async def test_pending_lot_is_undecided_and_gets_the_placeholder() -> None:
    vote = _election(
        result={
            "counts": {"c1": 3, "c8": 3},
            "elected": [],
            "lot": {"among": ["c1", "c8"], "seats": 1, "drawn": None},
        }
    )
    changed, _ = await _erase(vote)
    assert len(changed) == 1
    assert _names(vote)["c1"] == ERASED_CANDIDATE_NAME


async def test_result_without_elected_key_counts_as_not_elected() -> None:
    vote = _election(result={"counts": {"c1": 0}})
    changed, _ = await _erase(vote)
    assert len(changed) == 1


async def test_pending_runoff_without_a_runoff_vote_gets_the_placeholder() -> None:
    parent = _election(
        result={
            "counts": {"c1": 2, "c8": 2},
            "elected": [],
            "runoff": {"candidateIds": ["c1", "c8"], "seats": 1},
        }
    )
    changed, _ = await _erase(parent)
    assert len(changed) == 1
    assert _names(parent)["c1"] == ERASED_CANDIDATE_NAME


async def test_win_in_the_runoff_keeps_the_name_in_every_round() -> None:
    parent = _election(
        result={
            "counts": {"c1": 2, "c8": 2},
            "elected": [],
            "runoff": {"candidateIds": ["c1", "c8"], "seats": 1},
        }
    )
    child = _election(elected=["c1"], parent=parent.id, round_=2)
    changed, _ = await _erase(child, parent)
    assert changed == []
    assert _names(parent)["c1"] == "Anna Erased"
    assert _names(child)["c1"] == "Anna Erased"


async def test_loss_in_the_runoff_replaces_the_name_in_every_round() -> None:
    parent = _election(
        result={
            "counts": {"c1": 2, "c8": 2},
            "elected": [],
            "runoff": {"candidateIds": ["c1", "c8"], "seats": 1},
        }
    )
    child = _election(elected=["c8"], parent=parent.id, round_=2)
    grandchild_open = _election(status="open", parent=child.id, round_=3)
    changed, _ = await _erase(parent, child, grandchild_open)
    assert {c.vote.id for c in changed} == {parent.id, child.id, grandchild_open.id}
    for vote in (parent, child, grandchild_open):
        assert _names(vote)["c1"] == ERASED_CANDIDATE_NAME


async def test_runoff_whose_parent_is_gone_stands_alone() -> None:
    # The parent row is deleted (or not found), so the runoff is its own election.
    child = _election(status="open", parent=uuid4(), round_=2)
    changed, _ = await _erase(child)
    assert [c.vote for c in changed] == [child]


async def test_parent_cycle_ends_the_walk() -> None:
    a = _election(status="open")
    b = _election(status="open", parent=a.id, round_=2)
    a.parent_vote_id = b.id
    changed, _ = await _erase(a, b)
    assert len(changed) == 2


async def test_person_who_is_not_a_candidate_changes_nothing() -> None:
    vote = _election(
        elected=["c8"],
        candidates=[
            {"id": "c8", "name": "Ben", "principalId": str(OTHER)},
            {"id": "c9", "name": "Cem"},
        ],
    )
    before = copy.deepcopy(vote.config)
    changed, _ = await _erase(vote)
    assert changed == []
    assert vote.config == before


async def test_config_without_candidates_changes_nothing() -> None:
    vote = _election(status="open")
    vote.config = {"seats": 1}
    changed, _ = await _erase(vote)
    assert changed == []


async def test_no_election_changes_nothing() -> None:
    changed, _ = await _erase()
    assert changed == []


async def test_name_only_candidate_with_the_same_name_stays() -> None:
    # A candidate without an account link never matches, even with the same name.
    vote = _election(
        elected=["c8"],
        candidates=[
            {"id": "c1", "name": "Anna Erased", "principalId": str(PID)},
            {"id": "c8", "name": "Ben", "principalId": str(OTHER)},
            {"id": "c9", "name": "Anna Erased"},
        ],
    )
    await _erase(vote)
    assert _names(vote) == {"c1": ERASED_CANDIDATE_NAME, "c8": "Ben", "c9": "Anna Erased"}


async def test_second_erasure_finds_nothing_to_change() -> None:
    vote = _election(elected=["c8"])
    await _erase(vote)
    changed, _ = await _erase(vote)
    assert changed == []


async def test_placeholder_name_without_the_marker_gets_the_marker() -> None:
    # The marker decides, not the name: a stored placeholder without the marker
    # (or a person really named so) gets the marker; the name stays the placeholder.
    vote = _election(
        elected=["c8"],
        candidates=[
            {"id": "c1", "name": ERASED_CANDIDATE_NAME, "principalId": str(PID)},
            {"id": "c8", "name": "Ben", "principalId": str(OTHER)},
        ],
    )
    changed, _ = await _erase(vote)
    assert [c.vote for c in changed] == [vote]
    assert vote.config["candidates"][0] == {
        "id": "c1",
        "name": ERASED_CANDIDATE_NAME,
        "principalId": str(PID),
        "erased": True,
    }


async def test_erased_config_validates_and_carries_the_marker() -> None:
    vote = _election(elected=["c8"])
    await _erase(vote)
    config = ElectionConfig.model_validate(vote.config)
    assert [c.erased for c in config.candidates] == [True, False, False]
    # The beamer form drops the account links and keeps the marker.
    dumped = config.public().model_dump(mode="json", by_alias=True)
    assert [c["erased"] for c in dumped["candidates"]] == [True, False, False]
    assert [c["principalId"] for c in dumped["candidates"]] == [None, None, None]


async def test_multiple_elections_each_decide_on_their_own() -> None:
    won = _election(elected=["c1"])
    lost = _election(elected=["c8"])
    open_ = _election(status="open")
    other_id = _election(elected=["c4"], candidates=_candidates(mine="c4"))
    changed, _ = await _erase(won, lost, open_, other_id)
    assert {c.vote.id for c in changed} == {lost.id, open_.id}
    assert _names(won)["c1"] == "Anna Erased"
    assert _names(lost)["c1"] == ERASED_CANDIDATE_NAME
    assert _names(open_)["c1"] == ERASED_CANDIDATE_NAME
    # The candidate id of the principal differs per election; the account link decides.
    assert _names(other_id)["c4"] == "Anna Erased"


# --- merged accounts -------------------------------------------------------------------

MERGED = uuid4()


def _merged_candidates(*, mine: str = "c1") -> list[dict[str, Any]]:
    return [
        {"id": mine, "name": "Anna Old Account", "principalId": str(MERGED)},
        {"id": "c8", "name": "Ben", "principalId": str(OTHER)},
    ]


async def test_candidacy_of_a_merged_account_gets_the_placeholder() -> None:
    # The merge leaves ``principalId`` of the old account in the candidate list.
    lost = _election(elected=["c8"], candidates=_merged_candidates())
    db = _Session([lost], merged=(MERGED,))
    changed = await erase_candidacies(db, PID)  # pyright: ignore[reportArgumentType]
    assert [c.vote for c in changed] == [lost]
    assert _names(lost) == {"c1": ERASED_CANDIDATE_NAME, "c8": "Ben"}
    assert lost.config["candidates"][0]["principalId"] == str(MERGED)
    # One containment clause per account id, joined with OR.
    sql = _sql(db.statements[1])
    assert sql.count("vote.config @>") == 2
    assert " OR " in sql


async def test_win_of_a_merged_account_keeps_the_name() -> None:
    won = _election(elected=["c1"], candidates=_merged_candidates())
    before = copy.deepcopy(won.config)
    db = _Session([won], merged=(MERGED,))
    changed = await erase_candidacies(db, PID)  # pyright: ignore[reportArgumentType]
    assert changed == []
    assert won.config == before


async def test_both_accounts_in_one_election_change_together() -> None:
    # The old and the new account both stand in one election; neither won.
    vote = _election(
        elected=["c8"],
        candidates=[
            {"id": "c1", "name": "Anna", "principalId": str(PID)},
            {"id": "c2", "name": "Anna Old", "principalId": str(MERGED)},
            {"id": "c8", "name": "Ben", "principalId": str(OTHER)},
        ],
    )
    db = _Session([vote], merged=(MERGED,))
    changed = await erase_candidacies(db, PID)  # pyright: ignore[reportArgumentType]
    assert len(changed) == 1
    assert _names(vote) == {
        "c1": ERASED_CANDIDATE_NAME,
        "c2": ERASED_CANDIDATE_NAME,
        "c8": "Ben",
    }


async def test_win_of_one_account_keeps_both_names_in_the_election() -> None:
    vote = _election(
        elected=["c2"],
        candidates=[
            {"id": "c1", "name": "Anna", "principalId": str(PID)},
            {"id": "c2", "name": "Anna Old", "principalId": str(MERGED)},
        ],
    )
    db = _Session([vote], merged=(MERGED,))
    assert await erase_candidacies(db, PID) == []  # pyright: ignore[reportArgumentType]


# --- a runoff that a parallel transaction inserted ------------------------------------


async def test_runoff_found_in_a_later_pass_joins_the_decision() -> None:
    # The first select waited for the parent lock of a parallel ``create_runoff``; its
    # snapshot misses the new runoff, which the second pass finds. A win there keeps
    # the name in the parent too.
    parent = _election(
        result={
            "counts": {"c1": 2, "c8": 2},
            "elected": [],
            "runoff": {"candidateIds": ["c1", "c8"], "seats": 1},
        }
    )
    child = _election(elected=["c1"], parent=parent.id, round_=2)
    db = _Session([parent], [child])
    changed = await erase_candidacies(db, PID)  # pyright: ignore[reportArgumentType]
    assert changed == []
    assert _names(parent)["c1"] == "Anna Erased"
    # The second pass leaves out the rows it holds; the third finds nothing.
    assert len(db.statements) == 4
    second = db.statements[2]
    assert "NOT IN" in _sql(second)
    assert "FOR UPDATE" in _sql(second)


async def test_draft_runoff_found_in_a_later_pass_gets_the_placeholder() -> None:
    parent = _election(
        result={
            "counts": {"c1": 2, "c8": 2},
            "elected": [],
            "runoff": {"candidateIds": ["c1", "c8"], "seats": 1},
        }
    )
    child = _election(status="draft", parent=parent.id, round_=2)
    db = _Session([parent], [child])
    changed = await erase_candidacies(db, PID)  # pyright: ignore[reportArgumentType]
    assert {c.vote.id for c in changed} == {parent.id, child.id}
    assert _names(child)["c1"] == ERASED_CANDIDATE_NAME


async def test_passes_stop_at_the_bound() -> None:
    rounds = [[_election(status="open")] for _ in range(_MAX_PASSES + 2)]
    db = _Session(*rounds)
    changed = await erase_candidacies(db, PID)  # pyright: ignore[reportArgumentType]
    # One principal select and ``_MAX_PASSES`` election selects, no more.
    assert len(db.statements) == 1 + _MAX_PASSES
    assert len(changed) == _MAX_PASSES
