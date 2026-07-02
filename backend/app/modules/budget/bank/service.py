"""Öffentliche Fassade des Bankabgleichs (#fints).

:class:`BankService` bündelt die Teilbereiche — der Router (``tree_router``) hängt an
genau dieser Klasse. Die Implementierung liegt in den Teilklassen:

* :class:`~.credentials.CredentialOps` — persönliche FinTS-Zugangsdaten (#fints-percred)
* :class:`~.sync.SyncOps` — Live-Abruf + TAN-Sitzungen (erbt den Staging-Pfad)
* :class:`~.staging.StagingOps` — Datei-Import + idempotentes Einspielen (#fints-batch)
* :class:`~.reconcile.ReconcileOps` — bestätigen / ignorieren / lösen
* :class:`~.listing.ListingOps` — gefilterte Liste
"""

from __future__ import annotations

from app.modules.budget.bank.credentials import CredentialOps
from app.modules.budget.bank.listing import ListingOps
from app.modules.budget.bank.reconcile import ReconcileOps
from app.modules.budget.bank.sync import SyncOps


class BankService(CredentialOps, SyncOps, ReconcileOps, ListingOps):
    """FinTS-/Datei-gestützter Kontoabgleich (an eine Session gebunden)."""
