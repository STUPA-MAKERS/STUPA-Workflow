"""Public facade of the to-do service.

`TodoService` combines the ops classes. The router and every other caller bind to
exactly this class:

* `boards.BoardOps`: boards, their entries, archive and delete
* `columns.ColumnOps`: columns and labels of a board
* `details.DetailOps`: the detail reads of a card
* `cards.CardOps`: create, change, move, transfer, complete, archive, links, agenda items
* `card_parts.CardPartOps`: assignees, labels and the checklist of a card
* `card_events.EventOps`: the event of a card, its follow-up and series
* `comments.CommentOps`: the comments of a card
* `reads.ReadOps`: the own cards, the board rows, linked cards, search
* `calendar_reads.CalendarOps`: the entries of the Kalender
"""

from __future__ import annotations

from app.modules.todos.service.boards import BoardOps
from app.modules.todos.service.calendar_reads import CalendarOps
from app.modules.todos.service.card_events import EventOps
from app.modules.todos.service.card_parts import CardPartOps
from app.modules.todos.service.cards import CardOps
from app.modules.todos.service.columns import ColumnOps
from app.modules.todos.service.comments import CommentOps
from app.modules.todos.service.reads import ReadOps


class TodoService(
    BoardOps,
    ColumnOps,
    CardOps,
    CardPartOps,
    EventOps,
    CommentOps,
    ReadOps,
    CalendarOps,
):
    """To-do operations bound to an ``AsyncSession``."""
