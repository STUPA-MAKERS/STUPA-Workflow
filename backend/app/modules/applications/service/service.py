"""Public facade of the applications service.

:class:`ApplicationsService` combines the concerns — the router and all callers
bind to exactly this class. The implementation lives in the ops classes:

* :class:`~.create.CreateOps` — application creation (public + managed)
* :class:`~.edits.EditOps` — versioned data edits + diff, version history, deletion
* :class:`~.reads.ReadOps` — detail view, pinned effective form, status timeline
* :class:`~.listing.ListingOps` — filtered listing, committee scope, tasks, name maps
* :class:`~.comments.CommentOps` — internal/public comments
* :class:`~.anonymize.AnonymizeOps` — GDPR anonymization
"""

from __future__ import annotations

from app.modules.applications.service.anonymize import AnonymizeOps
from app.modules.applications.service.comments import CommentOps
from app.modules.applications.service.create import CreateOps
from app.modules.applications.service.edits import EditOps
from app.modules.applications.service.listing import ListingOps
from app.modules.applications.service.reads import ReadOps


class ApplicationsService(
    CreateOps,
    EditOps,
    ReadOps,
    ListingOps,
    CommentOps,
    AnonymizeOps,
):
    """DB-backed application operations (bound to one ``AsyncSession``)."""
