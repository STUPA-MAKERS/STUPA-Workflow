"""Audited actions.

Closed catalog of security-/config-relevant operations. Modules reference these
constants instead of scattering free-form strings, keeping ``action`` values
stable and queryable.
"""

from __future__ import annotations

from enum import StrEnum


class AuditAction(StrEnum):
    """Stable ``audit_entry.action`` keys."""

    LOGIN = "login"
    STATUS_CHANGE = "status_change"
    VOTE_CAST = "vote_cast"
    CONFIG_CHANGE = "config_change"
    CONFIG_ACTIVATION = "config_activation"
    # Revert of a config change from the audit log (``audit.revert``); ``data``
    # carries only id references, including the new (itself revertable) revisionId.
    CONFIG_REVERT = "config_revert"
    ROLE_CHANGE = "role_change"
    DELEGATION_GRANT = "delegation_grant"
    DELEGATION_REVOKE = "delegation_revoke"
    DELEGATION_USE = "delegation_use"
    DELEGATION_SUBSTITUTE_ADD = "delegation_substitute_add"
    DELEGATION_SUBSTITUTE_REMOVE = "delegation_substitute_remove"
    EXPORT = "export"
    # Meeting deleted; deleting finalized meetings requires ``meeting.delete_finalized``.
    MEETING_DELETE = "meeting_delete"
    # Application deleted — irreversible admin action cascading to PII, versions,
    # status events, magic links, comments, budget entries and votes. ``data``
    # carries only id references/metadata, never raw PII.
    APPLICATION_DELETE = "application_delete"
    WEBHOOK_CONFIG = "webhook_config"
    ATTACHMENT_QUARANTINE = "attachment_quarantine"
    ATTACHMENT_DELETE = "attachment_delete"
    # GDPR/PII: access (Art. 15), erasure/anonymization (Art. 17), retention
    # (Art. 5(1)(e)) plus the erasure-request queue. ``data`` carries only
    # id/email references and metadata, never raw PII values.
    PII_ACCESS = "pii_access"
    PII_DELETION = "pii_deletion"
    PII_EXPORT = "pii_export"
    ANONYMIZATION = "anonymization"
    ERASURE_REQUESTED = "erasure_requested"
    ERASURE_EXECUTED = "erasure_executed"
    ERASURE_REJECTED = "erasure_rejected"
    PRINCIPAL_ERASED = "principal_erased"
    RETENTION_ANONYMIZE = "retention_anonymize"
    # Budget/money mutations: cost-centre CRUD, top-down allocation, bookings and
    # transfers, invoices, application-to-cost-centre/fiscal-year moves. ``data``
    # carries only id references and amounts (no PII).
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
    # FinTS bank reconciliation: connection/credential changes, sync runs, statement
    # imports and line reconcile/ignore/unlink. ``data`` carries only id
    # references and counters — never PIN or other credential material.
    BANK_ACCOUNT_CONFIG = "bank_account_config"
    BANK_CREDENTIAL_SET = "bank_credential_set"
    BANK_CREDENTIAL_DELETE = "bank_credential_delete"
    BANK_SYNC = "bank_sync"
    BANK_STATEMENT_IMPORT = "bank_statement_import"
    BANK_LINE_RECONCILE = "bank_line_reconcile"
    BANK_LINE_IGNORE = "bank_line_ignore"
    BANK_LINE_UNLINK = "bank_line_unlink"


# Budget mutations revertable from the audit log: additive ops are deleted,
# updates restored from the prior state captured in audit ``data``. Deletes and
# assign/fiscal-year moves are deliberately excluded (no re-creation).
REVERTABLE_BUDGET_ACTIONS: frozenset[AuditAction] = frozenset(
    {
        AuditAction.BUDGET_NODE_CREATE,
        AuditAction.BUDGET_NODE_UPDATE,
        AuditAction.BUDGET_ALLOCATION_SET,
        AuditAction.BUDGET_TRANSFER_CREATE,
        AuditAction.BUDGET_EXPENSE_CREATE,
        AuditAction.BUDGET_EXPENSE_UPDATE,
    }
)
