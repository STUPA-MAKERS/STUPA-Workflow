"""Audited actions.

This is the closed catalog of security-relevant and config-relevant operations.
Modules reference these constants instead of free-form strings. That keeps the
``action`` values stable and queryable.
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
    # Revert of a config change from the audit log, gated by ``audit.revert``.
    # ``data`` carries only id references, including the new revisionId. That new
    # revision is itself revertable.
    CONFIG_REVERT = "config_revert"
    ROLE_CHANGE = "role_change"
    DELEGATION_GRANT = "delegation_grant"
    DELEGATION_UPDATE = "delegation_update"
    DELEGATION_REVOKE = "delegation_revoke"
    DELEGATION_USE = "delegation_use"
    DELEGATION_SUBSTITUTE_ADD = "delegation_substitute_add"
    DELEGATION_SUBSTITUTE_REMOVE = "delegation_substitute_remove"
    EXPORT = "export"
    # Meeting deleted. To delete a finalized meeting you need ``meeting.delete_finalized``.
    MEETING_DELETE = "meeting_delete"
    # Application deleted. This admin action is irreversible. It cascades to PII,
    # versions, status events, magic links, comments, budget entries and votes.
    # ``data`` carries only id references and metadata, never raw PII.
    APPLICATION_DELETE = "application_delete"
    WEBHOOK_CONFIG = "webhook_config"
    ATTACHMENT_QUARANTINE = "attachment_quarantine"
    ATTACHMENT_DELETE = "attachment_delete"
    # A comment keeps no version history, so ``data`` records the metadata of the
    # change but never the text, which can hold PII.
    COMMENT_UPDATE = "comment_update"
    COMMENT_DELETE = "comment_delete"
    PROTOCOL_DELETE = "protocol_delete"
    VOTE_DELETE = "vote_delete"
    VOTE_UPDATE = "vote_update"
    # Correction of the applicant name or email. ``data`` records which fields
    # changed, never the old or the new value, which are PII.
    APPLICANT_UPDATE = "applicant_update"
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
    # Budget and money mutations: cost-center CRUD, top-down allocation, bookings
    # and transfers, invoices, moves of an application to another cost center or
    # fiscal year. ``data`` carries only id references and amounts, no PII.
    BUDGET_NODE_CREATE = "budget_node_create"
    BUDGET_NODE_UPDATE = "budget_node_update"
    BUDGET_NODE_DELETE = "budget_node_delete"
    BUDGET_FISCAL_YEAR_DELETE = "budget_fiscal_year_delete"
    BUDGET_ALLOCATION_SET = "budget_allocation_set"
    BUDGET_ALLOCATION_DELETE = "budget_allocation_delete"
    BUDGET_EXPENSE_CREATE = "budget_expense_create"
    BUDGET_EXPENSE_UPDATE = "budget_expense_update"
    BUDGET_EXPENSE_DELETE = "budget_expense_delete"
    BUDGET_TRANSFER_CREATE = "budget_transfer_create"
    BUDGET_INVOICE_CREATE = "budget_invoice_create"
    BUDGET_INVOICE_UPDATE = "budget_invoice_update"
    BUDGET_INVOICE_DELETE = "budget_invoice_delete"
    BUDGET_ASSIGN = "budget_assign"
    BUDGET_MOVE_FISCAL_YEAR = "budget_move_fiscal_year"


# Budget mutations that the audit log can revert. A revert deletes an additive
# operation. A revert of an update restores the prior state that audit ``data``
# captured. Deletes and assign or fiscal-year moves stay out on purpose, because
# the platform cannot re-create them.
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
