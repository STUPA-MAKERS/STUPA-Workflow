"""Admin config service — gremien, application types, global flow, RBAC, webhooks.

Server-side authoritative: the frontend is only a UX gate. Permissions are
enforced in the router, inputs are strictly validated (flow graph via
``validate_flow_graph``), and every config mutation writes an audit entry in
the same transaction as the change. The global flow is saved as a new,
immutable version per save; running applications follow the newest version by
state key (not pinned). Form versions are owned by the ``forms`` module.

Layout:

* :mod:`.service_base`      — shared constructor, audit hook, datetime helpers.
* :mod:`.gremien`           — gremium CRUD + protocol mail recipients.
* :mod:`.application_types` — application-type CRUD.
* :mod:`.flow`              — active global flow graph, immutable flow versions.
* :mod:`.rbac`              — roles, role assignments, principals, group mappings.
* :mod:`.webhooks`          — webhook CRUD + delivery diagnostics.
* :mod:`.service`           — :class:`~.service.ConfigService` facade combining the ops.

The facade is re-exported here so ``from app.modules.admin.service import
ConfigService`` keeps working.
"""

from app.modules.admin.service.service import ConfigService

__all__ = ["ConfigService"]
