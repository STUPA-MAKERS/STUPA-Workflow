"""To-do service: boards, columns, labels, cards and their sub-resources.

The service decides every right itself (``BoardAccess``): a board, a card or a
sub-resource that the caller cannot read answers 404, a card write on a board that
the caller reads but cannot write (``todo.read_all``) answers 403
``todo_write_required``, and a configuration change without ``todo.configure``
answers 403 ``todo_configure_required``.

Writes that order cards (create, move, column delete) lock the board row first, so
two parallel moves compute their ranks one after the other. Every card write bumps
``todo_board.updated_at``. A write that changes a card sets its ``updated_at`` itself:
the column default ``onupdate=now()`` would expire the attribute, and the response
built after the commit would then load it outside the async context. ``version``
guards the content edits only (title, description, due date): moves and
sub-resources neither need nor bump it, so a drag never invalidates an open drawer.

A card that enters the done column gets ``completed_at`` and writes ``todo_done``
into the timeline of every linked ticket; a card that leaves it loses
``completed_at``.

Mails go through ``outbox``: the router sends them after the commit.

Layout of the package:

``common``
    Constants, types and small helpers.
``ranks``
    Lexorank placement of cards.
``rows``
    Pure serialization into the API schemas.
``base``
    Access, locks, lookups, events, pings and mails that every ops class shares.
``boards``, ``columns``, ``details``, ``cards``, ``card_parts``, ``card_events``,
``comments``, ``reads``, ``calendar_reads``
    The ops classes, one concern each.
``service``
    The `TodoService` facade that combines them.

This package re-exports the public names, so ``from app.modules.todos.service import
TodoService`` keeps working.
"""

from app.modules.todos.service.common import BERLIN, TodoMail, berlin_today
from app.modules.todos.service.service import TodoService

__all__ = ["BERLIN", "TodoMail", "TodoService", "berlin_today"]
