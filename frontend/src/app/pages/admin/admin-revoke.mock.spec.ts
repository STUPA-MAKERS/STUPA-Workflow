import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import { AdminApiService } from './admin-api.service';
import { MOCK_GREMIUM_STUPA_ID } from './admin.mock';
import type { AdminPrincipal } from './admin.models';
import {
  mockApplyRevoke,
  mockHasAccess,
  mockMatchesFilters,
  mockRevokePreview,
  type RevokeMockStore,
} from './admin-revoke.mock';

function svc(mock: boolean): AdminApiService {
  TestBed.configureTestingModule({
    providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: mock }],
  });
  return TestBed.inject(AdminApiService);
}

describe('Rechte entziehen (F3) — real mode (contract)', () => {
  it('wires the list filters, the preview and the revoke', () => {
    const s = svc(false);
    const http = TestBed.inject(HttpTestingController);
    s.listPrincipals('', { lastLoginBefore: '2026-07-11', includeNever: true, hasGroups: false }).subscribe();
    http
      .expectOne('/api/admin/principals?lastLoginBefore=2026-07-11&includeNever=true&hasGroups=false')
      .flush([]);
    s.listPrincipals(undefined, { hasGroups: true }).subscribe();
    http.expectOne('/api/admin/principals?hasGroups=true').flush([]);

    s.previewPrincipalRevoke('p-12').subscribe();
    const pv = http.expectOne('/api/admin/principals/p-12/revoke-preview');
    expect(pv.request.method).toBe('GET');
    pv.flush({});

    const body = { gremiumIds: ['g-1'], globalRoleIds: [], deactivate: true };
    s.revokePrincipal('p-12', body).subscribe();
    const rv = http.expectOne('/api/admin/principals/p-12/revoke');
    expect(rv.request.method).toBe('POST');
    expect(rv.request.body).toEqual(body);
    rv.flush({});
    http.verify();
  });
});

describe('Rechte entziehen (F3) — mock mode', () => {
  it('lists the demo person with access and filters by last login and groups', async () => {
    const s = svc(true);
    const all = await firstValueFrom(s.listPrincipals());
    const tobias = all.find((p) => p.id === 'p-12')!;
    expect(tobias.hasAccess).toBe(true);
    const stale = await firstValueFrom(
      s.listPrincipals('', { lastLoginBefore: '2026-07-11', includeNever: true }),
    );
    expect(stale.map((p) => p.id)).toContain('p-12');
    const never = await firstValueFrom(s.listPrincipals('', { includeNever: true }));
    expect(never.every((p) => !p.lastLogin)).toBe(true);
    const noGroups = await firstValueFrom(s.listPrincipals('', { hasGroups: false }));
    expect(noGroups.map((p) => p.id)).not.toContain('p-12');
  });

  it('previews the Gremien, the shared group and the global roles', async () => {
    const s = svc(true);
    const p = await firstValueFrom(s.previewPrincipalRevoke('p-12'));
    expect(p.isSelf).toBe(false);
    expect(p.principal.displayName).toBe('Tobias Kern');
    const ids = p.gremien.map((g) => g.gremiumId);
    expect(ids).toEqual(expect.arrayContaining([MOCK_GREMIUM_STUPA_ID, 'g-asta']));
    const shared = p.groups.find((g) => g.group === 'gremien-alle')!;
    expect(shared.gremiumIds).toEqual([MOCK_GREMIUM_STUPA_ID, 'g-asta']);
    const asta = p.gremien.find((g) => g.gremiumId === 'g-asta')!;
    expect(asta.assignments.map((a) => a.id)).toEqual(['a-12']);
    expect(asta.liveDelegations).toHaveLength(1);
    expect(asta.poolEntries[0]).toMatchObject({ asSubstitute: true, gremiumWide: true });
    const err = await firstValueFrom(s.previewPrincipalRevoke('nope')).catch((e: unknown) => e);
    expect(err).toEqual({ status: 404 });
  });

  it('refuses a half selection, an empty one and an unknown person', async () => {
    const s = svc(true);
    const half = await firstValueFrom(
      s.revokePrincipal('p-12', { gremiumIds: ['g-asta'], globalRoleIds: [], deactivate: false }),
    ).catch((e: unknown) => e);
    expect(half).toMatchObject({ status: 422, error: { code: 'revoke_incomplete' } });
    const empty = await firstValueFrom(
      s.revokePrincipal('p-12', { gremiumIds: [], globalRoleIds: [], deactivate: false }),
    ).catch((e: unknown) => e);
    expect(empty).toMatchObject({ status: 422, error: { code: 'revoke_empty' } });
    const missing = await firstValueFrom(
      s.revokePrincipal('nope', { gremiumIds: [], globalRoleIds: [], deactivate: true }),
    ).catch((e: unknown) => e);
    expect(missing).toMatchObject({ status: 404 });
  });

  it('revokes everything: the person keeps the account, but no ties', async () => {
    const s = svc(true);
    const p = await firstValueFrom(s.previewPrincipalRevoke('p-12'));
    const res = await firstValueFrom(
      s.revokePrincipal('p-12', {
        gremiumIds: p.gremien.map((g) => g.gremiumId),
        globalRoleIds: p.globalRoles.map((r) => r.roleId),
        deactivate: true,
      }),
    );
    expect(res.removedGroups).toContain('gremien-alle');
    expect(res.deletedAssignments).toBe(1);
    expect(res.deletedPoolEntries).toBe(2);
    expect(res.revokedDelegations).toBe(1);
    expect(res.keptLiveDelegations).toBe(1);
    expect(res.deactivated).toBe(true);
    const after = await firstValueFrom(s.previewPrincipalRevoke('p-12'));
    // The live delegation stays until the meeting ends.
    expect(after.gremien.map((g) => g.gremiumId)).toEqual(['g-asta']);
    expect(after.gremien[0].liveDelegations).toHaveLength(1);
    expect(after.globalRoles).toEqual([]);
    expect(after.principal.active).toBe(false);
  });

  it('mockMatchesFilters reads the filters like the server', () => {
    const p = { lastLogin: null, oidcGroups: [] } as unknown as AdminPrincipal;
    const old = { lastLogin: '2026-01-01T00:00:00Z', oidcGroups: ['x'] } as unknown as AdminPrincipal;
    expect(mockMatchesFilters(p, undefined)).toBe(true);
    expect(mockMatchesFilters(p, {})).toBe(true);
    expect(mockMatchesFilters(p, { lastLoginBefore: '2026-07-01' })).toBe(false);
    expect(mockMatchesFilters(p, { lastLoginBefore: '2026-07-01', includeNever: true })).toBe(true);
    expect(mockMatchesFilters(old, { lastLoginBefore: '2026-07-01' })).toBe(true);
    expect(mockMatchesFilters(old, { includeNever: true })).toBe(false);
    expect(mockMatchesFilters(old, { hasGroups: false })).toBe(false);
    expect(mockMatchesFilters(old, { hasGroups: true })).toBe(true);
  });
});

describe('Rechte entziehen (F3) — mock store edge cases', () => {
  /** A store full of loose ends: unnamed people, unknown roles and Gremien, no role mapping. */
  function store(): RevokeMockStore {
    return {
      principals: [
        {
          id: 'x-1',
          sub: 'kc|x',
          oidcGroups: ['grp-a', 'grp-role', 'grp-ghost'],
          assignments: [
            { id: 'as-1', principalId: 'x-1', roleId: 'r-unknown', delegateVoting: false },
            { id: 'as-2', principalId: 'x-1', roleId: 'r-known', gremiumId: 'g-ghost', delegateVoting: false },
          ],
        },
        { id: 'x-2', sub: 'kc|two', displayName: null, email: 'two@x', oidcGroups: [], assignments: [] },
        { id: 'x-3', sub: 'kc|three', displayName: null, email: null, oidcGroups: [], assignments: [] },
        // A dev row without a group list at all.
        { id: 'x-4', sub: 'kc|four', assignments: [] } as unknown as AdminPrincipal,
      ],
      gremien: [{ id: 'g-a', name: 'A', slug: 'a', cdVariantId: null, defaultLang: 'de', allowVoteDelegation: true }],
      gremiumRoles: [],
      roles: [
        { id: 'r-known', key: 'known', label: { de: 'Bekannt' }, permissions: [] },
        { id: 'r-member', key: 'member', label: { de: 'Mitglied' }, permissions: [] },
      ],
      groupMappings: [
        { id: 'gm-1', oidcGroup: 'grp-role', roleId: 'r-missing' },
        { id: 'gm-2', oidcGroup: 'grp-role', roleId: 'r-member' },
      ],
      membershipMappings: [{ id: 'mm-1', gremiumId: 'g-a', oidcGroup: 'grp-a' }],
      roleMappings: [],
      memberships: [{ id: 'm-1', principalId: 'x-1', gremiumId: 'g-b', gremiumRoleId: 'gr-b' }],
      revoked: {},
      extras: {
        pool: [
          { id: 'ds-1', gremiumId: 'g-a', memberId: 'x-2', substituteId: 'x-1' },
          { id: 'ds-2', gremiumId: 'g-a', memberId: 'x-1', substituteId: 'x-3' },
          { id: 'ds-3', gremiumId: 'g-a', memberId: 'nobody', substituteId: 'x-1' },
        ],
        delegations: [],
      },
    };
  }

  it('falls back to keys, empty labels and null names where the store knows nothing', () => {
    const p = mockRevokePreview(store(), 'x-1', 'kc|someone-else')!;
    expect(p.isSelf).toBe(false);
    expect(p.principal).toEqual({ id: 'x-1', displayName: null, email: null, lastLogin: null, active: true });
    // Unknown Gremien have no name and sort first.
    expect(p.gremien.map((g) => [g.gremiumId, g.name])).toEqual([
      ['g-b', ''],
      ['g-ghost', ''],
      ['g-a', 'A'],
    ]);
    const a = p.gremien[2];
    // No role mapping and no implicit gremium role: the membership is a plain `member`.
    expect(a.membership).toEqual({ roleKey: 'member', roleLabel: {}, groups: ['grp-a'] });
    expect(a.groups).toEqual(['grp-a']);
    expect(a.poolEntries).toEqual([
      { id: 'ds-1', asSubstitute: true, gremiumWide: false, memberName: 'two@x', substituteName: null },
      { id: 'ds-2', asSubstitute: false, gremiumWide: false, memberName: null, substituteName: null },
      { id: 'ds-3', asSubstitute: true, gremiumWide: false, memberName: null, substituteName: null },
    ]);
    expect(p.gremien[0].membership?.roleKey).toBe('member');
    expect(p.gremien[1].membership).toBeNull();
    expect(p.gremien[1].assignments).toEqual([
      {
        id: 'as-2',
        roleId: 'r-known',
        roleKey: 'known',
        roleLabel: { de: 'Bekannt' },
        grantedBy: null,
        validFrom: null,
        validUntil: null,
      },
    ]);
    // `member` is never a right to take away; unknown roles keep their id as key.
    expect(p.globalRoles).toEqual([
      { roleId: 'r-missing', roleKey: 'r-missing', roleLabel: {}, groups: ['grp-role'], assignments: [] },
      {
        roleId: 'r-unknown',
        roleKey: 'r-unknown',
        roleLabel: {},
        groups: [],
        assignments: [
          {
            id: 'as-1',
            roleId: 'r-unknown',
            roleKey: 'r-unknown',
            roleLabel: {},
            grantedBy: null,
            validFrom: null,
            validUntil: null,
          },
        ],
      },
    ]);
    expect(p.groups).toEqual([
      { group: 'grp-a', gremiumIds: ['g-a'], globalRoleIds: [] },
      { group: 'grp-role', gremiumIds: [], globalRoleIds: ['r-missing'] },
    ]);
    expect(mockRevokePreview(store(), 'x-1', 'kc|x')!.isSelf).toBe(true);
  });

  it('refuses the own account and revokes twice in a row', () => {
    const st = store();
    expect(
      mockApplyRevoke(st, 'x-1', { gremiumIds: ['g-a'], globalRoleIds: [], deactivate: false }, 'kc|x'),
    ).toEqual({ status: 409, error: { code: 'revoke_own_account' } });
    const res = mockApplyRevoke(
      st,
      'x-1',
      { gremiumIds: ['g-a', 'g-b', 'g-ghost'], globalRoleIds: ['r-missing', 'r-unknown'], deactivate: false },
      null,
    );
    expect(res).toEqual({
      gremiumIds: ['g-a', 'g-b', 'g-ghost'],
      globalRoleIds: ['r-missing', 'r-unknown'],
      removedGroups: ['grp-a', 'grp-role'],
      deletedAssignments: 2,
      deletedPoolEntries: 3,
      revokedDelegations: 0,
      keptLiveDelegations: 0,
      deactivated: false,
    });
    const after = mockRevokePreview(st, 'x-1', null)!;
    expect(after.gremien).toEqual([]);
    expect(after.globalRoles).toEqual([]);
    expect(mockHasAccess(st, st.principals[0])).toBe(true); // the unmapped group stays
    const again = mockApplyRevoke(st, 'x-1', { gremiumIds: ['g-c'], globalRoleIds: [], deactivate: true }, null);
    expect(again).toMatchObject({ deactivated: true, removedGroups: [] });
    expect(st.revoked['x-1']).toEqual(['g-a', 'g-b', 'g-ghost', 'g-c']);
    expect(st.principals[0].active).toBe(false);
  });

  it('a row without a group list has no access', () => {
    const st = store();
    expect(mockHasAccess(st, st.principals[3])).toBe(false);
    expect(mockMatchesFilters(st.principals[3], { hasGroups: false })).toBe(true);
  });
});
