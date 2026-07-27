"""Public facade of the meeting service.

`MeetingService` combines the concerns. The router, the WebSocket connection layer,
and every other caller bind to this class only. The implementation lives in the ops
classes:

* `lifecycle.LifecycleOps` — create, patch, delete, lifecycle rules, broadcast
* `listing.ListingOps` — detail read, list, gremien filter, timeline and search
* `permissions.PermissionOps` — RBAC checks, visibility scope, flag serializer
* `votes.VoteReadOps` — vote tally reload, reveal rule, quorum helpers
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
    """DB-backed meeting operations bound to one `AsyncSession` and a publisher."""
