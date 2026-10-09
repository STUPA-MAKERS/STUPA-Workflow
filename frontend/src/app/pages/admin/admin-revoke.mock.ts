/**
 * The mock of "Rechte entziehen" (F3) for the admin API in mock mode.
 *
 * It mirrors `backend/app/modules/admin/principal_revoke.py` on the in-memory store: the
 * Gremien of a person come from the memberships (static, plus the ones that the OIDC
 * groups give through the membership mappings), the manual gremium assignments, the pool
 * entries and the delegations; the global roles from the group mappings and the manual
 * assignments (never `member`). A revoke removes the groups, the assignments and the
 * extras of the selected entries, and refuses a half selection of a shared group with
 * 422 `revoke_incomplete`.
 */
import type { Uuid } from '@core/api/models';
import type {
  AdminPrincipal,
  Gremium,
  GremiumMembership,
  GremiumMembershipMapping,
  GremiumRole,
  GremiumRoleMapping,
  GroupMapping,
  PrincipalFilters,
  RevokeAssignment,
  RevokeDelegation,
  RevokeGremium,
  RevokePoolEntry,
  RevokePreview,
  RevokeRequest,
  RevokeResult,
  Role,
  RoleAssignment,
} from './admin.models';
import { MOCK_GREMIUM_STUPA_ID } from './admin.mock';

/** The role that every person holds. It is no right to take away. */
const IMPLICIT_ROLE = 'member';

/**
 * A stale demo person (the board of the mockup): last login in February, groups that
 * lead into both Gremien and to a global role, a pool entry and two delegations.
 */
export const MOCK_REVOKE_PRINCIPAL: AdminPrincipal = {
  id: 'p-12',
  sub: 'kc|tobias.kern',
  email: 'tobias.kern@stupa.example',
  displayName: 'Tobias Kern',
  lastLogin: '2026-02-12T10:15:00+00:00',
  oidcGroups: ['stupa-mitglieder', 'stupa-sitzungsleitung', 'gremien-alle', 'stupa-referate'],
  assignments: [
    {
      id: 'a-12',
      principalId: 'p-12',
      roleId: 'r-vorstand',
      gremiumId: 'g-asta',
      grantedBy: 'Alex Admin',
      validFrom: '2025-11-04T00:00:00+00:00',
      validUntil: null,
      delegateVoting: false,
    },
  ],
};

/**
 * A group that only this mock maps into BOTH Gremien. It shows how the dialog selects
 * a co-affected Gremium.
 */
const SHARED_GROUP: { oidcGroup: string; gremiumIds: Uuid[] } = {
  oidcGroup: 'gremien-alle',
  gremiumIds: [MOCK_GREMIUM_STUPA_ID, 'g-asta'],
};

interface PoolFact {
  id: Uuid;
  gremiumId: Uuid;
  memberId: Uuid | null;
  substituteId: Uuid;
}

interface DelegationFact {
  id: Uuid;
  gremiumId: Uuid;
  meetingId: Uuid;
  meetingTitle: string;
  meetingDate: string | null;
  live: boolean;
  delegatorId: Uuid;
  delegateId: Uuid;
  voting: boolean;
}

/** The pool entries and delegations of the mock (the revoke deletes from these lists). */
export function mockRevokeExtras(): { pool: PoolFact[]; delegations: DelegationFact[] } {
  return {
    pool: [
      { id: 'ds-1', gremiumId: MOCK_GREMIUM_STUPA_ID, memberId: 'p-2', substituteId: 'p-12' },
      { id: 'ds-2', gremiumId: 'g-asta', memberId: null, substituteId: 'p-12' },
    ],
    delegations: [
      {
        id: 'md-1',
        gremiumId: MOCK_GREMIUM_STUPA_ID,
        meetingId: 'd0000000-0000-0000-0000-000000000002',
        meetingTitle: 'StuPa-Sitzung Oktober',
        meetingDate: '2026-10-17',
        live: false,
        delegatorId: 'p-2',
        delegateId: 'p-12',
        voting: true,
      },
      {
        id: 'md-2',
        gremiumId: 'g-asta',
        meetingId: 'd0000000-0000-0000-0000-000000000001',
        meetingTitle: 'AStA-Sitzung',
        meetingDate: null,
        live: true,
        delegatorId: 'p-12',
        delegateId: 'p-7',
        voting: false,
      },
    ],
  };
}

/** The parts of the admin mock store that the revoke reads and writes. */
export interface RevokeMockStore {
  principals: AdminPrincipal[];
  gremien: Gremium[];
  gremiumRoles: GremiumRole[];
  roles: Role[];
  groupMappings: GroupMapping[];
  membershipMappings: GremiumMembershipMapping[];
  roleMappings: GremiumRoleMapping[];
  memberships: readonly GremiumMembership[];
  /** The Gremien cleared per principal: their static memberships no longer count. */
  revoked: Record<Uuid, Uuid[]>;
  extras: { pool: PoolFact[]; delegations: DelegationFact[] };
}

interface Ties {
  memberships: { gremiumId: Uuid; roleId: Uuid }[];
  membershipMaps: [string, Uuid][];
  roleMaps: [string, Uuid, Uuid][];
  groupMaps: [string, Uuid][];
  assignments: RoleAssignment[];
  pool: PoolFact[];
  delegations: DelegationFact[];
}

/** The SSO groups of a mock row. A row that the dev data leaves without groups has none. */
function groupsOf(p: AdminPrincipal): string[] {
  return Array.isArray(p.oidcGroups) ? p.oidcGroups : [];
}

function ties(store: RevokeMockStore, p: AdminPrincipal): Ties {
  const groups = new Set(groupsOf(p));
  const membershipMaps: [string, Uuid][] = [
    ...store.membershipMappings
      .filter((m) => groups.has(m.oidcGroup))
      .map((m): [string, Uuid] => [m.oidcGroup, m.gremiumId]),
    ...(groups.has(SHARED_GROUP.oidcGroup)
      ? SHARED_GROUP.gremiumIds.map((g): [string, Uuid] => [SHARED_GROUP.oidcGroup, g])
      : []),
  ];
  const roleMaps = store.roleMappings
    .filter((m) => groups.has(m.oidcGroup))
    .map((m): [string, Uuid, Uuid] => [m.oidcGroup, m.gremiumId, m.gremiumRoleId]);
  const derived = new Map<Uuid, Uuid>();
  for (const [, gid] of membershipMaps) {
    const mapped = roleMaps.find(([, g]) => g === gid);
    const fallback = store.gremiumRoles.find((r) => r.gremiumId === gid && r.key === IMPLICIT_ROLE);
    derived.set(gid, mapped?.[2] ?? fallback?.id ?? '');
  }
  const cleared = new Set(store.revoked[p.id] ?? []);
  for (const m of store.memberships) {
    if (m.principalId === p.id && !cleared.has(m.gremiumId) && !derived.has(m.gremiumId)) {
      derived.set(m.gremiumId, m.gremiumRoleId);
    }
  }
  return {
    memberships: [...derived].map(([gremiumId, roleId]) => ({ gremiumId, roleId })),
    membershipMaps,
    roleMaps,
    groupMaps: store.groupMappings
      .filter((m) => groups.has(m.oidcGroup))
      .map((m): [string, Uuid] => [m.oidcGroup, m.roleId]),
    assignments: p.assignments,
    pool: store.extras.pool.filter((e) => e.substituteId === p.id || e.memberId === p.id),
    delegations: store.extras.delegations.filter(
      (d) => d.delegatorId === p.id || d.delegateId === p.id,
    ),
  };
}

function roleKey(store: RevokeMockStore, roleId: Uuid): string {
  return store.roles.find((r) => r.id === roleId)?.key ?? roleId;
}

function tiedGremien(t: Ties): Set<Uuid> {
  return new Set([
    ...t.memberships.map((m) => m.gremiumId),
    ...t.membershipMaps.map(([, g]) => g),
    ...t.assignments.filter((a) => a.gremiumId).map((a) => a.gremiumId as Uuid),
    ...t.pool.map((e) => e.gremiumId),
    ...t.delegations.map((d) => d.gremiumId),
  ]);
}

function heldRoles(store: RevokeMockStore, t: Ties): Set<Uuid> {
  const ids = [...t.groupMaps.map(([, r]) => r), ...t.assignments.filter((a) => !a.gremiumId).map((a) => a.roleId)];
  return new Set(ids.filter((id) => roleKey(store, id) !== IMPLICIT_ROLE));
}

function targets(store: RevokeMockStore, p: AdminPrincipal, t: Ties): Map<string, [Set<Uuid>, Set<Uuid>]> {
  const tied = tiedGremien(t);
  const out = new Map<string, [Set<Uuid>, Set<Uuid>]>();
  const entry = (g: string) => {
    if (!out.has(g)) out.set(g, [new Set(), new Set()]);
    return out.get(g)!;
  };
  for (const [g, gid] of t.membershipMaps) entry(g)[0].add(gid);
  for (const [g, gid] of t.roleMaps) if (tied.has(gid)) entry(g)[0].add(gid);
  for (const [g, rid] of t.groupMaps) if (roleKey(store, rid) !== IMPLICIT_ROLE) entry(g)[1].add(rid);
  // In the order of the person's group list.
  return new Map(groupsOf(p).filter((g) => out.has(g)).map((g) => [g, out.get(g)!]));
}

function name(store: RevokeMockStore, id: Uuid | null): string | null {
  if (!id) return null;
  const p = store.principals.find((x) => x.id === id);
  return p ? (p.displayName ?? p.email ?? null) : null;
}

function assignmentOut(store: RevokeMockStore, a: RoleAssignment): RevokeAssignment {
  const role = store.roles.find((r) => r.id === a.roleId);
  return {
    id: a.id,
    roleId: a.roleId,
    roleKey: role?.key ?? a.roleId,
    roleLabel: role?.label ?? {},
    grantedBy: a.grantedBy ?? null,
    validFrom: a.validFrom ?? null,
    validUntil: a.validUntil ?? null,
  };
}

function delegationOut(store: RevokeMockStore, pid: Uuid, d: DelegationFact): RevokeDelegation {
  const asDelegator = d.delegatorId === pid;
  return {
    id: d.id,
    meetingId: d.meetingId,
    meetingTitle: d.meetingTitle,
    meetingDate: d.meetingDate,
    asDelegator,
    otherName: name(store, asDelegator ? d.delegateId : d.delegatorId),
    voting: d.voting,
  };
}

/** The mock answer of `GET /admin/principals/{id}/revoke-preview`. Null: unknown person. */
export function mockRevokePreview(store: RevokeMockStore, principalId: Uuid, mySub: string | null): RevokePreview | null {
  const p = store.principals.find((x) => x.id === principalId);
  if (!p) return null;
  const t = ties(store, p);
  const tgt = targets(store, p, t);
  const gremien: RevokeGremium[] = [...tiedGremien(t)].map((gid) => {
    const membership = t.memberships.find((m) => m.gremiumId === gid);
    const grole = membership ? store.gremiumRoles.find((r) => r.id === membership.roleId) : undefined;
    const causes = new Set([
      ...t.membershipMaps.filter(([, g]) => g === gid).map(([g]) => g),
      ...t.roleMaps.filter(([, , r]) => r === membership?.roleId).map(([g]) => g),
    ]);
    const pool: RevokePoolEntry[] = t.pool
      .filter((e) => e.gremiumId === gid)
      .map((e) => ({
        id: e.id,
        asSubstitute: e.substituteId === p.id,
        gremiumWide: e.memberId === null,
        memberName: name(store, e.memberId),
        substituteName: name(store, e.substituteId),
      }));
    const dels = t.delegations.filter((d) => d.gremiumId === gid);
    return {
      gremiumId: gid,
      name: store.gremien.find((g) => g.id === gid)?.name ?? '',
      membership: membership
        ? {
            roleKey: grole?.key ?? IMPLICIT_ROLE,
            roleLabel: grole?.name ?? {},
            groups: groupsOf(p).filter((g) => causes.has(g)),
          }
        : null,
      groups: [...tgt].filter(([, [gs]]) => gs.has(gid)).map(([g]) => g),
      assignments: t.assignments.filter((a) => a.gremiumId === gid).map((a) => assignmentOut(store, a)),
      poolEntries: pool,
      plannedDelegations: dels.filter((d) => !d.live).map((d) => delegationOut(store, p.id, d)),
      liveDelegations: dels.filter((d) => d.live).map((d) => delegationOut(store, p.id, d)),
      openTasks: membership && gid === MOCK_GREMIUM_STUPA_ID ? 1 : 0,
    };
  });
  gremien.sort((a, b) => a.name.localeCompare(b.name));
  const held = heldRoles(store, t);
  return {
    principal: {
      id: p.id,
      displayName: p.displayName ?? null,
      email: p.email ?? null,
      lastLogin: p.lastLogin ?? null,
      active: p.active !== false,
    },
    gremien,
    globalRoles: [...held].map((rid) => {
      const role = store.roles.find((r) => r.id === rid);
      return {
        roleId: rid,
        roleKey: role?.key ?? rid,
        roleLabel: role?.label ?? {},
        groups: [...tgt].filter(([, [, rs]]) => rs.has(rid)).map(([g]) => g),
        assignments: t.assignments
          .filter((a) => !a.gremiumId && a.roleId === rid)
          .map((a) => assignmentOut(store, a)),
      };
    }),
    groups: [...tgt].map(([group, [gs, rs]]) => ({ group, gremiumIds: [...gs], globalRoleIds: [...rs] })),
    isSelf: mySub !== null && p.sub === mySub,
  };
}

/** A refusal of the mock revoke, shaped like the problem body of the server. */
export interface MockProblem {
  status: number;
  error: { code: string; errors?: { field: string; msg: string }[] };
}

/** The mock of `POST /admin/principals/{id}/revoke`: apply it to the store or refuse. */
export function mockApplyRevoke(
  store: RevokeMockStore,
  principalId: Uuid,
  body: RevokeRequest,
  mySub: string | null,
): RevokeResult | MockProblem {
  const p = store.principals.find((x) => x.id === principalId);
  if (!p) return { status: 404, error: { code: 'not_found' } };
  if (mySub !== null && p.sub === mySub) return { status: 409, error: { code: 'revoke_own_account' } };
  if (!body.gremiumIds.length && !body.globalRoleIds.length && !body.deactivate) {
    return { status: 422, error: { code: 'revoke_empty' } };
  }
  const t = ties(store, p);
  const tgt = targets(store, p, t);
  const g = new Set(body.gremiumIds);
  const r = new Set(body.globalRoleIds);
  const removed = [...tgt].filter(([, [gs, rs]]) => [...gs].some((x) => g.has(x)) || [...rs].some((x) => r.has(x)));
  const missing = removed.flatMap(([, [gs, rs]]) => [
    ...[...gs].filter((x) => !g.has(x)).map((x) => ({ field: 'gremiumIds', msg: x })),
    ...[...rs].filter((x) => !r.has(x)).map((x) => ({ field: 'globalRoleIds', msg: x })),
  ]);
  if (missing.length) return { status: 422, error: { code: 'revoke_incomplete', errors: missing } };
  const gone = new Set(removed.map(([group]) => group));
  const deletedAssignments = p.assignments.filter((a) => (a.gremiumId ? g.has(a.gremiumId) : r.has(a.roleId)));
  p.oidcGroups = groupsOf(p).filter((x) => !gone.has(x));
  p.assignments = p.assignments.filter((a) => !deletedAssignments.includes(a));
  store.revoked[p.id] = [...(store.revoked[p.id] ?? []), ...g];
  const pool = t.pool.filter((e) => g.has(e.gremiumId));
  store.extras.pool = store.extras.pool.filter((e) => !pool.includes(e));
  const dels = t.delegations.filter((d) => g.has(d.gremiumId));
  const planned = dels.filter((d) => !d.live);
  store.extras.delegations = store.extras.delegations.filter((d) => !planned.includes(d));
  const deactivated = body.deactivate && p.active !== false;
  if (deactivated) p.active = false;
  return {
    gremiumIds: body.gremiumIds,
    globalRoleIds: body.globalRoleIds,
    removedGroups: [...gone],
    deletedAssignments: deletedAssignments.length,
    deletedPoolEntries: pool.length,
    revokedDelegations: planned.length,
    keptLiveDelegations: dels.length - planned.length,
    deactivated,
  };
}

/** `hasAccess` of a mock row: groups, a membership, a role other than `member`, an extra. */
export function mockHasAccess(store: RevokeMockStore, p: AdminPrincipal): boolean {
  const t = ties(store, p);
  return groupsOf(p).length > 0 || tiedGremien(t).size > 0 || heldRoles(store, t).size > 0;
}

/** The list filters of `GET /admin/principals` on the mock rows. */
export function mockMatchesFilters(p: AdminPrincipal, f: PrincipalFilters | undefined): boolean {
  if (!f) return true;
  if (f.hasGroups != null && groupsOf(p).length > 0 !== f.hasGroups) return false;
  const last = p.lastLogin ?? null;
  if (f.lastLoginBefore) {
    const older = last !== null && last < f.lastLoginBefore;
    return older || (!!f.includeNever && last === null);
  }
  return f.includeNever ? last === null : true;
}
