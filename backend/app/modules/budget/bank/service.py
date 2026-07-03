"""Public facade of the bank reconciliation.

:class:`BankService` bundles the sub-areas — the router hangs off exactly this
class. Implementation lives in the mixins: :class:`~.credentials.CredentialOps`
(personal FinTS credentials), :class:`~.sync.SyncOps` (live fetch + TAN
sessions), :class:`~.staging.StagingOps` (file import + idempotent staging),
:class:`~.reconcile.ReconcileOps` (confirm/ignore/unlink) and
:class:`~.listing.ListingOps` (filtered list).
"""

from __future__ import annotations

from app.modules.budget.bank.credentials import CredentialOps
from app.modules.budget.bank.listing import ListingOps
from app.modules.budget.bank.reconcile import ReconcileOps
from app.modules.budget.bank.sync import SyncOps


class BankService(CredentialOps, SyncOps, ReconcileOps, ListingOps):
    """FinTS-/file-based account reconciliation (bound to a session)."""
