"""Audit-log module.

Append-only hash chain: ``hash = sha256(prev_hash || canonical_json(entry))``.
Other modules write via the re-exported :func:`record` hook; entries are read
through ``GET /api/admin/audit`` (RBAC ``audit.read``).
"""

from __future__ import annotations

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService, record

__all__ = ["AuditAction", "AuditService", "record"]
