"""Change pings of the to-do boards: ``BoardPings`` collects them, ``publish_pings`` sends them.

A ping names what changed, never the content: a tile is per viewer (the primary
link of a card is redacted for a viewer who cannot read its target), so the client
reads the changed card (``GET /todos/cards/{id}/tile``) or the board through REST,
which applies every rule. The channel of a board is ``todo-board:{board_id}``:

* ``{"type": "card", "boardId", "cardId"}``: a card of the board was created or
  changed (a field, a sub-resource, a comment, a move inside the board, a restore).
* ``{"type": "card_removed", "boardId", "cardId"}``: the card left the board
  (archived, or transferred to another board).
* ``{"type": "board", "boardId"}``: a change of the board itself (name, settings,
  columns, labels), or more than one card in one request.

``TodoService._touch`` records every board write in ``TodoService.pings``. The
router publishes them after the commit, one ping per board, like the mails of the
outbox. A failed publish is logged and swallowed, because the 30 s poll of the page
covers a lost ping, and a write must not fail on Redis.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.modules.livevote.broker import InMemoryBroker, PatternBroker

logger = logging.getLogger("app.todos.live")

PingKind = Literal["card", "card_removed", "board"]
#: The glob that one to-do socket subscribes to (one subscription per socket).
CHANNEL_PATTERN = "todo-board:*"

# The single-process fallback when the lifespan wires no broker (tests). Production
# uses the Redis broker of the live vote on ``app.state.broker``.
_FALLBACK_BROKER = InMemoryBroker()


def board_channel(board_id: uuid.UUID) -> str:
    """The broker channel of a board."""
    return f"todo-board:{board_id}"


def todo_broker(state: object) -> PatternBroker:
    """Return the broker of the app state (Redis in production), else the in-memory fallback."""
    broker: PatternBroker | None = getattr(state, "broker", None)
    return broker or _FALLBACK_BROKER


@dataclass(slots=True)
class _Touched:
    cards: dict[uuid.UUID, PingKind] = field(default_factory=dict)
    whole: bool = False


@dataclass(slots=True)
class BoardPings:
    """The boards and cards that one request changed, in the order of the first write."""

    _boards: dict[uuid.UUID, _Touched] = field(default_factory=dict)

    def touch(
        self, board_id: uuid.UUID, card_id: uuid.UUID | None = None, *, removed: bool = False
    ) -> None:
        """Record a write: of the board itself (no card), of a card, or a card that left."""
        entry = self._boards.setdefault(board_id, _Touched())
        if card_id is None:
            entry.whole = True
        elif removed or entry.cards.get(card_id) != "card_removed":
            # A card that left the board stays gone, whatever the request did before.
            entry.cards[card_id] = "card_removed" if removed else "card"

    def messages(self) -> list[dict[str, object]]:
        """One ping per touched board: ``board`` for a board change or several cards."""
        out: list[dict[str, object]] = []
        for board_id, entry in self._boards.items():
            if entry.whole or len(entry.cards) != 1:
                out.append({"type": "board", "boardId": str(board_id)})
                continue
            ((card_id, kind),) = entry.cards.items()
            out.append({"type": kind, "boardId": str(board_id), "cardId": str(card_id)})
        return out

    def drain(self) -> list[dict[str, object]]:
        """Return the pings and forget them (a second publish sends nothing)."""
        out = self.messages()
        self._boards.clear()
        return out


async def publish_pings(broker: PatternBroker, messages: Sequence[dict[str, object]]) -> None:
    """Publish the pings after the commit; a broker fault is logged, never raised."""
    for message in messages:
        board_id = uuid.UUID(str(message["boardId"]))
        try:
            await broker.publish(board_channel(board_id), message)
        except Exception:  # noqa: BLE001 — a lost ping is covered by the poll of the page
            logger.warning("to-do ping for board %s failed", board_id, exc_info=True)
