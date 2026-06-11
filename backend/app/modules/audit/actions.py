"""Auditierte Aktionen (security.md §4).

Geschlossene Liste sicherheits-/config-relevanter Vorgänge. Module verweisen auf
diese Konstanten statt freie Strings zu streuen — stabile, abfragbare ``action``-Werte.
"""

from __future__ import annotations

from enum import StrEnum


class AuditAction(StrEnum):
    """Stabile ``audit_entry.action``-Schlüssel (security.md §4)."""

    LOGIN = "login"
    STATUS_CHANGE = "status_change"
    VOTE_CAST = "vote_cast"
    CONFIG_CHANGE = "config_change"
    CONFIG_ACTIVATION = "config_activation"
    ROLE_CHANGE = "role_change"
    DELEGATION_GRANT = "delegation_grant"
    DELEGATION_REVOKE = "delegation_revoke"
    DELEGATION_USE = "delegation_use"
    DELEGATION_SUBSTITUTE_ADD = "delegation_substitute_add"
    DELEGATION_SUBSTITUTE_REMOVE = "delegation_substitute_remove"
    EXPORT = "export"
    WEBHOOK_CONFIG = "webhook_config"
    ATTACHMENT_QUARANTINE = "attachment_quarantine"
    ATTACHMENT_DELETE = "attachment_delete"
