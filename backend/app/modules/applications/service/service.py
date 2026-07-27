"""Public facade of the applications service.

`ApplicationsService` combines the concerns. The router and all other callers bind to
exactly this class. The implementation lives in the ops classes:

* `create.CreateOps`: application creation, public and managed
* `edits.EditOps`: versioned data edits with diff, version history, deletion
* `reads.ReadOps`: detail view, pinned effective form, status timeline
* `listing.ListingOps`: filtered listing, Gremium scope, tasks, name maps
* `comments.CommentOps`: internal and public comments
* `anonymize.AnonymizeOps`: GDPR anonymization
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
    """DB-backed application operations, bound to one `AsyncSession`."""
