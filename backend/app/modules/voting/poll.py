"""Polls ("Umfrage"): ballot shape, stored result, the poll of a Gremium and the edit.

A poll is a ``vote`` row with ``kind = 'poll'``. ``vote.config`` holds a
``PollConfig`` (mode, options, ``maxChoices``, secret, guests). A poll only counts the
answers: no quorum, no majority, no lot, no runoff, no application and no flow branch.
It shares the life cycle of a vote (draft -> open -> closed / cancelled), the
race-safe ballot tables, the secret path and the reveal rule. The differences live
here:

* The ballot: a single poll takes ``[optionId]`` or ``[]`` (abstention), a multi
  poll 0 to ``maxChoices`` option ids, a date poll ``yes``/``maybe``/``no`` for every
  option.
* The close: ``tally.tally_poll`` counts; the vote stores ``poll_result`` and keeps
  ``result`` NULL.
* The poll of a Gremium (``POST /votes``): no meeting, a planned end (``closesAt``, at
  least one hour ahead), created by a holder of ``vote.manage`` in the Gremium. The
  deadline cron closes it at its end.
* The edit (``PATCH /votes/{id}``): question, options and end, only while the poll
  holds no ballot (409 ``poll_has_answers``).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pydantic

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.voting import tally as tally_mod
from app.modules.voting.models import Vote
from app.modules.voting.schemas import (
    MyBallot,
    PollCreate,
    PollIn,
    PollPatch,
    PollResultOut,
    VoteCreateInternal,
    VoteOut,
)
from app.shared.config_schemas import PollConfig
from app.shared.errors import ConflictError, ForbiddenError, ValidationProblem

if TYPE_CHECKING:
    from app.modules.voting.service import VotingService

POLL = "poll"

# 409 codes of the edit.
NOT_A_POLL = "not_a_poll"
POLL_HAS_ANSWERS = "poll_has_answers"
POLL_NOT_EDITABLE = "poll_not_editable"

# The end of a poll of a Gremium lies at least this far ahead (create, edit and open).
MIN_RUNTIME = timedelta(hours=1)

_DATE_ANSWERS = frozenset({"yes", "maybe", "no"})


def is_poll(vote: object) -> bool:
    """Tell whether a vote row is a poll. A row without ``kind`` is a motion."""
    return getattr(vote, "kind", "motion") == POLL


def poll_config(vote: Vote) -> PollConfig:
    """Validate the stored ``PollConfig`` of a poll row."""
    return PollConfig.model_validate(vote.config)


def build_config(data: PollIn, *, secret: bool, guests_vote: bool = False) -> PollConfig:
    """Build the stored config of a poll with the server-side option ids.

    Raises:
        ValidationProblem: The options do not fit the mode (422 ``poll_invalid``).
    """
    try:
        return data.config(secret=secret, guests_vote=guests_vote)
    except pydantic.ValidationError as exc:
        raise ValidationProblem(
            "The options do not fit the poll.",
            code="poll_invalid",
            errors=[{"field": "options", "msg": str(err["msg"])} for err in exc.errors()],
        ) from exc


def _invalid_choice(msg: str) -> ValidationProblem:
    return ValidationProblem("Invalid poll ballot.", errors=[{"field": "choice", "msg": msg}])


def stored_choice(config: PollConfig, choice: str | list[str] | Mapping[str, str]) -> str:
    """Check a poll ballot and return its stored form.

    Raises:
        ValidationProblem: The ballot does not fit the poll (422).
    """
    known = set(config.option_ids)
    if config.mode == "date":
        if not isinstance(choice, Mapping):
            raise _invalid_choice("an answer for every date")
        if set(choice) != known:
            raise _invalid_choice("an answer for every date")
        if not set(choice.values()) <= _DATE_ANSWERS:
            raise _invalid_choice("yes, maybe or no")
        return tally_mod.encode_poll_answers(choice)
    if not isinstance(choice, list):
        raise _invalid_choice("a list of option ids")
    if len(set(choice)) != len(choice):
        raise _invalid_choice("an option is chosen twice")
    if len(choice) > config.choice_limit:
        raise _invalid_choice("too many options")
    if not set(choice) <= known:
        raise _invalid_choice("unknown option")
    return tally_mod.encode_election_choice(choice)


def own_ballot(choice: str | None) -> MyBallot:
    """Build the own ballot of an open poll row (a cast ``ballot`` row)."""
    picks = tally_mod.decode_election_choice(choice)
    if picks is not None:
        return MyBallot(cast=True, choices=picks)
    answers = tally_mod.decode_poll_answers(choice)
    if answers is not None:
        return MyBallot.model_validate({"cast": True, "answers": answers})
    return MyBallot(cast=True, choice=choice)


def result_of(outcome: tally_mod.PollOutcome) -> PollResultOut:
    """Build the result of a poll from its tally."""
    return PollResultOut(
        counts=dict(outcome.counts),
        maybe=dict(outcome.maybe) if outcome.maybe is not None else None,
        abstentions=outcome.abstentions,
        ballots=outcome.ballots,
        order=list(outcome.order),
        top=list(outcome.top),
    )


def dump_result(result: PollResultOut) -> dict[str, Any]:
    """Return the JSONB form of a poll result."""
    return result.model_dump(mode="json", by_alias=True)


def poll_fields(vote: Vote, live: PollResultOut | None = None) -> dict[str, Any]:
    """Return the poll fields of ``VoteOut`` for a vote row (empty for another kind).

    A closed poll carries its stored result; ``live`` is the revealed count of an
    open poll.
    """
    if not is_poll(vote):
        return {}
    stored = getattr(vote, "poll_result", None)
    return {
        "kind": POLL,
        "poll": poll_config(vote),
        "pollResult": PollResultOut.model_validate(stored) if stored else live,
    }


def audit_data(vote: Vote, config: PollConfig) -> dict[str, Any]:
    """Return the audit data of a poll: id references, mode and option count."""
    return {
        "meetingId": str(vote.meeting_id) if vote.meeting_id else None,
        "eligibleGroup": vote.eligible_group,
        "kind": POLL,
        "mode": config.mode,
        "options": len(config.options),
        "secret": config.secret,
    }


def _check_end(closes_at: datetime, now: datetime) -> None:
    """Require a planned end at least one hour ahead (tz-aware).

    Raises:
        ValidationProblem: The end is naive or too soon (422 ``closes_at_too_soon``).
    """
    if closes_at.tzinfo is None or closes_at < now + MIN_RUNTIME:
        raise ValidationProblem(
            "The poll ends at least one hour from now.",
            code="closes_at_too_soon",
            errors=[{"field": "closesAt", "msg": "at least one hour ahead"}],
        )


class PollService:
    """The poll of a Gremium and the edit of a poll, on a ``VotingService`` session."""

    def __init__(self, voting: VotingService) -> None:
        self.voting = voting
        self.session = voting.session

    async def can_create(self, gremium_id: UUID, principal: Principal) -> bool:
        """Tell whether the principal creates a poll in this Gremium.

        The admin role (``admin_bypass`` with ``vote.manage``) or the gremium
        permission ``vote.manage`` (scope-capped through ``gremium_ids_for``).
        """
        from app.modules.admin.gremium_roles import admin_bypass, gremium_ids_for

        if admin_bypass(principal, "vote.manage"):
            return True
        return gremium_id in await gremium_ids_for(self.session, principal, "vote.manage")

    async def create(self, payload: PollCreate, principal: Principal, *, now: datetime) -> VoteOut:
        """Create the poll of a Gremium, as a draft or open at once.

        The eligible voters are the members with ``vote.cast`` in the Gremium (the
        roster count). Without ``draft`` the poll opens in the same call, with a
        ``vote_open`` audit entry.

        Raises:
            ForbiddenError: The principal lacks ``vote.manage`` in the Gremium (403).
            ValidationProblem: The Gremium does not exist (``eligible_group_invalid``),
                the end is too soon (``closes_at_too_soon``) or the options do not fit
                the mode (``poll_invalid``) (422).
        """
        gremium_id = payload.eligible_group
        if not await self.voting._gremium_exists(gremium_id):
            raise ValidationProblem(
                "eligibleGroup is not the id of a gremium.",
                code="eligible_group_invalid",
                errors=[{"field": "eligibleGroup", "msg": "unknown gremium"}],
            )
        if not await self.can_create(gremium_id, principal):
            raise ForbiddenError("not allowed to create a poll in this gremium")
        _check_end(payload.closes_at, now)
        config = build_config(payload, secret=payload.secret)
        from app.modules.livevote.service import MeetingService

        eligible = await MeetingService(self.session).vote_eligible_count(gremium_id)
        internal = VoteCreateInternal(
            config=config,
            eligibleGroup=gremium_id,
            question=payload.question,
            eligibleCount=eligible,
            closesAt=payload.closes_at,
        )
        created = await self.voting._insert(None, internal, actor=principal.sub)
        if payload.draft:
            return created
        return await self.voting.open(created.id, now=now, actor=principal.sub)

    async def check_open(self, vote: Vote, now: datetime) -> None:
        """Check the planned end of a poll of a Gremium before it opens.

        A draft can wait past its end; the creator moves the end first.

        Raises:
            ValidationProblem: The end is missing or too soon (``closes_at_too_soon``).
        """
        if not is_poll(vote) or vote.meeting_id is not None:
            return
        if vote.closes_at is None:
            raise ValidationProblem(
                "A poll of a Gremium needs its end.",
                code="closes_at_too_soon",
                errors=[{"field": "closesAt", "msg": "missing"}],
            )
        _check_end(vote.closes_at, now)

    async def patch(
        self, vote_id: UUID, payload: PollPatch, principal: Principal, *, now: datetime
    ) -> VoteOut:
        """Change the question, the options or the end of a poll without a ballot.

        New options replace every option and get new ids; the mode stays. The end
        moves only for a poll without a meeting, at least one hour ahead. The caller
        checks the manage right. Writes ``poll_updated``.

        Raises:
            ConflictError: The vote is no poll (``not_a_poll``), it ended
                (``poll_not_editable``) or it holds a ballot (``poll_has_answers``).
            ValidationProblem: The options do not fit (``poll_invalid``), or the end is
                too soon or belongs to a meeting poll (``closes_at_too_soon``).
        """
        vote = await self.voting._get_vote(vote_id, for_update=True)
        if not is_poll(vote):
            raise ConflictError("The vote is no poll.", code=NOT_A_POLL)
        if vote.status not in ("draft", "open"):
            raise ConflictError("The poll has ended.", code=POLL_NOT_EDITABLE)
        if await self.voting._ballot_count(vote.id) > 0:
            raise ConflictError(
                "The poll holds answers; its options are fixed.", code=POLL_HAS_ANSWERS
            )
        config = poll_config(vote)
        changed: list[str] = []
        if payload.question is not None:
            question = payload.question.strip()
            if not question:
                raise ValidationProblem(
                    "The question is empty.",
                    code="poll_invalid",
                    errors=[{"field": "question", "msg": "empty"}],
                )
            vote.question = question
            changed.append("question")
        if payload.options is not None or "max_choices" in payload.model_fields_set:
            data = PollIn.model_validate(
                {
                    "mode": config.mode,
                    "options": (
                        [o.model_dump(by_alias=True, exclude_none=True) for o in payload.options]
                        if payload.options is not None
                        else [
                            o.model_dump(by_alias=True, exclude_none=True, exclude={"id"})
                            for o in config.options
                        ]
                    ),
                    "maxChoices": (
                        payload.max_choices
                        if "max_choices" in payload.model_fields_set
                        else config.max_choices
                    ),
                }
            )
            config = build_config(data, secret=config.secret, guests_vote=config.guests_vote)
            vote.config = config.model_dump(mode="json", by_alias=True)
            changed.append("options")
        if payload.closes_at is not None:
            if vote.meeting_id is not None:
                raise ValidationProblem(
                    "A meeting poll ends with its close in the meeting.",
                    code="closes_at_too_soon",
                    errors=[{"field": "closesAt", "msg": "a meeting poll"}],
                )
            _check_end(payload.closes_at, now)
            vote.closes_at = payload.closes_at
            vote.reminded_at = None
            changed.append("closesAt")
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.POLL_UPDATED,
            target_type="vote",
            target_id=str(vote.id),
            data={**audit_data(vote, config), "changed": changed},
        )
        await self.session.commit()
        return await self.voting.get(vote.id)
