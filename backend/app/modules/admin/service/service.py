"""Public facade of the admin config service.

:class:`ConfigService` combines the concerns — the router and all callers bind
to exactly this class. The implementation lives in the ops classes:

* :class:`~.gremien.GremiumOps` — gremium CRUD + protocol mail recipients
* :class:`~.application_types.ApplicationTypeOps` — application-type CRUD
* :class:`~.flow.FlowOps` — active global flow graph, immutable flow versions
* :class:`~.rbac.RbacOps` — roles, assignments, principals, group mappings
* :class:`~.webhooks.WebhookOps` — webhook CRUD + delivery diagnostics
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
