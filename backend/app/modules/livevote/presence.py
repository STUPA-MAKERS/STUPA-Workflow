"""Live presence: which voters have a meeting page open now.

The registry holds the open voter WebSocket connections per meeting and lives
in one process. A beamer connection does not count, because it is a display
only. Each connection gets an own id, so a user with two tabs stays in the list
when one tab closes. A join or a leave fans a `viewers` event out over the
broker.

Each entry keeps the principal id next to the name, because the client shows
the avatar of each viewer and the avatar loads by principal id (spec 000574).

The registry is in memory by design. With several API replicas each instance
sees the own connections only. This is the documented single-replica limit.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class Viewer:
    """One person in the live list: the principal id (if known) and the display name."""

    id: UUID | None
    name: str


@dataclass(frozen=True, slots=True)
class MeetingPresence:
    """Map `meeting_id` to `{connection_id: (sub, viewer)}`."""

    _viewers: dict[UUID, dict[str, tuple[str, Viewer]]] = field(
        default_factory=lambda: defaultdict(dict)
    )

    def join(
        self, meeting_id: UUID, sub: str, name: str, principal_id: UUID | None = None
    ) -> tuple[str, list[Viewer]]:
        """Register a connection.

        Returns:
            The connection id and the current list of viewers.
        """
        connection_id = uuid4().hex
        self._viewers[meeting_id].update({connection_id: (sub, Viewer(principal_id, name))})
        return connection_id, self.viewers(meeting_id)

    def leave(self, meeting_id: UUID, connection_id: str) -> list[Viewer]:
        """Unregister a connection.

        Returns:
            The current list of viewers.
        """
        self._viewers.get(meeting_id, {}).pop(connection_id, None)
        if not self._viewers.get(meeting_id, True):
            self._viewers.pop(meeting_id, None)
        return self.viewers(meeting_id)

    def viewers(self, meeting_id: UUID) -> list[Viewer]:
        """Return the viewers sorted by name, deduplicated per `sub`."""
        entries = tuple(self._viewers.get(meeting_id, {}).values())
        first = dict(reversed(entries))
        subs = dict.fromkeys(sub for sub, _ in entries)
        return sorted((first[sub] for sub in subs), key=lambda v: v.name.casefold())

    def names(self, meeting_id: UUID) -> list[str]:
        """Return the sorted viewer display names, deduplicated per `sub`."""
        return [v.name for v in self.viewers(meeting_id)]


#: One registry per API process. The WebSocket connections live in that process.
PRESENCE = MeetingPresence()
