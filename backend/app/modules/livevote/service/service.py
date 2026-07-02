"""Public facade of the meeting service.

:class:`MeetingService` combines the concerns — the router, WS connection layer,
and all callers bind to exactly this class. The implementation lives in the ops
classes:

* :class:`~.lifecycle.LifecycleOps` — create/patch/delete, lifecycle rules, broadcast
* :class:`~.listing.ListingOps` — detail read, list, filter gremien, timeline/search
* :class:`~.permissions.PermissionOps` — RBAC checks, visibility scope, flag serializer
* :class:`~.votes.VoteReadOps` — vote tally reload, reveal rule, quorum helpers
"""

from __future__ import annotations

from app.modules.livevote.service.lifecycle import LifecycleOps
from app.modules.livevote.service.listing import ListingOps
from app.modules.livevote.service.permissions import PermissionOps
from app.modules.livevote.service.votes import VoteReadOps


class MeetingService(
    LifecycleOps,
    ListingOps,
    PermissionOps,
    VoteReadOps,
):
    """DB-backed meeting operations (bound to one ``AsyncSession`` + publisher)."""
