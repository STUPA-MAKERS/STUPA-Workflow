"""Admin config service: gremien, application types, global flow, RBAC, webhooks.

The server is authoritative. The frontend is only a UX gate. The router enforces
the permissions. The service validates the inputs strictly and checks the flow
graph with ``validate_flow_graph``. Every config mutation writes an audit entry
in the same transaction as the change. A save of the global flow writes a new,
immutable version. A running application is not pinned. It follows the newest
version by state key. The ``forms`` module owns the form versions.

Layout:

`.service_base`: the shared constructor, the audit hook and the datetime helpers.
`.gremien`: gremium CRUD and the protocol mail recipients.
`.application_types`: application-type CRUD.
`.flow`: the active global flow graph and the immutable flow versions.
`.rbac`: roles, role assignments, principals and group mappings.
`.webhooks`: webhook CRUD and the delivery diagnostics.
`.service`: the `ConfigService` facade that combines the ops.

This module re-exports the facade, so ``from app.modules.admin.service import
ConfigService`` keeps working.
"""

from app.modules.admin.service.service import ConfigService

__all__ = ["ConfigService"]
