"""Live presence: which voters currently have a meeting page open.

Process-local registry of open voter WS connections per meeting (beamer
connections don't count — display only). Each connection gets its own id so a
user with two tabs isn't dropped when one closes; join/leave fans a ``viewers``
event out over the broker. In-memory by design: with multiple API replicas each
instance sees only its own connections (documented single-replica limit).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class MeetingPresence:
    """``meeting_id → {connection_id: (sub, display_name)}``."""

    _viewers: dict[UUID, dict[str, tuple[str, str]]] = field(
        default_factory=lambda: defaultdict(dict)
    )

    def join(self, meeting_id: UUID, sub: str, name: str) -> tuple[str, list[str]]:
        """Register a connection → (connection_id, current name list)."""
        connection_id = uuid4().hex
        self._viewers[meeting_id][connection_id] = (sub, name)
        return connection_id, self.names(meeting_id)

    def leave(self, meeting_id: UUID, connection_id: str) -> list[str]:
        """Unregister a connection → current name list."""
        room = self._viewers.get(meeting_id)
        if room is not None:
            room.pop(connection_id, None)
            if not room:
                self._viewers.pop(meeting_id, None)
        return self.names(meeting_id)

    def names(self, meeting_id: UUID) -> list[str]:
        """Deduplicated (per ``sub``), sorted viewer display names."""
        seen: dict[str, str] = {}
        for sub, name in self._viewers.get(meeting_id, {}).values():
            seen.setdefault(sub, name)
        return sorted(seen.values(), key=str.casefold)


# One registry per API process (WS connections live in the same process).
PRESENCE = MeetingPresence()
