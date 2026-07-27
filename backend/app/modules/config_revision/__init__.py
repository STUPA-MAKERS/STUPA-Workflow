"""Config-revision module.

This module keeps an append-only snapshot history of the versioned configs: forms,
flow and branding. Every config mutation appends an immutable ``config_revision``
snapshot per ``entity_type`` and ``entity_id``. The audit entry points to that
snapshot through ``data.revisionId``, which is an id reference only and holds no PII.
The module backs the version sidebar with its list and restore, the field diff, and
the audit-log revert.
"""
