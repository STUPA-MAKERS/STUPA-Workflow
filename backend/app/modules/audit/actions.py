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
    # Sitzung gelöscht (#16) — mit ``finalizedProtocol``-Flag im Datensatz; das
    # Löschen finalisierter Sitzungen verlangt ``meeting.delete_finalized``.
    MEETING_DELETE = "meeting_delete"
    WEBHOOK_CONFIG = "webhook_config"
    ATTACHMENT_QUARANTINE = "attachment_quarantine"
    ATTACHMENT_DELETE = "attachment_delete"
    # Budget-/Geld-Mutationen (#sec-audit): Kostenstellen-CRUD, Top-Down-Zuteilung,
    # Buchungen/Umbuchungen, Rechnungen, Antrag→Kostenstelle/HHJ. Nur id-Referenzen
    # und Beträge im ``data`` (keine PII) — wer wann Mittel bewegt/gelöscht hat.
    BUDGET_NODE_CREATE = "budget_node_create"
    BUDGET_NODE_UPDATE = "budget_node_update"
    BUDGET_NODE_DELETE = "budget_node_delete"
    BUDGET_ALLOCATION_SET = "budget_allocation_set"
    BUDGET_EXPENSE_CREATE = "budget_expense_create"
    BUDGET_EXPENSE_UPDATE = "budget_expense_update"
    BUDGET_EXPENSE_DELETE = "budget_expense_delete"
    BUDGET_TRANSFER_CREATE = "budget_transfer_create"
    BUDGET_INVOICE_CREATE = "budget_invoice_create"
    BUDGET_INVOICE_UPDATE = "budget_invoice_update"
    BUDGET_INVOICE_DELETE = "budget_invoice_delete"
    BUDGET_ASSIGN = "budget_assign"
    BUDGET_MOVE_FISCAL_YEAR = "budget_move_fiscal_year"
