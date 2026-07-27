"""Public facade of the admin config service.

``ConfigService`` combines the concerns. The router and every caller bind to
exactly this class. The ops classes hold the implementation.

``gremien.GremiumOps`` — gremium CRUD plus the protocol mail recipients.
``application_types.ApplicationTypeOps`` — application-type CRUD.
``flow.FlowOps`` — the active global flow graph and immutable flow versions.
``rbac.RbacOps`` — roles, assignments, principals and group mappings.
``webhooks.WebhookOps`` — webhook CRUD plus delivery diagnostics.
"""

from __future__ import annotations

from app.modules.admin.service.application_types import ApplicationTypeOps
from app.modules.admin.service.flow import FlowOps
from app.modules.admin.service.gremien import GremiumOps
from app.modules.admin.service.rbac import RbacOps
from app.modules.admin.service.webhooks import WebhookOps


class ConfigService(
    GremiumOps,
    ApplicationTypeOps,
    FlowOps,
    RbacOps,
    WebhookOps,
):
    """DB-backed admin config operations (bound to one ``AsyncSession``)."""
