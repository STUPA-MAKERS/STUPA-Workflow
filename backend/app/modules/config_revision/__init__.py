"""Config-revision module.

Append-only snapshot history of versioned configs (forms, flow, branding). Every
config mutation appends an immutable ``config_revision`` snapshot per
``entity_type``/``entity_id`` and links it from the audit entry
(``data.revisionId`` — id reference only, no PII). Backs the version sidebar
(list/restore), the field diff, and the audit-log revert.
"""
