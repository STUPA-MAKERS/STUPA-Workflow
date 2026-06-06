"""Audit-Log-Modul (T-23, security.md §4, data-model §1 ``audit_entry``).

Append-only Hash-Kette: ``hash = sha256(prev_hash || canonical_json(entry))``. Andere
Module schreiben über die Service-Hook :func:`record` (re-exportiert), abfragbar über
``GET /api/admin/audit`` (RBAC ``audit.read``).
"""

from __future__ import annotations

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService, record

__all__ = ["AuditAction", "AuditService", "record"]
