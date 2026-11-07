"""The config of a meeting vote from the body of the dialog.

The create of a meeting vote (``POST /meetings/{id}/votes``) and the change of a
prepared draft (``PUT /meetings/{id}/votes/{voteId}``) take the same body and build
the same config, so a changed draft passes the same checks as a new one: guests vote
only where the meeting and the agenda item let them, an election and a poll belong to
a free-text agenda item, every vote is secret, and the quorum
denominator comes from the roster.
"""

from __future__ import annotations

from app.modules.livevote.models import MeetingAgendaItem
from app.modules.livevote.schemas import MeetingOut, MeetingVoteBody
from app.modules.livevote.service import MeetingService
from app.modules.livevote.vote_open import eligible_count
from app.modules.voting.poll import build_config as build_poll_config
from app.modules.voting.schemas import VoteCreateInternal
from app.modules.voting.service import secret_only
from app.shared.config_schemas import ElectionConfig, PollConfig, VoteConfig
from app.shared.errors import ValidationProblem


def _vote_config(
    payload: MeetingVoteBody,
    config_data: dict[str, object],
    *,
    election: bool,
    guests_vote: bool,
) -> VoteConfig | ElectionConfig | PollConfig:
    """Validate the config of the vote kind: a poll, an election or a motion."""
    match (payload.poll, election):
        case (None, True):
            return ElectionConfig.model_validate(config_data)
        case (None, False):
            return VoteConfig.model_validate(config_data)
        case (poll, _):
            return build_poll_config(
                poll,
                secret=secret_only(payload.secret, field="secret"),
                guests_vote=guests_vote,
            )


async def build_meeting_vote(
    service: MeetingService,
    meeting: MeetingOut,
    item: MeetingAgendaItem,
    payload: MeetingVoteBody,
) -> VoteCreateInternal:
    """Check the body against the meeting and the agenda item and build the vote.

    The admitted guests vote by default in a meeting where guests vote, on a public
    item, and never in an election unless the lead switches them on. A vote with
    guests and a poll have no quorum; without an explicit percent the vote inherits
    the percent quorum of the Gremium.

    Raises:
        ValidationProblem: Guests cannot vote here (``guests_vote_unavailable``,
            ``guests_vote_non_public``), an election or a poll is on an application
            item, a motion or an election is open (``open_vote_unavailable``), or a
            candidate account does not exist.
    """
    guests_allowed = meeting.public_join and meeting.guests_mode == "vote"
    if payload.guests_vote and not guests_allowed:
        raise ValidationProblem(
            "Guests do not vote in this meeting.",
            code="guests_vote_unavailable",
            errors=[{"field": "guestsVote", "msg": "the meeting does not let guests vote"}],
        )
    if payload.guests_vote and item.non_public:
        raise ValidationProblem(
            "Guests never vote on a non-public agenda item.",
            code="guests_vote_non_public",
            errors=[{"field": "guestsVote", "msg": "non-public agenda item"}],
        )
    election = payload.kind == "election"
    if election and item.application_id is not None:
        raise ValidationProblem(
            "An election belongs to a free-text agenda item.",
            code="election_on_application_item",
            errors=[{"field": "kind", "msg": "an application agenda item"}],
        )
    if payload.poll is not None and item.application_id is not None:
        raise ValidationProblem(
            "A poll belongs to a free-text agenda item.",
            code="poll_on_application_item",
            errors=[{"field": "kind", "msg": "an application agenda item"}],
        )
    guests_vote = (
        payload.guests_vote
        if payload.guests_vote is not None
        else guests_allowed and not item.non_public and not election
    )
    base: dict[str, object] = (
        {
            "seats": payload.seats,
            "candidates": payload.election_candidates(),
            "secret": secret_only(payload.secret, field="secret"),
            "guestsVote": guests_vote,
        }
        if election
        else {
            "options": payload.options,
            "majorityRule": payload.majority_rule,
            "secret": secret_only(payload.secret, field="secret"),
            "tieBreak": "rejected",
            "guestsVote": guests_vote,
        }
    )
    quorum_percent = (
        None
        if guests_vote or payload.poll is not None
        else payload.quorum_percent
        if payload.quorum_percent is not None
        else await service.gremium_quorum_percent(meeting.gremium_id)
    )
    quorum: dict[str, object] = (
        {} if quorum_percent is None else {"quorum": {"type": "percent", "value": quorum_percent}}
    )
    config_data = {**base, **quorum}
    if election:
        await service.assert_candidates_exist(
            [c.principal_id for c in payload.candidates if c.principal_id is not None]
        )
    return VoteCreateInternal(
        config=_vote_config(payload, config_data, election=election, guests_vote=guests_vote),
        eligibleGroup=meeting.gremium_id,
        question=payload.question,
        eligibleCount=await eligible_count(service, meeting, guests_vote=guests_vote),
        proposal=payload.proposal,
    )
