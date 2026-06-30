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
    # Rücknahme eines Config-Changes aus dem Audit-Log (#config-versioning,
    # ``audit.revert``). Trägt im ``data`` die zurückgenommene Audit-/Revision-Id +
    # die neue ``revisionId`` (selbst revertierbar). Nur id-Referenzen.
    CONFIG_REVERT = "config_revert"
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
    # Antrag gelöscht (#AUD-002) — irreversibler Admin-Vorgang, kaskadiert auf
    # Antragsteller-PII/Versionen/Status-Events/Magic-Links/Kommentare sowie 1:1
    # ``budget_entry`` und ``Vote``-Zeilen. ``data`` trägt nur id-Referenzen/Metadaten
    # (Typ/Gremium/Status/Versionsanzahl), niemals rohe PII (security.md §4).
    APPLICATION_DELETE = "application_delete"
    WEBHOOK_CONFIG = "webhook_config"
    ATTACHMENT_QUARANTINE = "attachment_quarantine"
    ATTACHMENT_DELETE = "attachment_delete"
    # DSGVO/PII (#PII-Re-Add): Auskunft (Art. 15), Löschung/Anonymisierung (Art. 17),
    # Aufbewahrung (Art. 5(1)(e)) + Löschantrags-Queue. ``data`` trägt nur id-/E-Mail-
    # Referenzen + Metadaten, nie rohe PII-Werte (security.md §4).
    PII_ACCESS = "pii_access"
    PII_DELETION = "pii_deletion"
    PII_EXPORT = "pii_export"
    ANONYMIZATION = "anonymization"
    ERASURE_REQUESTED = "erasure_requested"
    ERASURE_EXECUTED = "erasure_executed"
    ERASURE_REJECTED = "erasure_rejected"
    PRINCIPAL_ERASED = "principal_erased"
    RETENTION_ANONYMIZE = "retention_anonymize"
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
    # FinTS-Bankabgleich (#fints): Bank-Verbindung gesetzt (keine PIN/kein Klartext im
    # ``data``, nur Konto-id + Endpunkt/BLZ), persönliche Zugangsdaten eines Buchers
    # gesetzt/gelöscht (#fints-percred; nur Konto-id, der ``actor`` ist der Bucher),
    # Sync-Lauf, Umsatz-Import (Anzahl), Abgleich eines Umsatzes auf eine Buchung,
    # Ignorieren. Nur id-Referenzen/Zähler (security.md §4).
    BANK_ACCOUNT_CONFIG = "bank_account_config"
    BANK_CREDENTIAL_SET = "bank_credential_set"
    BANK_CREDENTIAL_DELETE = "bank_credential_delete"
    BANK_SYNC = "bank_sync"
    BANK_STATEMENT_IMPORT = "bank_statement_import"
    BANK_LINE_RECONCILE = "bank_line_reconcile"
    BANK_LINE_IGNORE = "bank_line_ignore"
    BANK_LINE_UNLINK = "bank_line_unlink"


# Budget-/Geld-Mutationen, die aus dem Audit-Log zurückgenommen werden können
# (#config-versioning). Additive Vorgänge werden gelöscht, Änderungen aus dem im
# Audit-``data`` festgehaltenen Vorzustand wiederhergestellt. Löschungen sind bewusst
# NICHT enthalten (kein Wieder-Anlegen) — ebenso Zuordnung/HHJ-Verschiebung.
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
