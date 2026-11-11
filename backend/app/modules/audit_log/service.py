"""The admin view of the audit log: target labels and the revertable flag.

`AuditLogService` adds to `AuditService` the reads that need the models of other
modules: the label of each target, the label of each id in the entry data, and the
flag that tells whether the log can revert an entry. They are in `audit_log` and not
in `audit`, because `audit` must import no higher module (§S/backend/python/000649).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import Row, select

from app.modules.audit.actions import REVERTABLE_BUDGET_ACTIONS, AuditAction
from app.modules.audit.models import (
    AuditEntry,
)
from app.modules.audit.service import AuditService


def _as_uuid(value: str) -> uuid.UUID | None:
    """Parse ``value`` as a UUID. Return ``None`` when it is not one."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def data_uuid_strings(data: object) -> frozenset[str]:
    """Collect every UUID-shaped string value from a ``data`` payload, recursively.

    The caller resolves the entity ids inside ``data`` to display names with this
    set. The walk ignores keys and looks at values only.
    """
    match data:
        case str():
            return frozenset({data}) if _as_uuid(data) is not None else frozenset()
        case dict():
            return frozenset[str]().union(*(data_uuid_strings(v) for v in data.values()))
        case list() | tuple():
            return frozenset[str]().union(*(data_uuid_strings(v) for v in data))
        case _:
            return frozenset()


def _i18n_label(names: object) -> str | None:
    """Pick the German name of an i18n map, else its first name. ``None`` for no name."""
    match names:
        case dict() if names:
            return names.get("de") or next(iter(names.values()), None)
        case _:
            return None


def _application_title(data: Mapping[str, Any] | None) -> str | None:
    """Return the stripped ``title`` of an application ``data``. ``None`` when it is blank."""
    title = (data or {}).get("title")
    return (title.strip() or None) if isinstance(title, str) else None


def _first_wins(pairs: Iterable[tuple[str, str | None]]) -> dict[str, str]:
    """Map each key to its first non-empty label.

    A later pair never overwrites an earlier one, so the order of the pairs is the
    priority of the lookups.
    """
    return dict(reversed([(key, label) for key, label in pairs if label]))


def _uuids_by_type(
    targets: Iterable[tuple[str | None, str | None]],
) -> dict[str, frozenset[uuid.UUID]]:
    """Group the ids of ``(target_type, target_id)`` pairs by type.

    A pair without a type or an id drops out, and so does an id that is not a UUID,
    because no table can resolve them.
    """
    parsed = tuple(
        (target_type, target_uuid)
        for target_type, target_id in targets
        if target_type and target_id
        if (target_uuid := _as_uuid(target_id)) is not None
    )
    return {
        target_type: frozenset(u for t, u in parsed if t == target_type)
        for target_type in dict.fromkeys(t for t, _ in parsed)
    }


def _type_label_pairs(
    rows: Iterable[Row[uuid.UUID, dict[str, Any]]],
    form_ids: Collection[uuid.UUID],
    type_ids: Collection[uuid.UUID],
) -> tuple[tuple[tuple[str, str], str | None], ...]:
    """Label the ``form`` and the ``application_type`` targets from one name query.

    A form target holds the id of its application type, and the type name is the only
    name a form has. A row that both lists ask for gives two labels.
    """
    return tuple(
        ((target_type, str(row_id)), _i18n_label(name_i18n))
        for row_id, name_i18n in rows
        for target_type, ids in (("form", form_ids), ("application_type", type_ids))
        if row_id in ids
    )


def _revertable_without_revision(action: str, data: Mapping[str, Any]) -> bool:
    """Tell whether an entry without a config revision is revertable.

    A status change needs both states. A budget update needs the captured prior
    state, and an allocation needs the previous amount. The other revertable budget
    actions need nothing more.
    """
    match action:
        case AuditAction.STATUS_CHANGE:
            return bool(data.get("fromStateId") and data.get("toStateId"))
        case AuditAction.BUDGET_NODE_UPDATE | AuditAction.BUDGET_EXPENSE_UPDATE:
            return bool(data.get("before"))
        case AuditAction.BUDGET_ALLOCATION_SET:
            return "previousAllocated" in data
        case _:
            return action in REVERTABLE_BUDGET_ACTIONS


class AuditLogService(AuditService):
    """The audit service with the reads of the admin view."""

    async def revertable_flags(
        self, entries: Sequence[AuditEntry]
    ) -> dict[int, bool]:
        """Determine for each entry whether the log can revert it.

        The check is cheap and mostly static, because the list view needs it for
        every row. It runs no per-row head or stale check. The actual revert call
        enforces those and answers 409. A config change without a predecessor is not
        revertable. A budget update needs the captured prior state. One batch lookup
        resolves the config-snapshot predecessor check.
        """
        revision_ids = {
            e.id: str(rid) for e in entries if (rid := (e.data or {}).get("revisionId"))
        }
        static = {
            e.id: e.id not in revision_ids
            and _revertable_without_revision(e.action, e.data or {})
            for e in entries
        }
        by_revision = {
            revision_uuid: eid
            for eid, rid in revision_ids.items()
            if (revision_uuid := _as_uuid(rid)) is not None
        }
        predecessors = await self._revision_predecessors(by_revision)
        return {**static, **predecessors}

    async def _revision_predecessors(
        self, by_revision: Mapping[uuid.UUID, int]
    ) -> dict[int, bool]:
        """Map the entry of each config revision to whether the revision has a predecessor.

        One batch query serves all revisions. An empty map runs no query.
        """
        from app.modules.config_revision.models import ConfigRevision

        rows = await self._rows_for(
            by_revision,
            select(ConfigRevision.id, ConfigRevision.prev_revision_id).where(
                ConfigRevision.id.in_(by_revision.keys())
            ),
        )
        return {
            by_revision[rev_id]: prev_id is not None
            for rev_id, prev_id in rows
            if rev_id in by_revision
        }

    async def resolve_target_labels(
        self, targets: Sequence[tuple[str | None, str | None]]
    ) -> dict[tuple[str, str], str]:
        """Resolve each ``(target_type, target_id)`` pair to a readable label.

        The lookup runs in batches and is best effort. It resolves only a type that
        has a name source. A deleted target and a non-UUID id are absent from the
        map. The method adds no PII beyond the read view. A holder of ``audit.read``
        can reach all of it through the admin views.

        A config target keeps the id of the entity it configures. ``form`` therefore
        holds an ``application_type`` id and reads the same table. ``flow`` holds the
        literal id ``global`` and ``notification_settings`` holds ``1``. Both are
        singletons with no name column, so no lookup can resolve them. A
        non-UUID id (for example an export filename) is its own label.

        One query serves ``form`` and ``application_type``, because the type name is
        the only name a form has. A principal target names the account itself (the
        merge entry names the old account); only an account without a name of its own
        shows the name of the account it was merged into. A draft attachment has no
        application yet, so its file name stays out of the log view until the create
        binds it. A site-config version has no name column, so its version number is
        the label: it tells two drafts apart and reads the same in both UI locales.
        """
        from app.modules.application_types.models import ApplicationType
        from app.modules.applications.models import Application
        from app.modules.auth.identity import refs_by_id
        from app.modules.auth.models import Role
        from app.modules.files.models import Attachment
        from app.modules.gremien.models import Gremium
        from app.modules.site_config.models import CdVariant, SiteConfigVersion
        from app.modules.voting.models import Vote
        from app.modules.webhooks.models import Webhook

        by_type = _uuids_by_type(targets)
        application_ids = by_type.get("application", frozenset())
        gremium_ids = by_type.get("gremium", frozenset())
        form_ids = by_type.get("form", frozenset())
        type_ids = by_type.get("application_type", frozenset())
        role_ids = by_type.get("role", frozenset())
        webhook_ids = by_type.get("webhook", frozenset())
        vote_ids = by_type.get("vote", frozenset())
        attachment_ids = by_type.get("attachment", frozenset())
        cd_variant_ids = by_type.get("cd_variant", frozenset())
        site_config_ids = by_type.get("site_config", frozenset())
        applications = await self._rows_for(
            application_ids,
            select(Application.id, Application.data).where(Application.id.in_(application_ids)),
        )
        gremien = await self._rows_for(
            gremium_ids, select(Gremium.id, Gremium.name).where(Gremium.id.in_(gremium_ids))
        )
        types = await self._rows_for(
            form_ids | type_ids,
            select(ApplicationType.id, ApplicationType.name_i18n).where(
                ApplicationType.id.in_(form_ids | type_ids)
            ),
        )
        roles = await self._rows_for(
            role_ids, select(Role.id, Role.name_i18n, Role.key).where(Role.id.in_(role_ids))
        )
        principals = await refs_by_id(self.session, by_type.get("principal", frozenset()))
        named_queries = (
            (
                "webhook",
                webhook_ids,
                select(Webhook.id, Webhook.name).where(Webhook.id.in_(webhook_ids)),
            ),
            ("vote", vote_ids, select(Vote.id, Vote.question).where(Vote.id.in_(vote_ids))),
            (
                "attachment",
                attachment_ids,
                select(Attachment.id, Attachment.filename).where(
                    Attachment.id.in_(attachment_ids), Attachment.application_id.is_not(None)
                ),
            ),
            (
                "cd_variant",
                cd_variant_ids,
                select(CdVariant.id, CdVariant.name).where(CdVariant.id.in_(cd_variant_ids)),
            ),
        )
        named = [
            (target_type, await self._rows_for(ids, stmt))
            for target_type, ids, stmt in named_queries
        ]
        site_configs = await self._rows_for(
            site_config_ids,
            select(SiteConfigVersion.id, SiteConfigVersion.version).where(
                SiteConfigVersion.id.in_(site_config_ids)
            ),
        )
        pairs = (
            *((("application", str(i)), _application_title(data)) for i, data in applications),
            *_type_label_pairs(types, form_ids, type_ids),
            *((("role", str(i)), _i18n_label(name_i18n) or key) for i, name_i18n, key in roles),
            *((("principal", str(i)), ref.label) for i, ref in principals.items()),
            *(
                ((target_type, str(i)), name)
                for target_type, rows in (("gremium", gremien), *named)
                for i, name in rows
            ),
            *((("site_config", str(i)), f"Version {version}") for i, version in site_configs),
        )
        return {key: label for key, label in pairs if label}

    async def resolve_data_ids(
        self, data_dicts: Sequence[dict[str, Any] | None]
    ) -> dict[str, str]:
        """Resolve the UUIDs inside ``data`` payloads to display names, in batches.

        The keys of ``data`` are untyped. The method therefore collects every
        UUID-shaped value recursively and resolves it per table with an
        ``id IN (...)`` query. A UUID is globally unique, so the tables cannot
        collide. An id that the method cannot resolve, and an id of a deleted row,
        are absent from the map. The method exposes no extra PII beyond the admin
        views.

        The title of an application lives in its JSONB ``data``. An id of a principal
        names the account itself (``sourceId`` of a merge names the old one). The
        order of the lookups does not matter, because no lookup overwrites an entry.
        """
        candidates = frozenset(
            uuid.UUID(s) for d in data_dicts for s in data_uuid_strings(d)
        )
        return await self._data_id_labels(candidates) if candidates else {}

    async def _data_id_labels(self, candidates: frozenset[uuid.UUID]) -> dict[str, str]:
        """Look up the candidate ids table by table, in a fixed order.

        The first table that names an id wins, because `_first_wins` keeps the first
        label of each id.
        """
        from app.modules.application_types.models import ApplicationType
        from app.modules.applications.models import Application
        from app.modules.auth.identity import refs_by_id
        from app.modules.auth.models import Role
        from app.modules.budget.tree_models import Budget, FiscalYear
        from app.modules.files.models import Attachment
        from app.modules.gremien.models import Gremium
        from app.modules.livevote.models import Meeting
        from app.modules.voting.models import Vote
        from app.modules.webhooks.models import Webhook

        applications = await self._rows_for(
            candidates,
            select(Application.id, Application.data).where(Application.id.in_(candidates)),
        )
        named_queries = (
            select(Gremium.id, Gremium.name).where(Gremium.id.in_(candidates)),
            select(Budget.id, Budget.name).where(Budget.id.in_(candidates)),
            select(Meeting.id, Meeting.title).where(Meeting.id.in_(candidates)),
            select(Webhook.id, Webhook.name).where(Webhook.id.in_(candidates)),
            select(Vote.id, Vote.question).where(Vote.id.in_(candidates)),
            select(Attachment.id, Attachment.filename).where(
                Attachment.id.in_(candidates), Attachment.application_id.is_not(None)
            ),
        )
        named = [await self._rows_for(candidates, stmt) for stmt in named_queries]
        principals = await refs_by_id(self.session, candidates)
        roles = await self._rows_for(
            candidates,
            select(Role.id, Role.name_i18n, Role.key).where(Role.id.in_(candidates)),
        )
        types = await self._rows_for(
            candidates,
            select(ApplicationType.id, ApplicationType.name_i18n).where(
                ApplicationType.id.in_(candidates)
            ),
        )
        years = await self._rows_for(
            candidates,
            select(FiscalYear.id, FiscalYear.year).where(FiscalYear.id.in_(candidates)),
        )
        return _first_wins(
            (
                *((str(i), _application_title(data)) for i, data in applications),
                *((str(i), name) for rows in named for i, name in rows),
                *((str(i), ref.label) for i, ref in principals.items()),
                *((str(i), _i18n_label(name_i18n) or key) for i, name_i18n, key in roles),
                *((str(i), _i18n_label(name_i18n)) for i, name_i18n in types),
                *((str(i), str(year)) for i, year in years),
            )
        )
