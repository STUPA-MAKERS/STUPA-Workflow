"""Public facade of the bank reconciliation.

``BankService`` bundles the sub-areas. The router hangs off exactly this class.
The mixins hold the implementation. ``credentials.CredentialOps`` keeps the
personal FinTS credentials. ``sync.SyncOps`` runs the live fetch and the TAN
sessions. ``staging.StagingOps`` does the file import and the idempotent staging.
``reconcile.ReconcileOps`` covers confirm, ignore and unlink.
``listing.ListingOps`` returns the filtered list.
"""

from __future__ import annotations

from app.modules.budget.bank.credentials import CredentialOps
from app.modules.budget.bank.listing import ListingOps
from app.modules.budget.bank.reconcile import ReconcileOps
from app.modules.budget.bank.sync import SyncOps


class BankService(CredentialOps, SyncOps, ReconcileOps, ListingOps):
    """FinTS-/file-based account reconciliation (bound to a session)."""
