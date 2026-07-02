"""Application service — lifecycle, versioning, timeline, comments, anonymization.

Layout:

* :mod:`.service_base` — shared constructor + lookup/serialization helpers, pure field helpers.
* :mod:`.create`       — creation: effective-form validation, v1, initial state + status event.
* :mod:`.edits`        — versioned data edits with diff, version history, deletion.
* :mod:`.reads`        — detail view, pinned effective form, status timeline.
* :mod:`.listing`      — filtered listing, committee read scope, open tasks, export name maps.
* :mod:`.comments`     — internal/public comments.
* :mod:`.anonymize`    — GDPR anonymization (PII blanking, magic links, attachments).
* :mod:`.service`      — :class:`~.service.ApplicationsService` facade combining the ops.

The facade is re-exported here so ``from app.modules.applications.service import
ApplicationsService`` keeps working.
"""

from app.modules.applications.service.service import ApplicationsService

__all__ = ["ApplicationsService"]
