"""Application service: lifecycle, versioning, timeline, comments, anonymization.

Layout of the package:

``service_base``
    Shared constructor, lookup and serialization helpers, and pure field helpers.
``create``
    Creation: effective-form validation, v1, initial state and status event.
``edits``
    Versioned data edits with a diff, version history and deletion.
``reads``
    Detail view, pinned effective form and status timeline.
``listing``
    Filtered listing, committee read scope, open tasks and export name maps.
``comments``
    Internal and public comments.
``anonymize``
    GDPR anonymization: PII blanking, magic links and attachments.
``service``
    The `ApplicationsService` facade that combines these operations.

This module re-exports the facade, so ``from app.modules.applications.service
import ApplicationsService`` keeps working.
"""

from app.modules.applications.service.service import ApplicationsService

__all__ = ["ApplicationsService"]
