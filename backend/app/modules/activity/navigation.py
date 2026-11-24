"""The marks of the navigation in one read (spec 002001).

The rail and the tab bar show four marks: the count of the open tasks (applications to
act on plus the open to-dos of the caller), the count of the new tickets, a dot while a
readable meeting runs, and a dot while an event of another person waits on the activity
page. Each mark reuses the read and the gate of its own module, so a mark never shows
more than the page behind it. A mark of a feature that is off is empty.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity.schemas import NavigationStatus
from app.modules.activity.service import ActivityService
from app.modules.applications.service import ApplicationsService
from app.modules.auth.principal import Principal
from app.modules.livevote.service import MeetingService
from app.modules.site_config.features import Feature, active_features
from app.modules.tickets.access import area_scope, works_anywhere
from app.modules.tickets.service import TicketService
from app.modules.todos.service import TodoService
from app.shared.errors import ForbiddenError


async def _open_todos(session: AsyncSession, principal: Principal) -> int:
    """Count the open cards assigned to the caller; a token without to-do scope counts 0."""
    try:
        return len((await TodoService(session).mine(principal)).items)
    except ForbiddenError:
        return 0


async def navigation_status(session: AsyncSession, principal: Principal) -> NavigationStatus:
    """Read the four marks of the navigation for ``principal``."""
    features = await active_features(session)
    tasks = len(await ApplicationsService(session).list_tasks(principal))
    todos = await _open_todos(session, principal) if Feature.TODOS in features else 0
    areas = await area_scope(session, principal) if Feature.TICKETS in features else frozenset()
    tickets = (
        (await TicketService(session).counts(areas=areas)).new if works_anywhere(areas) else None
    )
    live = Feature.MEETINGS in features and await MeetingService(session).any_live(principal)
    activity = Feature.ACTIVITY in features and await ActivityService(session).has_new(principal)
    return NavigationStatus(tasks=tasks + todos, tickets=tickets, live=live, activity=activity)
