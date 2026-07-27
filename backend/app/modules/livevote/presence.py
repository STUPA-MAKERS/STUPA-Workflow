"""Live presence: which voters have a meeting page open now.

The registry holds the open voter WebSocket connections per meeting and lives
in one process. A beamer connection does not count, because it is a display
only. Each connection gets an own id, so a user with two tabs stays in the list
when one tab closes. A join or a leave fans a `viewers` event out over the
broker.

The registry is in memory by design. With several API replicas each instance
sees the own connections only. This is the documented single-replica limit.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class MeetingPresence:
    """Map `meeting_id` to `{connection_id: (sub, display_name)}`."""

    _viewers: dict[UUID, dict[str, tuple[str, str]]] = field(
        default_factory=lambda: defaultdict(dict)
    )

    def join(self, meeting_id: UUID, sub: str, name: str) -> tuple[str, list[str]]:
        """Register a connection.

        Returns:
            The connection id and the current list of names.
        """
        connection_id = uuid4().hex
        self._viewers[meeting_id][connection_id] = (sub, name)
        return connection_id, self.names(meeting_id)

    def leave(self, meeting_id: UUID, connection_id: str) -> list[str]:
        """Unregister a connection.

        Returns:
            The current list of names.
        """
        room = self._viewers.get(meeting_id)
        if room is not None:
            room.pop(connection_id, None)
            if not room:
                self._viewers.pop(meeting_id, None)
        return self.names(meeting_id)

    def names(self, meeting_id: UUID) -> list[str]:
        """Return the sorted viewer display names, deduplicated per `sub`."""
        seen: dict[str, str] = {}
        for sub, name in self._viewers.get(meeting_id, {}).values():
            seen.setdefault(sub, name)
        return sorted(seen.values(), key=str.casefold)


# One registry per API process. The WebSocket connections live in that process.
PRESENCE = MeetingPresence()
