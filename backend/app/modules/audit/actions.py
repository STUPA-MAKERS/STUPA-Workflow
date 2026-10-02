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
    DELEGATION_REVOKE = "delegation_revoke"
    DELEGATION_USE = "delegation_use"
    DELEGATION_SUBSTITUTE_ADD = "delegation_substitute_add"
    DELEGATION_SUBSTITUTE_REMOVE = "delegation_substitute_remove"
    EXPORT = "export"
    # Meeting deleted. To delete a finalized meeting you need ``meeting.delete_finalized``.
    MEETING_DELETE = "meeting_delete"
    # Meeting and agenda (F12). ``data`` carries id references and planning values
    # only. MEETING_UPDATE records a status change and a change of the date, the times
    # or the protokollant, each as ``{"from": ..., "to": ...}``. The current agenda item
    # and the beamer focus change many times in a meeting and are not recorded.
    # AGENDA_ITEM_UPDATE names the changed fields, never the Markdown text: a body
    # edit is recorded only after the close, as a correction of the minutes (O22).
    MEETING_CREATE = "meeting_create"
    MEETING_UPDATE = "meeting_update"
    AGENDA_ITEM_ADD = "agenda_item_add"
    AGENDA_ITEM_UPDATE = "agenda_item_update"
    AGENDA_ITEM_REMOVE = "agenda_item_remove"
    AGENDA_REORDER = "agenda_reorder"
    # Attendance set or reset by the meeting lead (F12, Z2). ``data`` carries the
    # principal id and the status before and after the change. It never carries the
    # note, because the reason of an excuse is personal data. The own report of a
    # member is not recorded.
    ATTENDANCE_SET = "attendance_set"
    ATTENDANCE_RESET = "attendance_reset"
    # Application deleted. This admin action is irreversible. It cascades to PII,
    # versions, status events, magic links, comments, budget entries and votes.
    # ``data`` carries only id references and metadata, never raw PII.
    APPLICATION_DELETE = "application_delete"
    # Application created (F12). ``data`` carries the type, the gremium, the initial
    # state and whether the email still needs a confirmation. It never carries the
    # email, the name or a field value.
    APPLICATION_CREATE = "application_create"
    # An application without a confirmed email was discarded after
    # ``guest_application_settings.confirm_ttl_hours`` (Z1). ``data`` carries the
    # type, the gremium, the attachment count and the window, never PII.
    GUEST_APPLICATION_DISCARD = "guest_application_discard"
    # Application data edited (PATCH). ``data`` carries the new version number and
    # the keys of the added, removed and changed fields. It never carries a value,
    # because a field value can hold PII. The version diff keeps the values.
    APPLICATION_UPDATE = "application_update"
    # Application archived or brought back. Reversible, unlike the delete above, but it
    # changes what the working list shows, so both directions are recorded. ``data``
    # carries id references and the direction, never raw PII.
    APPLICATION_ARCHIVE = "application_archive"
    APPLICATION_UNARCHIVE = "application_unarchive"
    # A public read-only link created or revoked. Both are recorded: publishing a record
    # and taking it back are the two moments anyone will ask about afterwards. ``data``
    # carries the share id and the expiry, never the token.
    APPLICATION_SHARE = "application_share"
    APPLICATION_SHARE_REVOKE = "application_share_revoke"
    WEBHOOK_CONFIG = "webhook_config"
    # Attachment uploaded (F12). ``data`` names the application, or carries
    # ``draft: true`` for a draft upload of the wizard (Z4). It holds the field key,
    # the comparison-offer flag, the MIME type and the size, never the file name,
    # because a file name can hold PII. The quarantine and the delete of a draft carry
    # ``draft: true`` the same way.
    ATTACHMENT_UPLOAD = "attachment_upload"
    ATTACHMENT_QUARANTINE = "attachment_quarantine"
    ATTACHMENT_DELETE = "attachment_delete"
    # Application comment edited or removed in place. A comment keeps no version
    # history, so the log is the only record that the text changed. ``data``
    # carries the application id, the visibility and the author kind. It never
    # carries the comment text, because a comment can hold PII.
    COMMENT_UPDATE = "comment_update"
    COMMENT_DELETE = "comment_delete"
    # Draft protocol removed. A finalized protocol is a signed record and the
    # route refuses to delete it.
    PROTOCOL_DELETE = "protocol_delete"
    # Start of the finalization of a protocol (F8, F12). ``data`` carries the meeting
    # and the gremium. A render that fails sets the protocol back to a draft, and a
    # new finalization writes a new entry.
    PROTOCOL_FINALIZE = "protocol_finalize"
    # Handover of the minutes during a live meeting (Z3, F12). ``data`` carries the
    # ``mode`` (``now``, ``next_item``, ``activate`` when a move of the agenda item
    # starts the planned period, ``cancel`` when the planned handover goes away),
    # the principal ids ``from`` and ``to``, and the current agenda item.
    PROTOKOLLANT_HANDOVER = "protokollant_handover"
    # Vote removed before it ever opened. A vote with ballots is not deletable.
    VOTE_DELETE = "vote_delete"
    # Vote lifecycle (F12). ``data`` carries id references and aggregates only, never
    # a voter: VOTE_CLOSE holds the result and the counts per option. VOTE_CANCEL
    # holds the reason (a person cancelled, or the application left the vote state).
    # VOTE_BRANCH_BLOCKED records a close whose pass or fail transition did not fire
    # (the guard failed, or the state has no such transition). The vote then stays
    # closed and the application stays in its state.
    VOTE_OPEN = "vote_open"
    VOTE_CLOSE = "vote_close"
    VOTE_CANCEL = "vote_cancel"
    VOTE_BRANCH_BLOCKED = "vote_branch_blocked"
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
    BUDGET_EXPENSE_CREATE = "budget_expense_create"
    BUDGET_EXPENSE_UPDATE = "budget_expense_update"
    BUDGET_EXPENSE_DELETE = "budget_expense_delete"
    BUDGET_TRANSFER_CREATE = "budget_transfer_create"
    BUDGET_INVOICE_CREATE = "budget_invoice_create"
    BUDGET_INVOICE_UPDATE = "budget_invoice_update"
    BUDGET_INVOICE_DELETE = "budget_invoice_delete"
    BUDGET_ASSIGN = "budget_assign"
    BUDGET_MOVE_FISCAL_YEAR = "budget_move_fiscal_year"
    # Whole-platform backup and restore, gated by ``backup.manage``. ``data`` carries
    # the backup id, the kind and size metadata, never archive contents. A restore
    # replaces the database, so the entry for BACKUP_RESTORE lands in the chain of the
    # restored state, after the safety backup that the restore takes first.
    BACKUP_CREATE = "backup_create"
    BACKUP_DELETE = "backup_delete"
    BACKUP_EXPORT = "backup_export"
    BACKUP_IMPORT = "backup_import"
    BACKUP_RESTORE = "backup_restore"


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
