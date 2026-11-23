"""Flow hook of the Paperless filing (§F/integrations/paperless/002523).

The flow engine calls `ActionDispatcher.dispatch(actions)` after the commit of a
transition. This dispatcher reads no action: a committed transition can be the decision
of an Antrag, so it asks for one filing run. The run itself finds out what is to file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.flow.dispatch import DispatchedAction
from app.modules.paperless.queue import request_filing


@dataclass(frozen=True, slots=True)
class PaperlessFilingDispatcher:
    """Ask for a filing run after a committed transition.

    ``pool`` is an ``arq.ArqRedis`` or `None`, typed loosely to keep arq out of the API.
    """

    pool: object | None

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        """Ask for one filing run when the transition dispatched an action."""
        if actions:
            await request_filing(self.pool)
