"""Audit-log module.

The log is an append-only hash chain: ``hash = sha256(prev_hash || canonical_json(entry))``.
Other modules write through the re-exported `record` hook. Clients read entries
through ``GET /api/admin/audit`` with the RBAC permission ``audit.read``.
"""

from __future__ import annotations

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService, record

__all__ = ["AuditAction", "AuditService", "record"]
