"""Polls ("Umfrage") in the voting module, without a database.

A result-queue fake drives every poll branch: the config rules, the tally of the three
modes, the ballot shapes, the own ballot, the read with the running count, the create
of a poll of a Gremium, the open check, the close and the edit.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pydantic
import pytest

from app.modules.auth import policy
from app.modules.auth.principal import Principal
from app.modules.voting import poll as poll_mod
from app.modules.voting.election import own_ballot as any_ballot
from app.modules.voting.poll import PollService
from app.modules.voting.schemas import (
    MyBallot,
    PollCreate,
    PollIn,
    PollPatch,
    PollResultOut,
    VoteCreateInternal,
    VoteOut,
)
from app.modules.voting.service import VotingService
from app.modules.voting.tally import (
    decode_poll_answers,
    encode_poll_answers,
    tally_poll,
)
from app.shared.config_schemas import PollConfig, VoteConfig
from app.shared.errors import ConflictError, ForbiddenError, ValidationProblem
from tests._support.flow_fakes import fake_session, result
from tests.unit.modules.voting.test_voting_service_unit import (  # noqa: F401 - fixture
    GID,
    NOW,
    _FakeFlow,
    _patch_flow,
    _vote,
    _voter,
)

D1 = "2026-11-02T18:00:00+01:00"
D2 = "2026-11-03T18:00:00+01:00"
D3 = "2026-11-04T18:00:00+01:00"


def _options(n: int = 3) -> list[dict[str, Any]]:
    return [{"id": f"o{i}", "label": f"Option {i}"} for i in range(1, n + 1)]


def _dates() -> list[dict[str, Any]]:
    return [
        {"id": "o1", "start": D1, "end": "2026-11-02T20:00:00+01:00"},
        {"id": "o2", "start": D2},
        {"id": "o3", "start": D3},
    ]


def _pcfg(mode: str = "single", **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "mode": mode,
        "options": _dates() if mode == "date" else _options(),
    }
    data.update(over)
    return PollConfig.model_validate(data).model_dump(mode="json", by_alias=True)


def _pvote(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "application_id": None,
        "kind": "poll",
        "question": "Wohin?",
        "config": _pcfg(),
        "poll_result": None,
        "reminded_at": None,
        "present_members": None,
        "present_guests": None,
        "closes_at": NOW + timedelta(days=3),
    }
    base.update(over)
    return _vote(**base)


def _audits(db: Any) -> list[Any]:
    return [a for a in db.added if type(a).__name__ == "AuditEntry"]


def _cfg(mode: str = "single", **over: Any) -> PollConfig:
    return PollConfig.model_validate(_pcfg(mode, **over))


# ---------------------------------------------------------------- config


def test_config_projection_of_the_modes() -> None:
    single = _cfg()
    assert single.option_ids == ["o1", "o2", "o3"]
    assert single.choice_limit == 1
    assert single.as_vote_config().options == ["o1", "o2", "o3", "abstain"]
    assert _cfg("multi").choice_limit == 3
    assert _cfg("multi", maxChoices=2).choice_limit == 2
    date = _cfg("date")
    assert date.as_vote_config().options == ["o1", "o2", "o3"]
    assert date.as_vote_config().quorum is None


def test_config_from_stored_reads_a_poll() -> None:
    projected = VoteConfig.from_stored(_pcfg(secret=True))
    assert projected.secret is True
    assert projected.options[-1] == "abstain"


@pytest.mark.parametrize(
    "data",
    [
        {"mode": "single", "options": [{"id": "o1", "label": "A"}, {"id": "o1", "label": "B"}]},
        {"mode": "single", "options": [{"id": "o1", "label": "A"}, {"id": "o2", "start": D1}]},
        {"mode": "single", "options": [{"id": "o1", "label": "A"}, {"id": "o2"}]},
        {"mode": "date", "options": [{"id": "o1", "start": D1}, {"id": "o2", "label": "B"}]},
        {"mode": "date", "options": [{"id": "o1", "start": D1}, {"id": "o2", "end": D2}]},
        {
            "mode": "date",
            "options": [{"id": "o1", "start": D2, "end": D1}, {"id": "o2", "start": D1}],
        },
        {"mode": "single", "options": _options(2), "maxChoices": 1},
        {"mode": "multi", "options": _options(2), "maxChoices": 3},
        {"mode": "single", "options": [{"id": "o1", "label": "  "}, {"id": "o2", "label": "B"}]},
        {"mode": "single", "options": [{"id": "x1", "label": "A"}, {"id": "o2", "label": "B"}]},
        {"mode": "single", "options": _options(1)},
        {"mode": "single", "options": _options(21)},
        {
            "mode": "date",
            "options": [{"id": "o1", "start": "2026-11-02T18:00:00"}, {"id": "o2", "start": D1}],
        },
    ],
)
def test_config_refuses_a_bad_poll(data: dict[str, Any]) -> None:
    with pytest.raises(pydantic.ValidationError):
        PollConfig.model_validate(data)


def test_config_strips_the_labels() -> None:
    config = PollConfig.model_validate(
        {"mode": "single", "options": [{"id": "o1", "label": " A "}, {"id": "o2", "label": "B"}]}
    )
    assert config.options[0].label == "A"


def test_poll_in_numbers_the_options() -> None:
    data = PollIn.model_validate(
        {"mode": "multi", "options": [{"label": "A"}, {"label": "B"}], "maxChoices": 2}
    )
    config = data.config(secret=True, guests_vote=True)
    assert config.option_ids == ["o1", "o2"]
    assert config.secret is True
    assert config.guests_vote is True


def test_poll_create_refuses_an_empty_question() -> None:
    body = {
        "eligibleGroup": str(GID),
        "mode": "single",
        "options": [{"label": "A"}, {"label": "B"}],
        "closesAt": (NOW + timedelta(days=1)).isoformat(),
    }
    assert PollCreate.model_validate({**body, "question": " Q "}).question == "Q"
    with pytest.raises(pydantic.ValidationError):
        PollCreate.model_validate({**body, "question": "   "})


def test_internal_create_of_a_poll_has_no_quorum() -> None:
    payload = VoteCreateInternal(config=_cfg(), eligibleGroup=GID)
    assert isinstance(payload.config, PollConfig)


# ---------------------------------------------------------------- tally


def test_answers_round_trip() -> None:
    raw = encode_poll_answers({"o2": "no", "o1": "yes"})
    assert raw == '{"o1":"yes","o2":"no"}'
    assert decode_poll_answers(raw) == {"o1": "yes", "o2": "no"}
    assert decode_poll_answers(None) is None
    assert decode_poll_answers("not json") is None
    assert decode_poll_answers('["o1"]') is None
    assert decode_poll_answers('{"o1": 1}') is None


def test_tally_single_counts_ranks_and_ties() -> None:
    out = tally_poll(['["o2"]', '["o3"]', "[]", '["o2","o2"]', '["zz"]', None], _cfg())
    assert out.counts == {"o1": 0, "o2": 2, "o3": 1}
    assert out.abstentions == 3
    assert out.ballots == 6
    assert out.order == ("o2", "o3", "o1")
    assert out.top == ("o2",)
    assert out.display_counts() == {"o1": 0, "o2": 2, "o3": 1, "abstain": 3}


def test_tally_multi_caps_the_picks_and_marks_every_tied_top() -> None:
    out = tally_poll(['["o1","o2","o3"]', '["o3"]'], _cfg("multi", maxChoices=2))
    assert out.counts == {"o1": 1, "o2": 1, "o3": 1}
    assert out.top == ("o1", "o2", "o3")


def test_tally_without_votes_has_no_top() -> None:
    assert tally_poll([], _cfg()).top == ()
    assert tally_poll([], _cfg("date")).top == ()


def test_tally_date_ranks_by_yes_then_maybe() -> None:
    ballots = [
        encode_poll_answers({"o1": "yes", "o2": "maybe", "o3": "yes"}),
        encode_poll_answers({"o1": "maybe", "o2": "yes", "o3": "yes"}),
        encode_poll_answers({"o1": "yes", "o2": "no", "o3": "maybe", "zz": "yes"}),
        "broken",
    ]
    out = tally_poll(ballots, _cfg("date"))
    assert out.counts == {"o1": 2, "o2": 1, "o3": 2}
    assert out.maybe == {"o1": 1, "o2": 1, "o3": 1}
    assert out.order == ("o1", "o3", "o2")
    assert out.top == ("o1", "o3")
    assert out.ballots == 4
    assert out.display_counts() == {"o1": 2, "o2": 1, "o3": 2}


def test_tally_date_with_maybe_only_still_has_a_best_date() -> None:
    out = tally_poll([encode_poll_answers({"o1": "no", "o2": "maybe", "o3": "no"})], _cfg("date"))
    assert out.order[0] == "o2"
    assert out.top == ("o2",)


# ---------------------------------------------------------------- helpers


def test_build_config_wraps_the_error_in_422() -> None:
    data = PollIn.model_validate({"mode": "single", "options": [{"label": "A"}, {"start": D1}]})
    with pytest.raises(ValidationProblem) as err:
        poll_mod.build_config(data, secret=False)
    assert err.value.code == "poll_invalid"


@pytest.mark.parametrize(
    ("mode", "choice"),
    [
        ("date", ["o1"]),
        ("date", {"o1": "yes"}),
        ("date", {"o1": "yes", "o2": "yes", "o3": "perhaps"}),
        ("single", "o1"),
        ("multi", ["o1", "o1"]),
        ("single", ["o1", "o2"]),
        ("single", ["zz"]),
    ],
)
def test_stored_choice_refuses_a_bad_ballot(mode: str, choice: Any) -> None:
    with pytest.raises(ValidationProblem):
        poll_mod.stored_choice(_cfg(mode), choice)


def test_stored_choice_forms() -> None:
    assert poll_mod.stored_choice(_cfg("multi"), ["o3", "o1"]) == '["o1","o3"]'
    assert poll_mod.stored_choice(_cfg(), []) == "[]"
    answers = {"o3": "no", "o1": "yes", "o2": "maybe"}
    assert poll_mod.stored_choice(_cfg("date"), answers) == '{"o1":"yes","o2":"maybe","o3":"no"}'


def test_own_ballot_shapes() -> None:
    assert poll_mod.own_ballot('["o1"]') == MyBallot(cast=True, choices=["o1"])
    assert poll_mod.own_ballot('{"o1":"yes"}') == MyBallot.model_validate(
        {"cast": True, "answers": {"o1": "yes"}}
    )
    assert poll_mod.own_ballot("odd") == MyBallot(cast=True, choice="odd")
    assert any_ballot("poll", '["o2"]') == MyBallot(cast=True, choices=["o2"])


def test_poll_fields_and_audit_data() -> None:
    assert poll_mod.poll_fields(_vote()) == {}  # type: ignore[arg-type]
    assert poll_mod.is_poll(SimpleNamespace()) is False
    stored = {"counts": {"o1": 1}, "ballots": 1, "order": ["o1"], "top": ["o1"]}
    fields = poll_mod.poll_fields(_pvote(poll_result=stored))  # type: ignore[arg-type]
    assert fields["kind"] == "poll"
    assert fields["pollResult"].counts == {"o1": 1}
    live = PollResultOut(counts={"o1": 0})
    assert poll_mod.poll_fields(_pvote(), live)["pollResult"] is live  # type: ignore[arg-type]
    data = poll_mod.audit_data(_pvote(meeting_id=uuid4()), _cfg())  # type: ignore[arg-type]
    assert data["mode"] == "single" and data["options"] == 3
    assert data["meetingId"] is not None
    assert poll_mod.audit_data(_pvote(), _cfg())["meetingId"] is None  # type: ignore[arg-type]


def test_result_of_keeps_maybe_none_outside_the_date_mode() -> None:
    out = poll_mod.result_of(tally_poll(['["o1"]'], _cfg()))
    assert out.maybe is None
    dated = poll_mod.result_of(tally_poll([], _cfg("date")))
    assert dated.maybe == {"o1": 0, "o2": 0, "o3": 0}
    assert poll_mod.dump_result(out)["counts"] == {"o1": 1, "o2": 0, "o3": 0}


# ---------------------------------------------------------------- cast


async def test_cast_single_poll_stores_the_list() -> None:
    vote = _pvote()
    db = fake_session(result(vote), result(uuid4()))
    out = await VotingService(db).cast(vote.id, _voter(), ["o2"], now=NOW)
    assert out.status == "cast"
    assert db.statements[-1].compile().params["choice"] == '["o2"]'


async def test_cast_date_poll_stores_the_answers() -> None:
    vote = _pvote(config=_pcfg("date"))
    db = fake_session(result(vote), result(uuid4()))
    answers = {"o1": "yes", "o2": "no", "o3": "maybe"}
    await VotingService(db).cast(vote.id, _voter(), answers, now=NOW)
    assert db.statements[-1].compile().params["choice"] == '{"o1":"yes","o2":"no","o3":"maybe"}'


async def test_cast_secret_poll_keeps_the_choice_apart() -> None:
    vote = _pvote(config=_pcfg("multi", secret=True))
    db = fake_session(result(vote), result(uuid4()))
    await VotingService(db).cast(vote.id, _voter(), [], now=NOW)
    [secret] = [a for a in db.added if type(a).__name__ == "SecretBallot"]
    assert secret.choice == "[]"


async def test_cast_poll_refuses_a_bad_ballot() -> None:
    vote = _pvote()
    with pytest.raises(ValidationProblem):
        await VotingService(fake_session(result(vote))).cast(vote.id, _voter(), "o1", now=NOW)


async def test_cast_motion_refuses_date_answers() -> None:
    vote = _vote()
    with pytest.raises(ValidationProblem):
        await VotingService(fake_session(result(vote))).cast(
            vote.id, _voter(), {"yes": "yes"}, now=NOW
        )


# ---------------------------------------------------------------- read


async def test_get_open_poll_shows_the_running_count() -> None:
    vote = _pvote(config=_pcfg("date"))
    ballot = encode_poll_answers({"o1": "yes", "o2": "maybe", "o3": "no"})
    db = fake_session(result(vote), result(ballot), result(ballot), result(ballot))
    out = await VotingService(db).get(vote.id)
    assert out.kind == "poll"
    assert out.poll is not None and out.poll.mode == "date"
    assert out.tally.revealed is True
    assert out.tally.counts == {"o1": 1, "o2": 0, "o3": 0}
    assert out.tally.voted == 1
    assert out.tally.quorum_met is True
    assert out.poll_result is not None
    assert out.poll_result.maybe == {"o1": 0, "o2": 1, "o3": 0}
    assert out.poll_result.top == ["o1"]


async def test_get_open_secret_poll_hides_the_count() -> None:
    vote = _pvote(config=_pcfg(secret=True))
    db = fake_session(result(vote), result('["o1"]'), result('["o1"]'))
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is False
    assert out.tally.counts == {}
    assert out.poll_result is None


async def test_get_draft_poll_has_no_running_count() -> None:
    vote = _pvote(status="draft")
    out = await VotingService(fake_session(result(vote))).get(vote.id)
    assert out.poll_result is None


async def test_get_closed_poll_carries_the_stored_result() -> None:
    stored = poll_mod.dump_result(poll_mod.result_of(tally_poll(['["o3"]'], _cfg())))
    vote = _pvote(status="closed", poll_result=stored, closed_at=NOW)
    db = fake_session(result(vote), result('["o3"]'), result('["o3"]'))
    out = await VotingService(db).get(vote.id)
    assert out.result is None
    assert out.poll_result is not None and out.poll_result.top == ["o3"]


# ---------------------------------------------------------------- create


async def test_create_internal_poll_writes_kind_config_and_audit() -> None:
    payload = VoteCreateInternal(
        config=_cfg("date"), eligibleGroup=GID, eligibleCount=5, question="Wann?"
    )
    db = fake_session()
    out = await VotingService(db).create_internal(None, payload, actor="mgr")
    [vote] = [a for a in db.added if type(a).__name__ == "Vote"]
    assert vote.kind == "poll"
    assert vote.config["options"][0]["start"] == D1
    assert out.kind == "poll"
    assert out.config.options == ["o1", "o2", "o3"]
    [entry] = _audits(db)
    assert entry.action == "poll_created"
    assert entry.actor == "mgr"
    assert entry.data["mode"] == "date"


def _create_body(**over: Any) -> PollCreate:
    data: dict[str, Any] = {
        "eligibleGroup": str(GID),
        "question": "Wohin?",
        "mode": "single",
        "options": [{"label": "A"}, {"label": "B"}],
        "closesAt": (NOW + timedelta(days=2)).isoformat(),
    }
    data.update(over)
    return PollCreate.model_validate(data)


@pytest.fixture
def manage(monkeypatch: pytest.MonkeyPatch) -> set[UUID]:
    """Stub the gremium ids where the principal holds ``vote.manage``."""
    ids: set[UUID] = {GID}

    async def _ids_for(_s: Any, _p: Principal, perm: str, _now: object = None) -> set[UUID]:
        assert perm == "vote.manage"
        return ids

    monkeypatch.setattr(policy, "held_gremium_ids", _ids_for)
    return ids


async def test_create_poll_as_draft(manage: set[UUID]) -> None:
    db = fake_session(result((uuid4(), ["vote.cast"]), (uuid4(), ["vote.read"])))
    db.scalar_results = [GID]
    out = await PollService(VotingService(db)).create(
        _create_body(draft=True), Principal(sub="mgr"), now=NOW
    )
    assert out.status == "draft"
    assert out.tally.eligible == 1
    assert out.closes_at == NOW + timedelta(days=2)
    assert out.meeting_id is None
    assert [e.action for e in _audits(db)] == ["poll_created"]


async def test_create_poll_opens_at_once(manage: set[UUID]) -> None:
    db = fake_session()
    db.scalar_results = [GID]
    voting = VotingService(db)
    opened: list[tuple[UUID, str | None]] = []

    async def _open(vote_id: UUID, *, now: Any, actor: str | None = None) -> VoteOut:
        opened.append((vote_id, actor))
        return VoteOut.model_validate({"id": vote_id, "status": "open", **_OUT})

    voting.open = _open  # type: ignore[method-assign]
    out = await PollService(voting).create(_create_body(), Principal(sub="mgr"), now=NOW)
    assert out.status == "open"
    assert opened and opened[0][1] == "mgr"


_OUT: dict[str, Any] = {
    "eligibleGroup": str(GID),
    "config": _cfg().as_vote_config().model_dump(by_alias=True),
    "secret": False,
    "tally": {"counts": {}, "eligible": 0, "voted": 0, "quorumMet": True},
}


async def test_create_poll_as_admin_needs_no_gremium_right() -> None:
    db = fake_session()
    db.scalar_results = [GID]
    admin = Principal(sub="adm", roles=["admin"])
    out = await PollService(VotingService(db)).create(_create_body(draft=True), admin, now=NOW)
    assert out.status == "draft"


async def test_create_poll_in_an_unknown_gremium_422(manage: set[UUID]) -> None:
    with pytest.raises(ValidationProblem) as err:
        await PollService(VotingService(fake_session())).create(
            _create_body(), Principal(sub="mgr"), now=NOW
        )
    assert err.value.code == "eligible_group_invalid"


async def test_create_poll_without_the_right_403(manage: set[UUID]) -> None:
    manage.clear()
    db = fake_session()
    db.scalar_results = [GID]
    with pytest.raises(ForbiddenError):
        await PollService(VotingService(db)).create(_create_body(), Principal(sub="m"), now=NOW)


@pytest.mark.parametrize(
    "closes_at",
    [(NOW + timedelta(minutes=30)).isoformat(), "2026-06-10T12:00:00"],
)
async def test_create_poll_with_an_early_or_naive_end_422(
    manage: set[UUID], closes_at: str
) -> None:
    db = fake_session()
    db.scalar_results = [GID]
    with pytest.raises(ValidationProblem) as err:
        await PollService(VotingService(db)).create(
            _create_body(closesAt=closes_at), Principal(sub="mgr"), now=NOW
        )
    assert err.value.code == "closes_at_too_soon"


async def test_create_poll_with_bad_options_422(manage: set[UUID]) -> None:
    db = fake_session()
    db.scalar_results = [GID]
    with pytest.raises(ValidationProblem) as err:
        await PollService(VotingService(db)).create(
            _create_body(mode="date"), Principal(sub="mgr"), now=NOW
        )
    assert err.value.code == "poll_invalid"


# ---------------------------------------------------------------- open


async def test_open_gremium_poll_audits_the_kind() -> None:
    vote = _pvote(status="draft")
    db = fake_session(result(vote))
    out = await VotingService(db).open(vote.id, now=NOW, actor="mgr")
    assert out.status == "open"
    [entry] = _audits(db)
    assert entry.action == "vote_open"
    assert entry.data["kind"] == "poll"


@pytest.mark.parametrize("closes_at", [None, NOW + timedelta(minutes=10)])
async def test_open_gremium_poll_needs_its_end_ahead(closes_at: Any) -> None:
    vote = _pvote(status="draft", closes_at=closes_at)
    with pytest.raises(ValidationProblem) as err:
        await VotingService(fake_session(result(vote))).open(vote.id, now=NOW)
    assert err.value.code == "closes_at_too_soon"
    assert vote.status == "draft"


async def test_open_check_skips_a_meeting_poll_and_a_motion() -> None:
    service = PollService(VotingService(fake_session()))
    await service.check_open(_pvote(meeting_id=uuid4(), closes_at=None), NOW)  # type: ignore[arg-type]
    await service.check_open(_vote(), NOW)  # type: ignore[arg-type]


# ---------------------------------------------------------------- close


@pytest.mark.usefixtures("_patch_flow")
async def test_close_gremium_poll_stores_the_result() -> None:
    vote = _pvote(config=_pcfg("multi"))
    db = fake_session(result(vote), result('["o1","o2"]', '["o2"]', "[]"))
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.result is None
    assert out.kind == "poll"
    assert out.branch_fired is False
    assert out.poll_result is not None and out.poll_result.top == ["o2"]
    assert out.tally.voted == 3
    assert out.tally.counts == {"o1": 1, "o2": 2, "o3": 0, "abstain": 1}
    assert out.tally.present_members is None
    assert vote.status == "closed"
    assert vote.result is None
    assert vote.poll_result["counts"] == {"o1": 1, "o2": 2, "o3": 0}
    assert _FakeFlow.branch_calls == []
    [entry] = _audits(db)
    assert entry.action == "vote_close"
    assert entry.data["kind"] == "poll"
    assert entry.data["ballots"] == 3


async def test_close_poll_without_now_stamps_the_time() -> None:
    vote = _pvote()
    out = await VotingService(fake_session(result(vote))).close(vote.id, _voter())
    assert out.closed_at is not None


async def test_close_meeting_poll_fixes_the_attendance() -> None:
    vote = _pvote(meeting_id=uuid4())
    db = fake_session(result(vote), result('["o1"]'))
    db.scalar_results = [4, 2]  # present members, admitted guests
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.tally.present_members == 4
    assert out.tally.present_guests == 2
    assert out.tally.eligible == 10


async def test_close_meeting_poll_with_guests_counts_them_as_eligible() -> None:
    vote = _pvote(meeting_id=uuid4(), config=_pcfg(guestsVote=True))
    db = fake_session(
        result(vote),
        result('["o1"]'),
        result(uuid4()),  # admitted guests
        result(),  # guest ballots
        result(),  # guest markers
    )
    db.scalar_results = [3]  # present members
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.tally.eligible == 4
    assert vote.eligible_count == 4


# ---------------------------------------------------------------- edit


async def test_patch_changes_question_options_and_end() -> None:
    vote = _pvote(config=_pcfg("multi", maxChoices=2), reminded_at=NOW)
    db = fake_session(result(vote), result(), result(), result(vote))  # audit: lock, prev hash
    end = NOW + timedelta(days=5)
    payload = PollPatch.model_validate(
        {
            "question": " Neu? ",
            "options": [{"label": "X"}, {"label": "Y"}],
            "maxChoices": None,
            "closesAt": end.isoformat(),
        }
    )
    out = await PollService(VotingService(db)).patch(vote.id, payload, _voter(), now=NOW)
    assert vote.question == "Neu?"
    assert [o["label"] for o in vote.config["options"]] == ["X", "Y"]
    assert vote.config["maxChoices"] is None
    assert vote.closes_at == end
    assert vote.reminded_at is None
    assert out.kind == "poll"
    [entry] = _audits(db)
    assert entry.action == "poll_updated"
    assert entry.data["changed"] == ["question", "options", "closesAt"]


async def test_patch_max_choices_keeps_the_options() -> None:
    vote = _pvote(config=_pcfg("multi"))
    db = fake_session(result(vote), result(), result(), result(vote))  # audit: lock, prev hash
    payload = PollPatch.model_validate({"maxChoices": 2})
    await PollService(VotingService(db)).patch(vote.id, payload, _voter(), now=NOW)
    assert vote.config["maxChoices"] == 2
    assert [o["label"] for o in vote.config["options"]] == ["Option 1", "Option 2", "Option 3"]


async def test_patch_date_options_keep_the_dates() -> None:
    vote = _pvote(config=_pcfg("date"))
    db = fake_session(result(vote), result(), result(), result(vote))  # audit: lock, prev hash
    payload = PollPatch.model_validate({"options": [{"start": D2}, {"start": D3}]})
    await PollService(VotingService(db)).patch(vote.id, payload, _voter(), now=NOW)
    assert [o["id"] for o in vote.config["options"]] == ["o1", "o2"]


async def test_patch_without_a_field_only_audits() -> None:
    vote = _pvote()
    db = fake_session(result(vote), result(), result(), result(vote))  # audit: lock, prev hash
    await PollService(VotingService(db)).patch(vote.id, PollPatch(), _voter(), now=NOW)
    [entry] = _audits(db)
    assert entry.data["changed"] == []


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"kind": "motion"}, "not_a_poll"),
        ({"status": "closed"}, "poll_not_editable"),
    ],
)
async def test_patch_refuses_a_motion_and_an_ended_poll(over: dict[str, Any], code: str) -> None:
    vote = _pvote(**over)
    with pytest.raises(ConflictError) as err:
        await PollService(VotingService(fake_session(result(vote)))).patch(
            vote.id, PollPatch(), _voter(), now=NOW
        )
    assert err.value.code == code


async def test_patch_with_answers_409() -> None:
    vote = _pvote()
    db = fake_session(result(vote))
    db.scalar_results = [0, 0, 1]
    with pytest.raises(ConflictError) as err:
        await PollService(VotingService(db)).patch(vote.id, PollPatch(), _voter(), now=NOW)
    assert err.value.code == "poll_has_answers"


async def test_patch_empty_question_422() -> None:
    vote = _pvote()
    payload = PollPatch.model_validate({"question": "  "})
    with pytest.raises(ValidationProblem) as err:
        await PollService(VotingService(fake_session(result(vote)))).patch(
            vote.id, payload, _voter(), now=NOW
        )
    assert err.value.code == "poll_invalid"


async def test_patch_end_of_a_meeting_poll_422() -> None:
    vote = _pvote(meeting_id=uuid4(), closes_at=None)
    payload = PollPatch.model_validate({"closesAt": (NOW + timedelta(days=1)).isoformat()})
    with pytest.raises(ValidationProblem) as err:
        await PollService(VotingService(fake_session(result(vote)))).patch(
            vote.id, payload, _voter(), now=NOW
        )
    assert err.value.code == "closes_at_too_soon"
    assert vote.closes_at is None


async def test_patch_end_too_soon_422() -> None:
    vote = _pvote()
    payload = PollPatch.model_validate({"closesAt": (NOW + timedelta(minutes=5)).isoformat()})
    with pytest.raises(ValidationProblem):
        await PollService(VotingService(fake_session(result(vote)))).patch(
            vote.id, payload, _voter(), now=NOW
        )
