"""RBAC-Auflösung (security.md §2, api.md §1).

App-seitige Rollen sind die Wahrheit: Permissions stammen aus `role_assignment`
(zeit-validiert: Vertretung/Delegation) **plus** optional `group_mapping`
(OIDC-Gruppe → Rolle, Komfort). Gremium-Scope eines Assignments/Mappings landet als
Gruppen-Key in `Principal.groups` (`require_group` greift darauf).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.auth.models import GroupMapping, Role, RoleAssignment, RolePermission
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal


def vote_group_key(gremium_id: object) -> str:
    """Namespaced group key for *gremium voting eligibility*.

    The cast gate must depend on a real ``vote.cast`` Gremium-membership, never on
    a raw OIDC group claim that merely happens to equal a gremium UUID string
    (AUD-066). Prefixing the internal key (``vote:<uuid>``) makes it impossible for
    an arbitrary IdP-emitted group name to collide with — and thereby satisfy —
    gremium cast eligibility. ``Vote.eligible_group`` stays the bare UUID-as-text
    (it is parsed back to a UUID for gremium/delegation resolution); the voting
    service derives this prefixed key from that UUID for the membership check.
    """
    return f"vote:{gremium_id}"


def _as_aware(dt: datetime | None) -> datetime | None:
    """Naive Werte als UTC interpretieren (defensiv: Alt-Daten/timestamp ohne tz).

    Der Rest des Codes rechnet mit aware-UTC (``datetime.now(UTC)``). Eine naive
    ``valid_from``/``valid_until`` aus der DB würde sonst beim Vergleich mit dem
    aware ``now`` ``TypeError: can't compare offset-naive and offset-aware
    datetimes`` werfen und so die komplette Principal-Auflösung (REST **und**
    WS-Handshake) lahmlegen.
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _assignment_valid(
    valid_from: datetime | None, valid_until: datetime | None, now: datetime
) -> bool:
    """Gültigkeitsfenster (Vertretung/Delegation) prüfen.

    ``now`` ist immer aware-UTC (Aufrufer); nur die DB-Spalten können naiv sein.
    """
    valid_from = _as_aware(valid_from)
    valid_until = _as_aware(valid_until)
    after_start = valid_from is None or valid_from <= now
    before_end = valid_until is None or valid_until >= now
    return after_start and before_end


async def resolve_principal(db: AsyncSession, row: PrincipalRow, now: datetime) -> Principal:
    """`principal`-Zeile → vollständiger `Principal` (Rollen/Permissions/Gruppen)."""
    groups: set[str] = {str(g) for g in (row.oidc_groups or [])}
    role_ids: set = set()

    assignments = (
        await db.execute(
            select(RoleAssignment).where(RoleAssignment.principal_id == row.id)
        )
    ).scalars().all()
    for a in assignments:
        if _assignment_valid(a.valid_from, a.valid_until, now):
            role_ids.add(a.role_id)
            if a.gremium_id is not None:
                groups.add(str(a.gremium_id))

    if groups:
        mappings = (
            await db.execute(
                select(GroupMapping).where(GroupMapping.oidc_group.in_(groups))
            )
        ).scalars().all()
        for m in mappings:
            role_ids.add(m.role_id)
            if m.gremium_id is not None:
                groups.add(str(m.gremium_id))

    permissions: set[str] = set()
    role_keys: list[str] = []
    if role_ids:
        permissions = set(
            (
                await db.execute(
                    select(RolePermission.permission).where(
                        RolePermission.role_id.in_(role_ids)
                    )
                )
            ).scalars().all()
        )
        role_keys = list(
            (
                await db.execute(select(Role.key).where(Role.id.in_(role_ids)))
            ).scalars().all()
        )

    # Gremium-Mitgliedschaften (#Sessions): wer in einem Gremium eine aktive Rolle mit
    # ``vote.cast`` hat, ist in der Gremium-Gruppe stimmberechtigt. Der Cast-Gate prüft
    # den NAMESPACED Key ``vote:<gremium_id>`` (``vote_group_key``), nie den nackten
    # UUID-String — so kann ein deckungsgleicher OIDC-Gruppen-Claim die Gremium-
    # Stimmberechtigung nicht fälschlich erfüllen (AUD-066). Das bloße Mitlesen einer
    # Sitzung läuft über ``MeetingService.is_member`` (eigene Query).
    membership_rows = (
        await db.execute(
            select(GremiumMembership.gremium_id, GremiumRole.permissions)
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .where(
                GremiumMembership.principal_id == row.id,
                (GremiumMembership.valid_from.is_(None))
                | (GremiumMembership.valid_from <= now),
                (GremiumMembership.valid_until.is_(None))
                | (GremiumMembership.valid_until > now),
            )
        )
    ).all()
    for gremium_id, perms in membership_rows:
        if "vote.cast" in (perms or []):
            groups.add(vote_group_key(gremium_id))

    return Principal(
        sub=row.sub,
        email=row.email,
        display_name=row.display_name,
        roles=role_keys,
        permissions=permissions,
        groups=groups,
    )
