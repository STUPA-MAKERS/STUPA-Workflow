"""The pure rules of a Termin: who reads it, who is invited, who changes it.

A Termin is readable by its creator, by its invited persons, by each signed-in person
when its switch "Für alle" is on, and by a holder of ``calendar.manage``. An invited
Gremium stands for the persons who read its meetings at the time of the read, so the
rules take the Gremien of the viewer and not a stored list of persons.

A scoped OAuth token reads and writes no Termin, because no OAuth scope names the
Kalender. `Viewer.id` is then None.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, time
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Viewer:
    """The caller of a Kalender read or write.

    ``gremium_ids`` holds the Gremien whose invitations reach the viewer: the
    memberships and the substitute pools.
    """

    id: UUID | None
    gremium_ids: frozenset[UUID] = frozenset()
    manages: bool = False
    publishes: bool = False


@dataclass(frozen=True, slots=True)
class Targets:
    """The invitations of one Termin."""

    gremium_ids: frozenset[UUID] = frozenset()
    principal_ids: frozenset[UUID] = frozenset()


@dataclass(frozen=True, slots=True)
class Span:
    """The start and the end of a Termin with its place."""

    starts_on: date
    ends_on: date
    start_time: time | None
    end_time: time | None
    place: str | None


def is_creator(viewer: Viewer, creator_id: UUID | None) -> bool:
    """Tell if the viewer created the Termin."""
    return viewer.id is not None and viewer.id == creator_id


def is_invited(viewer: Viewer, targets: Targets) -> bool:
    """Tell if an invitation of the Termin reaches the viewer."""
    return viewer.id is not None and (
        viewer.id in targets.principal_ids or bool(viewer.gremium_ids & targets.gremium_ids)
    )


def can_read(viewer: Viewer, creator_id: UUID | None, targets: Targets, *, for_all: bool) -> bool:
    """Tell if the viewer reads the Termin."""
    return viewer.id is not None and (
        for_all or viewer.manages or is_creator(viewer, creator_id) or is_invited(viewer, targets)
    )


def can_edit(viewer: Viewer, creator_id: UUID | None) -> bool:
    """Tell if the viewer changes and deletes the Termin."""
    return viewer.id is not None and (viewer.manages or is_creator(viewer, creator_id))


def sees_answers(viewer: Viewer, creator_id: UUID | None, targets: Targets) -> bool:
    """Tell if the viewer sees who answered: the creator, an invited person or a manager."""
    return viewer.id is not None and (
        viewer.manages or is_creator(viewer, creator_id) or is_invited(viewer, targets)
    )


def time_changed(before: Span, after: Span) -> bool:
    """Tell if the start or the end moved. The answers are then void."""
    return (before.starts_on, before.ends_on, before.start_time, before.end_time) != (
        after.starts_on,
        after.ends_on,
        after.start_time,
        after.end_time,
    )


def needs_mail(before: Span, after: Span) -> bool:
    """Tell if a change goes to the invited persons: the start, the end or the place."""
    return time_changed(before, after) or (before.place or "") != (after.place or "")


def has_ended(span: Span, today: date, now: time) -> bool:
    """Tell if the Termin is over. An all-day Termin ends with its last day."""
    return span.ends_on < today or (
        span.ends_on == today and span.end_time is not None and span.end_time <= now
    )


def forbidden_gremien(
    wanted: Collection[UUID], readable: Collection[UUID] | None, already: Collection[UUID]
) -> frozenset[UUID]:
    """The Gremien that the creator must not invite.

    ``readable`` is None for a person who reads the meetings of every Gremium. A
    Gremium that the Termin invites already stays, so a person who changes the title
    of a Termin does not lose an invitation that a manager made.
    """
    return (
        frozenset()
        if readable is None
        else frozenset(wanted) - frozenset(readable) - frozenset(already)
    )
