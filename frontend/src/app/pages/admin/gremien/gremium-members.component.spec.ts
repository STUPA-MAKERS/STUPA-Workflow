import { ActivatedRoute } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render } from '@testing-library/angular';
import { provideRouter } from '@angular/router';
import { ToastService } from '@shared/ui';
import { DelegationsApiService } from '@core/api/delegations.service';
import type { AdminPrincipal, GremiumMembership, GremiumRole } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { GremiumMembersComponent } from './gremium-members.component';

const ROLES: GremiumRole[] = [
  { id: 'gr-1', gremiumId: 'g-1', key: 'vorsitz', name: { de: 'Vorsitz', en: 'Chair' } },
  { id: 'gr-2', gremiumId: 'g-1', key: 'beisitz', name: { en: 'Assessor' } },
];
const PRINCIPALS: AdminPrincipal[] = [
  { id: 'p-1', sub: 'kc|alex', email: 'alex@x.de', displayName: 'Alex', lastLogin: null, assignments: [] },
  { id: 'p-2', sub: 'kc|sam', email: 'sam@x.de', displayName: 'Sam', lastLogin: null, assignments: [] },
  { id: 'p-3', sub: 'kc|noname', email: null, displayName: '', lastLogin: null, assignments: [] },
];
const MEMBERSHIPS: GremiumMembership[] = [
  // resolvable principal + role, with both dates
  { id: 'm-1', principalId: 'p-1', gremiumId: 'g-1', gremiumRoleId: 'gr-1', validFrom: '2026-01-01T00:00:00Z', validUntil: '2026-12-31T00:00:00Z' },
  // unknown principal + unknown role → raw-id fallbacks; no dates
  { id: 'm-2', principalId: 'ghost', gremiumId: 'g-1', gremiumRoleId: 'gr-x', validFrom: null, validUntil: null },
  // principal with empty displayName + null email → sub; only validFrom
  { id: 'm-3', principalId: 'p-3', gremiumId: 'g-1', gremiumRoleId: 'gr-2', validFrom: '2026-02-01T00:00:00Z', validUntil: null },
  // duplicate principal (p-1) to exercise memberOptions dedup
  { id: 'm-4', principalId: 'p-1', gremiumId: 'g-1', gremiumRoleId: 'gr-2', validFrom: null, validUntil: '2026-06-30T00:00:00Z' },
];

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listGremien: jest.fn(() =>
      of([{ id: 'g-1', name: 'StuPa', slug: 'stupa', cdVariant: 'stupa', defaultLang: 'de', allowVoteDelegation: false }]),
    ),
    listGremiumRoles: jest.fn(() => of([...ROLES])),
    listPrincipals: jest.fn(() => of([...PRINCIPALS])),
    listGremiumMemberships: jest.fn(() => of([...MEMBERSHIPS])),
    createGremiumMembership: jest.fn(() => of({ id: 'm-new' })),
    deleteGremiumMembership: jest.fn(() => of(void 0)),
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

async function setup(api = makeApi(), delegations = makeDelegationsApi(), toast = makeToast()) {
  const view = await render(GremiumMembersComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: DelegationsApiService, useValue: delegations },
      { provide: ToastService, useValue: toast },
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => 'g-1' } } } },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, delegations, toast, c };
}

describe('GremiumMembersComponent (#18/#62)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads the gremium, roles, principals + memberships on init', async () => {
    const { c } = await setup();
    expect(c.members().some((m: { name: string }) => m.name === 'Alex')).toBe(true);
    expect(c.gremium().name).toBe('StuPa');
    expect(c.roleOptions()).toEqual([
      { value: 'gr-1', label: 'Vorsitz' },
      { value: 'gr-2', label: 'beisitz' }, // gr-2 has no de → key fallback
    ]);
  });

  it('gremium is null when not in the list', async () => {
    const api = makeApi({ listGremien: jest.fn(() => of([])) });
    const { c } = await setup(api);
    expect(c.gremium()).toBeNull();
  });

  it('builds the members table with all fallbacks', async () => {
    const { c } = await setup();
    const members = c.members();
    const m1 = members.find((m: { assignmentId: string }) => m.assignmentId === 'm-1');
    expect(m1).toMatchObject({ name: 'Alex', email: 'alex@x.de', roleLabel: 'Vorsitz', term: '2026-01-01 – 2026-12-31' });

    // unknown principal → principalId, unknown role → roleId, no dates → '—'
    const m2 = members.find((m: { assignmentId: string }) => m.assignmentId === 'm-2');
    expect(m2).toMatchObject({ name: 'ghost', email: null, roleLabel: 'gr-x', term: '—' });

    // empty displayName + null email → sub; only validFrom → "from – …"
    const m3 = members.find((m: { assignmentId: string }) => m.assignmentId === 'm-3');
    expect(m3).toMatchObject({ name: 'kc|noname', email: null, term: '2026-02-01 – …' });

    // only validUntil → "… – until"
    const m4 = members.find((m: { assignmentId: string }) => m.assignmentId === 'm-4');
    expect(m4.term).toBe('… – 2026-06-30');
  });

  it('rowId + subRowId expose the ids', async () => {
    const { c } = await setup();
    expect(c.rowId({ assignmentId: 'm-1' })).toBe('m-1');
    expect(c.subRowId({ id: 'sub-1' })).toBe('sub-1');
  });

  it('memberOptions dedups principals and starts with the all-members option', async () => {
    const { c } = await setup();
    const opts = c.memberOptions();
    expect(opts[0]).toEqual({ value: '', label: 'Alle Mitglieder' });
    const values = opts.map((o: { value: string }) => o.value);
    // p-1 appears once despite two memberships; ghost id falls back to itself
    expect(values).toEqual(['', 'p-1', 'ghost', 'p-3']);
    // ghost (unknown principal) → label is the raw id
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
    expect(c.roleOptions()).toEqual([]);
    // principals empty → members resolve names to principalId
    const m1 = c.members().find((m: { assignmentId: string }) => m.assignmentId === 'm-1');
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

  // --- Add member dialog ----------------------------------------------------
  it('openAdd resets dialog state', async () => {
    const { c } = await setup();
    c.query.set('x');
    c.selected.set(PRINCIPALS[0]);
    c.addRoleId.set('gr-1');
    c.openAdd();
    expect(c.query()).toBe('');
    expect(c.selected()).toBeNull();
    expect(c.addRoleId()).toBe('');
    expect(c.addFrom()).toBe('');
    expect(c.addUntil()).toBe('');
    expect(c.candidates()).toEqual([]);
    expect(c.addOpen()).toBe(true);
  });

  it('closeAdd closes the dialog', async () => {
    const { c } = await setup();
    c.openAdd();
    c.closeAdd();
    expect(c.addOpen()).toBe(false);
  });

  it('onSearch fills candidates capped at 8', async () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ ...PRINCIPALS[0], id: `p${i}` }));
    const api = makeApi({ listPrincipals: jest.fn(() => of(many)) });
    const { c } = await setup(api);
    c.onSearch('a');
    expect(c.query()).toBe('a');
    expect(c.candidates()).toHaveLength(8);
  });

  it('onSearch empties candidates on error', async () => {
    const apiErr = makeApi();
    const { c } = await setup(apiErr);
    apiErr.listPrincipals.mockReturnValueOnce(throwError(() => new Error('x')));
    c.onSearch('z');
    expect(c.candidates()).toEqual([]);
  });

  it('pick selects a candidate, fills the query and clears the list', async () => {
    const { c } = await setup();
    c.pick(PRINCIPALS[1]);
    expect(c.selected()).toEqual(PRINCIPALS[1]);
    expect(c.query()).toBe('Sam');
    expect(c.candidates()).toEqual([]);
    // empty displayName + null email → sub
    c.pick(PRINCIPALS[2]);
    expect(c.query()).toBe('kc|noname');
    // email fallback (displayName empty, email present)
    c.pick({ ...PRINCIPALS[1], displayName: '' });
    expect(c.query()).toBe('sam@x.de');
  });

  it('addMember is a no-op without a selection or role', async () => {
    const { c, api } = await setup();
    c.addMember(); // nothing selected
    expect(api.createGremiumMembership).not.toHaveBeenCalled();
    c.selected.set(PRINCIPALS[1]);
    c.addMember(); // no role
    expect(api.createGremiumMembership).not.toHaveBeenCalled();
  });

  it('adds a membership via typeahead pick + role + term', async () => {
    const { api, c, toast } = await setup();
    c.openAdd();
    c.pick(PRINCIPALS[1]);
    c.addRoleId.set('gr-1');
    c.addFrom.set('2026-01-01');
    c.addMember();
    expect(api.createGremiumMembership).toHaveBeenCalledWith('g-1', {
      principalId: 'p-2',
      gremiumRoleId: 'gr-1',
      validFrom: '2026-01-01',
      validUntil: null,
    });
    expect(c.addOpen()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
  });

  it('addMember sends null dates when term is left empty', async () => {
    const { api, c } = await setup();
    c.selected.set(PRINCIPALS[1]);
    c.addRoleId.set('gr-1');
    c.addMember();
    expect(api.createGremiumMembership).toHaveBeenCalledWith('g-1', {
      principalId: 'p-2',
      gremiumRoleId: 'gr-1',
      validFrom: null,
      validUntil: null,
    });
  });

  it('addMember 409 shows the overlap error', async () => {
    const api409 = makeApi({ createGremiumMembership: jest.fn(() => throwError(() => ({ status: 409 }))) });
    const { c, toast } = await setup(api409);
    c.selected.set(PRINCIPALS[1]);
    c.addRoleId.set('gr-1');
    c.addMember();
    expect(toast.error).toHaveBeenCalledWith('Überlappende Amtszeit: pro Zeitpunkt nur eine Rolle möglich.');
  });

  it('addMember non-409 shows the generic error', async () => {
    const apiErr = makeApi({ createGremiumMembership: jest.fn(() => throwError(() => ({ status: 500 }))) });
    const { c, toast } = await setup(apiErr);
    c.selected.set(PRINCIPALS[1]);
    c.addRoleId.set('gr-1');
    c.addMember();
    expect(toast.error).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
  });

  it('removeMember deletes and reloads', async () => {
    const { c, api, toast } = await setup();
    c.removeMember('m-1');
    expect(api.deleteGremiumMembership).toHaveBeenCalledWith('m-1');
    expect(toast.success).toHaveBeenCalled();
  });

  it('removeMember error shows a toast', async () => {
    const apiErr = makeApi({ deleteGremiumMembership: jest.fn(() => throwError(() => new Error('x'))) });
    const { c, toast } = await setup(apiErr);
    c.removeMember('m-1');
    expect(toast.error).toHaveBeenCalled();
  });

  // --- Substitute pool ------------------------------------------------------
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
    const view = await render(GremiumMembersComponent, {
      providers: [
        provideRouter([]),
        { provide: AdminApiService, useValue: api },
        { provide: DelegationsApiService, useValue: makeDelegationsApi() },
        { provide: ToastService, useValue: makeToast() },
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => null } } } },
      ],
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    expect(c.gremiumIdRef).toBe('');
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
