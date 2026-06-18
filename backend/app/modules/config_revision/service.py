"""Config-Revision-Service: append-only Snapshot-Kette + Diff (#config-versioning).

* :meth:`record` — neuen Snapshot anhängen **und** den verlinkten Audit-Eintrag
  schreiben (``data.revisionId`` — nur id-Referenz, security.md §4). Vor dem Lesen des
  Kopf-Standes wird ein **Transaktions-Advisory-Lock** je Entität genommen → konkurrierende
  Appends serialisieren, ``version``/``prev`` bleiben konsistent.
* :meth:`list_for` — Versions-Sidebar-Feed (neueste zuerst).
* :meth:`diff` — Feld-Diff zweier aufeinanderfolgender Snapshots (wie Antrags-Detail,
  :func:`app.modules.applications.diff.compute_diff`).

Kein Commit — die aufrufende Transaktion committet (atomar mit der Config-Mutation).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.diff import DataDiff, compute_diff
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.config_revision.models import ConfigRevision

# Stabile ``entity_type``-Schlüssel (= Audit ``target_type``).
ENTITY_FORM = "form"
ENTITY_FLOW = "flow"
ENTITY_SITE_CONFIG = "site_config"

# Globale (typ-unabhängige) Entitäten teilen sich diese ``entity_id``.
GLOBAL_ID = "global"


def _lock_key(entity_type: str, entity_id: str) -> int:
    """Stabiler 64-Bit-Advisory-Lock-Schlüssel je Entität (prozess-/host-stabil).

    ``pg_advisory_xact_lock`` braucht für dieselbe Entität in konkurrierenden Backends
    denselben Schlüssel → kein ``hash()`` (per Prozess randomisiert), sondern ein
    deterministischer BLAKE2b-Digest, als **signed bigint** (Postgres-Range) eingebettet.
    Reine Integer-Konstante im SQL → kein Bind-Param nötig, injection-sicher.
    """
    digest = hashlib.blake2b(
        f"{entity_type}:{entity_id}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big", signed=True)


def _flatten(entity_type: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Snapshot → flache ``{identität: wert}``-Map für den Feld-Diff.

    Die natürliche Snapshot-Form (Felder-Liste / FlowGraph / Branding-Dict) wird auf
    stabile, identitäts-getragene Schlüssel abgebildet, damit
    :func:`compute_diff` ein sinnvolles added/removed/changed pro Feld/State/Transition
    liefert (statt eines opaken Listen-Vergleichs).
    """
    if entity_type == ENTITY_FORM:
        flat: dict[str, Any] = {}
        for field in snapshot.get("fields", []) or []:
            if isinstance(field, dict) and field.get("key"):
                flat[f"field:{field['key']}"] = field
        if snapshot.get("description") is not None:
            flat["meta:description"] = snapshot["description"]
        return flat
    if entity_type == ENTITY_FLOW:
        flat = {}
        for state in snapshot.get("states", []) or []:
            if isinstance(state, dict) and state.get("key"):
                flat[f"state:{state['key']}"] = state
        for tr in snapshot.get("transitions", []) or []:
            if isinstance(tr, dict):
                ident = f"{tr.get('from')}->{tr.get('to')}"
                if tr.get("branch"):
                    ident += f":{tr['branch']}"
                flat[f"transition:{ident}"] = tr
        if snapshot.get("layout"):
            flat["meta:layout"] = snapshot["layout"]
        return flat
    if entity_type == ENTITY_SITE_CONFIG:
        # Branding ist bereits eine flache (verschachtelte) Top-Level-Map.
        return dict(snapshot)
    return dict(snapshot)


class ConfigRevisionService:
    """An eine ``AsyncSession`` gebundener Revision-Service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def head(self, entity_type: str, entity_id: str) -> ConfigRevision | None:
        """Aktueller (jüngster) Snapshot einer Entität — ``None``, wenn keiner existiert."""
        return await self.session.scalar(
            select(ConfigRevision)
            .where(
                ConfigRevision.entity_type == entity_type,
                ConfigRevision.entity_id == entity_id,
            )
            .order_by(ConfigRevision.version.desc())
            .limit(1)
        )

    async def get(self, revision_id: UUID | str) -> ConfigRevision | None:
        if isinstance(revision_id, str):
            try:
                revision_id = UUID(revision_id)
            except ValueError:
                return None
        return await self.session.get(ConfigRevision, revision_id)

    async def list_for(
        self, entity_type: str, entity_id: str
    ) -> list[ConfigRevision]:
        """Alle Snapshots einer Entität (neueste zuerst) — Versions-Sidebar."""
        return list(
            (
                await self.session.scalars(
                    select(ConfigRevision)
                    .where(
                        ConfigRevision.entity_type == entity_type,
                        ConfigRevision.entity_id == entity_id,
                    )
                    .order_by(ConfigRevision.version.desc())
                )
            ).all()
        )

    async def record(
        self,
        *,
        entity_type: str,
        entity_id: str,
        snapshot: dict[str, Any],
        actor: str,
        action: AuditAction = AuditAction.CONFIG_CHANGE,
        extra_data: dict[str, Any] | None = None,
    ) -> ConfigRevision:
        """Snapshot anhängen + verlinkten Audit-Eintrag schreiben (kein Commit).

        ``snapshot`` darf **nur Config** enthalten (keine Principal-PII). Der Audit-
        Eintrag trägt ``data.revisionId`` (id-Referenz) plus ``extra_data``.
        """
        # Append je Entität serialisieren (version/prev konsistent). Schlüssel ist eine
        # deterministische int-Konstante (kein User-Input) → direkt eingebettet, kein Bind.
        await self.session.execute(
            text(f"SELECT pg_advisory_xact_lock({_lock_key(entity_type, entity_id)})")
        )
        prev = await self.head(entity_type, entity_id)
        revision = ConfigRevision(
            entity_type=entity_type,
            entity_id=entity_id,
            version=(prev.version + 1) if prev is not None else 1,
            snapshot=snapshot,
            prev_revision_id=prev.id if prev is not None else None,
            created_by=actor,
        )
        self.session.add(revision)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=actor,
            action=action,
            target_type=entity_type,
            target_id=entity_id,
            data={
                "revisionId": str(revision.id),
                "version": revision.version,
                **(extra_data or {}),
            },
        )
        return revision

    async def diff(self, revision: ConfigRevision) -> DataDiff:
        """Feld-Diff dieses Snapshots gegen seinen Vorgänger (leer → erster Stand)."""
        prev_snapshot: dict[str, Any] = {}
        if revision.prev_revision_id is not None:
            prev = await self.session.get(ConfigRevision, revision.prev_revision_id)
            if prev is not None:
                prev_snapshot = prev.snapshot or {}
        return compute_diff(
            _flatten(revision.entity_type, prev_snapshot),
            _flatten(revision.entity_type, revision.snapshot or {}),
        )

    async def resolve_versions(
        self, revisions: Sequence[ConfigRevision]
    ) -> dict[UUID, int]:
        """``revision_id`` → ``version`` (für die Sidebar-Diff-Beschriftung)."""
        return {r.id: r.version for r in revisions}
