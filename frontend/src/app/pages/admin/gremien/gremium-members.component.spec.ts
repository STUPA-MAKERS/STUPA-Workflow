import { ActivatedRoute } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { provideRouter } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { DelegationsApiService } from '@core/api/delegations.service';
import type { AdminPrincipal, GremiumMembership, GremiumRole } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { GremiumMembersComponent } from './gremium-members.component';

const ROLES: GremiumRole[] = [
  { id: 'gr-1', gremiumId: 'g-1', key: 'vorsitz', name: { de: 'Vorsitz', en: 'Chair' } },
  { id: 'gr-2', gremiumId: 'g-1', key: 'beisitz', name: { en: 'Assessor' } },
];
const PRINCIPALS: AdminPrincipal[] = [
  { id: 'p-1', sub: 'kc|alex', email: 'alex@x.de', displayName: 'Alex', lastLogin: null, assignments: [], oidcGroups: [] },
  { id: 'p-2', sub: 'kc|sam', email: 'sam@x.de', displayName: 'Sam', lastLogin: null, assignments: [], oidcGroups: [] },
  { id: 'p-3', sub: 'kc|noname', email: null, displayName: '', lastLogin: null, assignments: [], oidcGroups: [] },
];
const MEMBERSHIPS: GremiumMembership[] = [
  { id: 'm-1', principalId: 'p-1', gremiumId: 'g-1', gremiumRoleId: 'gr-1' },
  // unknown principal and unknown role force the raw-id fallbacks
  { id: 'm-2', principalId: 'ghost', gremiumId: 'g-1', gremiumRoleId: 'gr-x' },
  // empty displayName and null email fall back to sub
  { id: 'm-3', principalId: 'p-3', gremiumId: 'g-1', gremiumRoleId: 'gr-2' },
  // duplicate principal (p-1) to exercise memberOptions dedup
  { id: 'm-4', principalId: 'p-1', gremiumId: 'g-1', gremiumRoleId: 'gr-2' },
];
function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listGremien: jest.fn(() =>
      of([{ id: 'g-1', name: 'StuPa', slug: 'stupa', cdVariantId: 'cd-stupa', defaultLang: 'de', allowVoteDelegation: false }]),
    ),
    listGremiumRoles: jest.fn(() => of([...ROLES])),
    listPrincipals: jest.fn(() => of([...PRINCIPALS])),
    listGremiumMemberships: jest.fn(() => of([...MEMBERSHIPS])),
    ...over,
  };
}

function makeDelegationsApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    substitutes: jest.fn(() => of([])),
    addSubstitute: jest.fn(() => of({ id: 'sub-new' })),
    removeSubstitute: jest.fn(() => of(void 0)),
    ...over,
  };
}

function makeToast() {
  return { success: jest.fn(), error: jest.fn() };
}

async function setup(
  api = makeApi(),
  delegations = makeDelegationsApi(),
  toast = makeToast(),
  can = true,
) {
  const view = await render(GremiumMembersComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: DelegationsApiService, useValue: delegations },
      { provide: ToastService, useValue: toast },
      { provide: AuthService, useValue: { can: () => can } },
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => 'g-1' } } } },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, delegations, toast, c };
}

describe('GremiumMembersComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads the gremium, roles, principals + memberships on init', async () => {
    const { c } = await setup();
    expect(c.members().some((m: { name: string }) => m.name === 'Alex')).toBe(true);
    expect(c.gremium().name).toBe('StuPa');
  });

  it('gremium is null when not in the list', async () => {
    const api = makeApi({ listGremien: jest.fn(() => of([])) });
    const { c } = await setup(api);
    expect(c.gremium()).toBeNull();
  });

  it('builds the read-only members table with all fallbacks', async () => {
    const { c } = await setup();
    const members = c.members();
    const byId = (id: string) => members.find((m: { id: string }) => m.id === id);
    expect(byId('m-1')).toEqual({ id: 'm-1', name: 'Alex', email: 'alex@x.de', roleLabel: 'Vorsitz' });
    // unknown principal → principalId, unknown role → roleId
    expect(byId('m-2')).toEqual({ id: 'm-2', name: 'ghost', email: null, roleLabel: 'gr-x' });
    // empty displayName and null email fall back to sub
    expect(byId('m-3')).toMatchObject({ name: 'kc|noname', email: null, roleLabel: 'beisitz' });
    // no term column and no action column on the member table
    expect(c.columns().map((col: { key: string }) => col.key)).toEqual(['name', 'email', 'roleLabel']);
  });

  it('rowId + subRowId expose the ids', async () => {
    const { c } = await setup();
    expect(c.rowId({ id: 'm-1' })).toBe('m-1');
    expect(c.subRowId({ id: 'sub-1' })).toBe('sub-1');
  });

  it('memberOptions dedups principals and starts with the all-members option', async () => {
    const { c } = await setup();
    const opts = c.memberOptions();
    expect(opts[0]).toEqual({ value: '', label: 'Alle Mitglieder' });
    const values = opts.map((o: { value: string }) => o.value);
    // p-1 appears once despite two memberships. The unknown id falls back to itself.
    expect(values).toEqual(['', 'p-1', 'ghost', 'p-3']);
    expect(opts.find((o: { value: string }) => o.value === 'ghost').label).toBe('ghost');
    // p-3 empty displayName + null email → sub label
    expect(opts.find((o: { value: string }) => o.value === 'p-3').label).toBe('kc|noname');
  });

  it('falls back to empty roles/principals when those loads error', async () => {
    const api = makeApi({
      listGremiumRoles: jest.fn(() => throwError(() => new Error('x'))),
      listPrincipals: jest.fn(() => throwError(() => new Error('y'))),
    });
    const { c } = await setup(api);
    // roles empty → the member role resolves to the raw role id
    expect(c.members().find((m: { id: string }) => m.id === 'm-1').roleLabel).toBe('gr-1');
    // principals empty → members resolve names to principalId
    const m1 = c.members().find((m: { id: string }) => m.id === 'm-1');
    expect(m1.name).toBe('p-1');
  });

  it('shows an error toast and empties memberships when the list errors (#5-3)', async () => {
    const api = makeApi({ listGremiumMemberships: jest.fn(() => throwError(() => new Error('x'))) });
    const { c, toast } = await setup(api);
    expect(c.members()).toEqual([]);
    expect(toast.error).toHaveBeenCalled();
  });

  it('empties substitutes when the substitutes list errors', async () => {
    const delegations = makeDelegationsApi({ substitutes: jest.fn(() => throwError(() => new Error('x'))) });
    const { c } = await setup(makeApi(), delegations);
    expect(c.substitutes()).toEqual([]);
  });

  it('openAddSub resets the substitute dialog state', async () => {
    const { c } = await setup();
    c.subQuery.set('x');
    c.subSelected.set(PRINCIPALS[0]);
    c.subMemberId.set('p-1');
    c.openAddSub();
    expect(c.subQuery()).toBe('');
    expect(c.subSelected()).toBeNull();
    expect(c.subCandidates()).toEqual([]);
    expect(c.subMemberId()).toBe('');
    expect(c.addSubOpen()).toBe(true);
  });

  it('onSubSearch fills candidates capped at 8', async () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ ...PRINCIPALS[0], id: `p${i}` }));
    const api = makeApi({ listPrincipals: jest.fn(() => of(many)) });
    const { c } = await setup(api);
    c.onSubSearch('a');
    expect(c.subQuery()).toBe('a');
    expect(c.subCandidates()).toHaveLength(8);
  });

  it('onSubSearch empties candidates on error', async () => {
    const apiErr = makeApi();
    const { c } = await setup(apiErr);
    apiErr.listPrincipals.mockReturnValueOnce(throwError(() => new Error('x')));
    c.onSubSearch('z');
    expect(c.subCandidates()).toEqual([]);
  });

  it('pickSub selects a candidate, fills query, clears list (incl. sub fallback)', async () => {
    const { c } = await setup();
    c.pickSub(PRINCIPALS[1]);
    expect(c.subSelected()).toEqual(PRINCIPALS[1]);
    expect(c.subQuery()).toBe('Sam');
    expect(c.subCandidates()).toEqual([]);
    // empty displayName + null email → sub fallback
    c.pickSub(PRINCIPALS[2]);
    expect(c.subQuery()).toBe('kc|noname');
    // email fallback (displayName empty, email present)
    c.pickSub({ ...PRINCIPALS[1], displayName: '' });
    expect(c.subQuery()).toBe('sam@x.de');
  });

  it('falls back to an empty gremium id when the route lacks one', async () => {
    const api = makeApi();
    await render(GremiumMembersComponent, {
      providers: [
        provideRouter([]),
        { provide: AdminApiService, useValue: api },
        { provide: DelegationsApiService, useValue: makeDelegationsApi() },
        { provide: ToastService, useValue: makeToast() },
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => null } } } },
      ],
    });
    expect(api.listGremiumRoles).toHaveBeenCalledWith('');
  });

  it('addSub is a no-op without a selection', async () => {
    const { c, delegations } = await setup();
    c.addSub();
    expect(delegations.addSubstitute).not.toHaveBeenCalled();
  });

  it('adds a gremium-wide substitute (empty memberId → null)', async () => {
    const { delegations, c, toast } = await setup();
    c.openAddSub();
    c.pickSub(PRINCIPALS[1]);
    c.addSub();
    expect(delegations.addSubstitute).toHaveBeenCalledWith({
      gremiumId: 'g-1',
      memberId: null,
      substituteId: 'p-2',
    });
    expect(c.addSubOpen()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
  });

  it('adds a member-specific substitute (concrete memberId)', async () => {
    const { delegations, c } = await setup();
    c.subSelected.set(PRINCIPALS[1]);
    c.subMemberId.set('p-1');
    c.addSub();
    expect(delegations.addSubstitute).toHaveBeenCalledWith({
      gremiumId: 'g-1',
      memberId: 'p-1',
      substituteId: 'p-2',
    });
  });

  it('addSub 409 shows the duplicate error', async () => {
    const dup = makeDelegationsApi({ addSubstitute: jest.fn(() => throwError(() => ({ status: 409 }))) });
    const { c, toast } = await setup(makeApi(), dup);
    c.subSelected.set(PRINCIPALS[1]);
    c.addSub();
    expect(toast.error).toHaveBeenCalledWith('Dieser Eintrag existiert bereits.');
  });

  it('addSub non-409 shows the generic error', async () => {
    const other = makeDelegationsApi({ addSubstitute: jest.fn(() => throwError(() => ({ status: 500 }))) });
    const { c, toast } = await setup(makeApi(), other);
    c.subSelected.set(PRINCIPALS[1]);
    c.addSub();
    expect(toast.error).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
  });

  it('removeSub deletes and reloads', async () => {
    const { delegations, c, toast } = await setup();
    c.removeSub('sub-1');
    expect(delegations.removeSubstitute).toHaveBeenCalledWith('sub-1');
    expect(toast.success).toHaveBeenCalled();
  });

  it('removeSub error shows a toast', async () => {
    const dErr = makeDelegationsApi({ removeSubstitute: jest.fn(() => throwError(() => new Error('x'))) });
    const { c, toast } = await setup(makeApi(), dErr);
    c.removeSub('sub-1');
    expect(toast.error).toHaveBeenCalled();
  });

  // --- mapping hint ---------------------------------------------------------

  it('has no mapping controls, only the hint with a link to the mappings page', async () => {
    await setup();
    expect(screen.getByRole('note')).toHaveTextContent('Die Mitgliedschaft kommt aus den OIDC-Gruppen der Person');
    expect(screen.getByRole('link', { name: 'Gruppen-Mappings verwalten' })).toHaveAttribute(
      'href',
      '/admin/group-mappings',
    );
    expect(screen.queryByRole('button', { name: 'Gruppe zuordnen' })).toBeNull();
    expect(screen.queryByText('OIDC-Gruppe')).toBeNull();
  });

  it('hides the link without admin.group_mappings', async () => {
    const { c } = await setup(makeApi(), makeDelegationsApi(), makeToast(), false);
    expect(c.canManageMappings()).toBe(false);
    expect(screen.getByRole('note')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Gruppen-Mappings verwalten' })).toBeNull();
  });

  it('lists substitutes when present', async () => {
    const dele = makeDelegationsApi({
      substitutes: jest.fn(() =>
        of([{ id: 's-1', gremiumId: 'g-1', memberId: null, memberName: null, substituteId: 'p-2', substituteName: 'Sam' }]),
      ),
    });
    const { c } = await setup(makeApi(), dele);
    expect(c.substitutes()).toHaveLength(1);
  });
});
