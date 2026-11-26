"""Who reads and writes an Event: the members of its team (F/collaboration/events/003026).

Each member of the team of an Event reads and writes it. A member of the parent team or
of a sub-team gets no access by this alone, because a team does not add the members of
another team (003064). A token needs ``todo.write`` in its scope, the same right that opens
the boards of a team, so the OAuth scopes of the to-dos give the same access.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.teams.members import member_team_ids
from app.modules.todos.access import TODO_WRITE


async def event_team_ids(session: AsyncSession, principal: Principal) -> frozenset[uuid.UUID]:
    """Return the teams whose Events the principal reads and writes."""
    if not principal.scope_allows(TODO_WRITE):
        return frozenset()
    return await member_team_ids(session, principal)
