"""Audited actions.

This is the closed catalog of security-relevant and config-relevant operations.
Modules reference these constants instead of free-form strings. That keeps the
``action`` values stable and queryable.

``REVERTABLE_BUDGET_ACTIONS`` lists the budget mutations that the audit log can
revert. A revert deletes an additive operation, or restores the prior state that
audit ``data`` captured for an update. Deletes and assign or fiscal-year moves stay
out, because the platform cannot re-create them.
"""

from __future__ import annotations

from enum import StrEnum


class AuditAction(StrEnum):
    """Stable ``audit_entry.action`` keys.

    ``data`` of every entry carries id references, counts and metadata only, never
    raw PII, because the chain is append-only and a value in it can never be deleted.

    Attributes:
        LOGIN: A successful OIDC login. The actor is the principal, the target its
            ``principal`` row. ``data`` holds only ``{"method": "oidc"}``, never an IP
            address, a user agent or an e-mail. A refused login writes nothing. A
            magic-link redeem is not a login: it opens an applicant session for one
            application and has no principal.
        CONFIG_REVERT: Revert of a config change from the audit log, gated by
            ``audit.revert``. ``data`` carries the new revisionId. That new revision
            is itself revertable.
        MEETING_DELETE: Meeting deleted. A finalized meeting needs
            ``meeting.delete_finalized``.
        MEETING_UPDATE: A status change or a change of the date, the times or the
            protokollant, each as ``{"from": ..., "to": ...}``. The current agenda
            item and the beamer focus change many times in a meeting and are not
            recorded.
        AGENDA_ITEM_UPDATE: Names the changed fields, never the Markdown text. A body
            edit is recorded only after the close, as a correction of the minutes.
        AGENDA_ITEM_DONE: The done mark of an agenda item set ("TOP abhaken").
            ``data`` carries the agenda item id and, for a move to the next item,
            ``via: next``.
        ATTENDANCE_SET: Attendance set or reset by the meeting lead. ``data`` carries
            the principal id and the status before and after. It never carries the
            note, because the reason of an excuse is personal data. The own report of
            a member is not recorded.
        APPLICATION_DELETE: Irreversible admin delete. It cascades to PII, versions,
            status events, magic links, comments, budget entries and votes.
        APPLICATION_CREATE: ``data`` carries the type, the gremium, the initial state
            and whether the email still needs a confirmation.
        APPLICATION_CREATE_ON_BEHALF: Application captured for an applicant. The actor
            is the capturing person. ``data`` carries the applicant kind
            (``principal`` or ``guest``), the principal id of an account applicant,
            the received date, whether an intake note exists and whether a guest
            e-mail matched an active account (``matchedByEmail``).
        GUEST_APPLICATION_DISCARD: An application without a confirmed email was
            discarded after ``guest_application_settings.confirm_ttl_hours``.
            ``data`` carries the type, the gremium, the attachment count and the
            window.
        APPLICATION_UPDATE: Application data edited (PATCH). ``data`` carries the new
            version number and the keys of the added, removed and changed fields,
            never a value, because a field value can hold PII. The version diff keeps
            the values.
        APPLICATION_ARCHIVE: Archive or unarchive. Both directions are recorded,
            because they change what the working list shows.
        APPLICATION_SHARE: A public read-only link created or revoked. ``data``
            carries the share id and the expiry, never the token.
        APPLICATION_DECISION: Approval with deviations from a passed vote with a
            proposal or from a manual transition, or its undo by an audit revert of
            its status change (``reverted: true``). ``data`` carries the requested
            amount, the old and the new approved amount, the number of conditions and
            the vote and status-event ids, never the condition texts.
        ATTACHMENT_UPLOAD: ``data`` names the application, or carries ``draft: true``
            for a draft upload of the wizard, plus whether a field key is set, the
            MIME type and the size. It never carries the file name, because a file
            name can hold PII. Quarantine and delete of a draft carry ``draft: true``
            too.
        COMMENT_UPDATE: Comment edited or removed in place. A comment keeps no version
            history, so the log is the only record of the change. ``data`` carries the
            application id, the visibility and the author kind, never the text.
        PROTOCOL_DELETE: Draft protocol removed. The route refuses to delete a
            finalized protocol, because it is a signed record.
        PROTOCOL_FINALIZE: Start of a finalization. ``data`` carries the meeting and
            the gremium. A failed render sets the protocol back to a draft, and a new
            finalization writes a new entry.
        PROTOCOL_PUBLICATION: A protocol held back from the public protocols page or
            released. ``data`` carries the meeting, the gremium and the old and new
            ``publicWithheld``.
        PROTOKOLLANT_HANDOVER: Handover of the minutes in a live meeting. ``data``
            carries the ``mode`` (``now``, ``next_item``, ``activate`` when an agenda
            move starts the planned period, ``cancel`` when the planned handover goes
            away), the principal ids ``from`` and ``to`` and the current agenda item.
        VOTE_DELETE: Vote removed before it opened. A vote with ballots is not
            deletable.
        VOTE_CLOSE: ``data`` holds the result and the counts per option, never a
            voter.
        VOTE_CANCEL: ``data`` holds the reason: a person cancelled, or the application
            left the vote state.
        VOTE_BRANCH_BLOCKED: A close whose pass or fail transition did not fire (the
            guard failed, or the state has no such transition). The vote stays closed
            and the application stays in its state.
        VOTE_LOT_DRAWN: The platform drew the lot of an election tie. ``data`` carries
            the candidate ids (``among``, ``seats``, ``drawn``).
        POLL_CREATED: A poll ("Umfrage") was created, or (POLL_UPDATED) its question,
            options or end changed before the first answer. ``data`` carries the mode
            and the number of options. Open, close and cancel of a poll write
            VOTE_OPEN, VOTE_CLOSE and VOTE_CANCEL with ``kind: poll``.
        MEETING_PUBLIC_JOIN_CHANGED: Public meeting with a QR code; the meeting lead is
            the actor. The ``GUEST_*`` entries NEVER carry the name of a guest. A
            guest ballot writes VOTE_CAST with the actor ``guest:<meeting_guest.id>``
            and no choice.
        PII_EXPORT: GDPR export (Art. 15). ANONYMIZATION and the ``ERASURE_*`` entries
            cover erasure (Art. 17) and its request queue, RETENTION_ANONYMIZE covers
            retention (Art. 5(1)(e)).
        PRINCIPAL_MERGE: An admin merged an old principal into a new one. ``data``
            holds the two principal ids and the counts per area. The log rows of the
            old principal stay unchanged; the display resolves its ``sub`` through
            ``principal.merged_into``.
        PRINCIPAL_ACCESS_REVOKE: Revoke the rights of a person who no longer logs in.
            ``data`` holds the gremium ids, the removed SSO group names, the ids of the
            deleted role assignments, pool entries and revoked delegations, and the
            ``deactivate`` flag.
        BUDGET_NODE_CREATE: The ``BUDGET_*`` entries cover cost-center CRUD,
            allocation, bookings, transfers, invoices and moves of an application to
            another cost center or fiscal year. ``data`` carries ids and amounts.
        BACKUP_CREATE: The ``BACKUP_*`` entries are gated by ``backup.manage``.
            ``data`` carries the backup id, the kind and size metadata, never archive
            contents. A restore replaces the database, so the BACKUP_RESTORE entry
            lands in the chain of the restored state, after the safety backup that the
            restore takes first.
    """

    LOGIN = "login"
    STATUS_CHANGE = "status_change"
    VOTE_CAST = "vote_cast"
    CONFIG_CHANGE = "config_change"
    CONFIG_ACTIVATION = "config_activation"
    CONFIG_REVERT = "config_revert"
    ROLE_CHANGE = "role_change"
    DELEGATION_GRANT = "delegation_grant"
    DELEGATION_REVOKE = "delegation_revoke"
    DELEGATION_USE = "delegation_use"
    DELEGATION_SUBSTITUTE_ADD = "delegation_substitute_add"
    DELEGATION_SUBSTITUTE_REMOVE = "delegation_substitute_remove"
    EXPORT = "export"
    MEETING_DELETE = "meeting_delete"
    MEETING_CREATE = "meeting_create"
    MEETING_UPDATE = "meeting_update"
    AGENDA_ITEM_ADD = "agenda_item_add"
    AGENDA_ITEM_UPDATE = "agenda_item_update"
    AGENDA_ITEM_REMOVE = "agenda_item_remove"
    AGENDA_REORDER = "agenda_reorder"
    AGENDA_ITEM_DONE = "agenda_item_done"
    AGENDA_ITEM_REOPENED = "agenda_item_reopened"
    ATTENDANCE_SET = "attendance_set"
    ATTENDANCE_RESET = "attendance_reset"
    APPLICATION_DELETE = "application_delete"
    APPLICATION_CREATE = "application_create"
    APPLICATION_CREATE_ON_BEHALF = "application_create_on_behalf"
    GUEST_APPLICATION_DISCARD = "guest_application_discard"
    APPLICATION_UPDATE = "application_update"
    APPLICATION_ARCHIVE = "application_archive"
    APPLICATION_UNARCHIVE = "application_unarchive"
    APPLICATION_SHARE = "application_share"
    APPLICATION_SHARE_REVOKE = "application_share_revoke"
    APPLICATION_DECISION = "application_decision"
    WEBHOOK_CONFIG = "webhook_config"
    ATTACHMENT_UPLOAD = "attachment_upload"
    ATTACHMENT_QUARANTINE = "attachment_quarantine"
    ATTACHMENT_DELETE = "attachment_delete"
    COMMENT_UPDATE = "comment_update"
    COMMENT_DELETE = "comment_delete"
    PROTOCOL_DELETE = "protocol_delete"
    PROTOCOL_FINALIZE = "protocol_finalize"
    PROTOCOL_PUBLICATION = "protocol_publication"
    PROTOKOLLANT_HANDOVER = "protokollant_handover"
    VOTE_DELETE = "vote_delete"
    VOTE_OPEN = "vote_open"
    VOTE_CLOSE = "vote_close"
    VOTE_CANCEL = "vote_cancel"
    VOTE_BRANCH_BLOCKED = "vote_branch_blocked"
    VOTE_LOT_DRAWN = "vote_lot_drawn"
    POLL_CREATED = "poll_created"
    POLL_UPDATED = "poll_updated"
    MEETING_PUBLIC_JOIN_CHANGED = "meeting_public_join_changed"
    MEETING_JOIN_CODE_ROTATED = "meeting_join_code_rotated"
    GUEST_ADMITTED = "guest_admitted"
    GUEST_REJECTED = "guest_rejected"
    GUEST_REMOVED = "guest_removed"
    GUEST_RENAMED = "guest_renamed"
    GUEST_ADMIT_ALL = "guest_admit_all"
    PII_EXPORT = "pii_export"
    ANONYMIZATION = "anonymization"
    ERASURE_REQUESTED = "erasure_requested"
    ERASURE_EXECUTED = "erasure_executed"
    ERASURE_REJECTED = "erasure_rejected"
    PRINCIPAL_ERASED = "principal_erased"
    PRINCIPAL_MERGE = "principal_merge"
    PRINCIPAL_ACCESS_REVOKE = "principal_access_revoke"
    RETENTION_ANONYMIZE = "retention_anonymize"
    BUDGET_NODE_CREATE = "budget_node_create"
    BUDGET_NODE_UPDATE = "budget_node_update"
    BUDGET_NODE_DELETE = "budget_node_delete"
    BUDGET_FISCAL_YEAR_DELETE = "budget_fiscal_year_delete"
    BUDGET_FISCAL_YEAR_CLOSE = "budget_fiscal_year_close"
    BUDGET_FISCAL_YEAR_REOPEN = "budget_fiscal_year_reopen"
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
    BACKUP_CREATE = "backup_create"
    BACKUP_DELETE = "backup_delete"
    BACKUP_EXPORT = "backup_export"
    BACKUP_IMPORT = "backup_import"
    BACKUP_RESTORE = "backup_restore"


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
