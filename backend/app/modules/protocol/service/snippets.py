"""The Markdown snippets of votes, elections and polls in a protocol."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from app.modules.protocol.markdown import (
    ElectionLine,
    ElectionSnippet,
    PollLine,
    PollSnippet,
    build_election_snippet,
    build_poll_snippet,
    build_vote_snippet,
    guest_vote_note,
)
from app.modules.protocol.public import passed_conditions
from app.modules.voting.models import Vote
from app.modules.voting.schemas import ElectionResultOut, PollResultOut, VoteOut
from app.shared.config_schemas import ElectionConfig, PollConfig, PollOption


def _snippet(
    view: VoteOut, fallback: str, *, public: bool = False, tz: ZoneInfo | None = None
) -> str:
    """Build the protocol callout of a vote: a motion, an election or a poll.

    ``tz`` is the local time zone of the dates of a date poll.
    """
    match getattr(view, "kind", "motion"):
        case "election" if view.election is not None:
            return build_election_snippet(_election_snippet(view), public=public)
        case "poll" if view.poll is not None:
            return build_poll_snippet(
                poll_snippet_of(
                    view.poll,
                    view.poll_result if view.status == "closed" else None,
                    question=_with_attempt(view.question or "Umfrage", view),
                    tz=tz or ZoneInfo("Europe/Berlin"),
                )
            )
        case _:
            return build_vote_snippet(
                view.question or fallback,
                view.tally.counts,
                question=_with_attempt(view.question or fallback, view),
                note=_guest_note(view),
                conditions=passed_conditions(view),
            )


def _election_pairs(views: Sequence[VoteOut], tz: ZoneInfo) -> list[tuple[str, str]]:
    """Pair the internal and the public callout of each election, for the public text."""
    return [
        (
            _snippet(view, "Beschlussfrage", tz=tz),
            _snippet(view, "Beschlussfrage", public=True, tz=tz),
        )
        for view in views
        if getattr(view, "kind", "motion") == "election"
    ]


def _repeat_marks(votes: Sequence[Vote], views: Sequence[VoteOut]) -> dict[UUID, str]:
    """Return the mark line of each repeated vote of an agenda item, by vote id.

    A vote counts as repeated once its repeat opened: a prepared repeat can still go
    away, and then the first result stands alone.
    """
    return {
        source: repeat_mark(view)
        for vote, view in zip(votes, views, strict=True)
        if (source := getattr(vote, "repeat_of_id", None)) is not None
        and getattr(vote, "status", None) in ("open", "closed")
    }


def _with_attempt(question: str, view: VoteOut) -> str:
    """Add the number of a repeat to the head of a motion or a poll.

    The repeat has the question of the vote it repeats, so its head names the attempt
    („Frage (2. Abstimmung)“). Each attempt then has its own head line, which
    `votes_in_body` and the editor match on.
    """
    attempt = getattr(view, "attempt", 1) or 1
    return f"{question.strip()} ({attempt}. Abstimmung)" if attempt > 1 else question


def repeat_mark(repeat: VoteOut) -> str:
    """Return the line that marks a repeated vote in the protocol."""
    attempt = getattr(repeat, "attempt", 2) or 2
    number = (getattr(repeat, "round", 1) or 1) + attempt - 1
    return (
        f"Wiederholt, siehe {number}. Wahlgang."
        if getattr(repeat, "kind", "motion") == "election"
        else f"Wiederholt, siehe {attempt}. Abstimmung."
    )


def _election_snippet(view: VoteOut) -> ElectionSnippet:
    """Map an election and its stored result on the protocol view.

    The caller checks that the vote is an election.
    """
    assert view.election is not None
    return election_snippet_of(
        view.election,
        view.election_result,
        question=view.question,
        round_=view.round,
        attempt=getattr(view, "attempt", 1) or 1,
    )


def election_snippet_of(
    election: ElectionConfig,
    result: ElectionResultOut | None,
    *,
    question: str | None,
    round_: int,
    attempt: int = 1,
) -> ElectionSnippet:
    """Map an election config and its stored result on the protocol view.

    The erasure of a candidate (``protocol.erasure``) also calls it, with the config
    before and after the change.
    """
    elected = set(result.elected) if result is not None else set()
    names = {c.id: c.name for c in election.candidates}
    counts = result.counts if result is not None else {}
    listed = [
        ElectionLine(name=c.name, votes=counts.get(c.id, 0), elected=c.id in elected)
        for c in election.candidates
    ]
    by_votes = result is not None and result.yes is None
    lines = sorted(listed, key=lambda line: -line.votes) if by_votes else listed
    lot = result.lot if result is not None else None
    runoff = result.runoff if result is not None else None
    place_lot = result.next_round_lot if result is not None else None
    return ElectionSnippet(
        question=(question or "Wahlgang").strip() or "Wahlgang",
        seats=election.seats,
        round=round_,
        candidates=lines,
        abstentions=result.abstentions if result is not None else 0,
        yes=result.yes if result is not None else None,
        no=result.no if result is not None else None,
        by_lot=lot is not None and lot.drawn is not None,
        next_round_lot_names=[names.get(cid, cid) for cid in (place_lot.drawn or ())]
        if place_lot is not None
        else [],
        lot_pending=lot is not None and lot.drawn is None,
        runoff_names=[names.get(cid, cid) for cid in runoff.candidate_ids] if runoff else [],
        runoff_seats=runoff.seats if runoff else 0,
        closed=result is not None,
        attempt=attempt,
        members_majority=election.members_majority,
    )


_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def poll_option_label(option: PollOption, tz: ZoneInfo) -> str:
    """Return the label of a poll option: its text, or „Di, 3.11. · 18:00–20:00“."""
    return (
        option.label or option.id
        if option.start is None
        else _date_label(option.start, option.end, tz)
    )


def _date_label(start_at: datetime, end_at: datetime | None, tz: ZoneInfo) -> str:
    """Return the label of a date option: „Di, 3.11. · 18:00“, with the end when set."""
    start = start_at.astimezone(tz)
    end = f"–{end_at.astimezone(tz):%H:%M}" if end_at is not None else ""
    return f"{_WEEKDAYS[start.weekday()]}, {start.day}.{start.month}. · {start:%H:%M}{end}"


def poll_meta(config: PollConfig) -> str:
    """Return the kind line of a poll snippet."""
    match (config.mode, config.max_choices):
        case ("date", _):
            return "Terminumfrage"
        case ("single", _):
            return "Umfrage · Einzelwahl"
        case (_, None):
            return "Umfrage · Mehrfachwahl"
        case (_, most):
            return f"Umfrage · Mehrfachwahl, höchstens {most}"


def poll_snippet_of(
    config: PollConfig, result: PollResultOut | None, *, question: str | None, tz: ZoneInfo
) -> PollSnippet:
    """Map a poll and its stored result on the protocol view (highest first)."""
    labels = {o.id: poll_option_label(o, tz) for o in config.options}
    date = config.mode == "date"
    return PollSnippet(
        question=(question or "Umfrage").strip() or "Umfrage",
        meta=poll_meta(config),
        lines=_poll_lines(result, labels, date=date) if result is not None else [],
        abstentions=None if date else (result.abstentions if result is not None else 0),
        ballots=result.ballots if result is not None else 0,
        date=date,
        closed=result is not None,
    )


def _poll_lines(result: PollResultOut, labels: Mapping[str, str], *, date: bool) -> list[PollLine]:
    """Map the stored result of a poll on its option lines, in the stored order."""
    order = [oid for oid in result.order if oid in labels] or list(labels)
    top = frozenset(result.top)
    return [
        PollLine(
            label=labels[oid],
            count=result.counts.get(oid, 0),
            maybe=(result.maybe or {}).get(oid, 0) if date else None,
            top=oid in top,
        )
        for oid in order
    ]


def _guest_note(view: VoteOut) -> str | None:
    """Return the base line of a vote with guests, or None for a members vote."""
    return (
        guest_vote_note(
            view.tally.present_members,
            view.tally.present_guests,
            sum(view.tally.counts.values()),
        )
        if view.guests_vote
        else None
    )


def _vote_title(application_id: UUID | None, question: str | None = None) -> str:
    """Build the snippet heading of an embedded vote.

    For an application item, the heading is a short reference to the application. For
    a generic decision question without an application, the heading is the question
    itself. The protokollant can edit the heading in the editor.
    """
    plain = question.strip() if question and question.strip() else "Beschlussfrage"
    return f"Abstimmung – Antrag {str(application_id)[:8]}" if application_id is not None else plain
