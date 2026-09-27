import { ActivatedRoute } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { provideRouter } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { DelegationsApiService } from '@core/api/delegations.service';
import type {
  AdminPrincipal,
  GremiumGroupMapping,
  GremiumMembership,
  GremiumRole,
} from '../admin.models';
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
const MAPPINGS: GremiumGroupMapping[] = [
  { id: 'gm-1', gremiumId: 'g-1', gremiumRoleId: 'gr-1', oidcGroup: 'stupa-vorsitz' },
  // unknown role → raw id fallback
  { id: 'gm-2', gremiumId: 'g-1', gremiumRoleId: 'gr-x', oidcGroup: 'stupa-alt' },
];

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listGremien: jest.fn(() =>
      of([{ id: 'g-1', name: 'StuPa', slug: 'stupa', cdVariantId: 'cd-stupa', defaultLang: 'de', allowVoteDelegation: false }]),
    ),
    listGremiumRoles: jest.fn(() => of([...ROLES])),
    listPrincipals: jest.fn(() => of([...PRINCIPALS])),
    listGremiumMemberships: jest.fn(() => of([...MEMBERSHIPS])),
    listGremiumGroupMappings: jest.fn(() => of([...MAPPINGS])),
    createGremiumGroupMapping: jest.fn(() => of({ id: 'gm-new' })),
    updateGremiumGroupMapping: jest.fn(() => of({ id: 'gm-1' })),
    deleteGremiumGroupMapping: jest.fn(() => of(void 0)),
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
    expect(c.mappingRowId({ id: 'gm-1' })).toBe('gm-1');
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
    expect(c.roleOptions()).toEqual([]);
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

  // --- OIDC group mappings --------------------------------------------------

  it('lists the mappings with resolved role labels', async () => {
    const { c } = await setup();
    expect(c.mappingRows()).toEqual([
      { id: 'gm-1', oidcGroup: 'stupa-vorsitz', roleLabel: 'Vorsitz' },
      { id: 'gm-2', oidcGroup: 'stupa-alt', roleLabel: 'gr-x' },
    ]);
    expect(screen.getByText('stupa-vorsitz')).toBeInTheDocument();
    expect(c.mappingsLoading()).toBe(false);
  });

  it('shows an error toast and empties the mappings when their list errors', async () => {
    const api = makeApi({
      listGremiumGroupMappings: jest.fn(() => throwError(() => new Error('x'))),
    });
    const { c, toast } = await setup(api);
    expect(c.mappingRows()).toEqual([]);
    expect(c.mappingsLoading()).toBe(false);
    expect(toast.error).toHaveBeenCalledWith('Gruppen-Mappings konnten nicht geladen werden.');
  });

  it('openAddMapping resets the dialog, openEditMapping seeds it', async () => {
    const { c } = await setup();
    c.mappingGroup.set('x');
    c.mappingRoleId.set('gr-2');
    c.openAddMapping();
    expect(c.mappingOpen()).toBe(true);
    expect(c.mappingEditId()).toBeNull();
    expect(c.mappingGroup()).toBe('');
    expect(c.mappingRoleId()).toBe('');
    c.openEditMapping('gm-1');
    expect(c.mappingEditId()).toBe('gm-1');
    expect(c.mappingGroup()).toBe('stupa-vorsitz');
    expect(c.mappingRoleId()).toBe('gr-1');
    c.closeMapping();
    expect(c.mappingOpen()).toBe(false);
  });

  it('openEditMapping ignores an unknown id', async () => {
    const { c } = await setup();
    c.openEditMapping('nope');
    expect(c.mappingOpen()).toBe(false);
  });

  it('validates the group name and the role before a save', async () => {
    const { c, api } = await setup();
    c.openAddMapping();
    expect(c.mappingValid()).toBe(false);
    c.mappingGroup.set('   ');
    c.mappingRoleId.set('gr-1');
    expect(c.mappingValid()).toBe(false);
    c.mappingGroup.set(' vote:abc ');
    expect(c.mappingGroupReserved()).toBe(true);
    expect(c.mappingValid()).toBe(false);
    c.saveMapping();
    expect(api.createGremiumGroupMapping).not.toHaveBeenCalled();
    c.mappingGroup.set('stupa');
    expect(c.mappingValid()).toBe(true);
  });

  it('shows the reserved-prefix hint in the dialog', async () => {
    const { c, fixture } = await setup();
    c.openAddMapping();
    c.mappingGroup.set('vote:x');
    fixture.detectChanges();
    expect(screen.getByText('Das Präfix „vote:“ ist reserviert.')).toBeInTheDocument();
  });

  it('creates a mapping with a trimmed group, then reloads mappings and members', async () => {
    const { c, api, toast } = await setup();
    c.openAddMapping();
    c.mappingGroup.set('  stupa-mitglieder ');
    c.mappingRoleId.set('gr-2');
    c.saveMapping();
    expect(api.createGremiumGroupMapping).toHaveBeenCalledWith('g-1', {
      oidcGroup: 'stupa-mitglieder',
      gremiumRoleId: 'gr-2',
    });
    expect(c.mappingOpen()).toBe(false);
    expect(c.mappingSaving()).toBe(false);
    expect(toast.success).toHaveBeenCalledWith('Mapping gespeichert. Die Mitglieder sind aktualisiert.');
    // The backend re-syncs the memberships, so both lists load again.
    expect(api.listGremiumGroupMappings).toHaveBeenCalledTimes(2);
    expect(api.listGremiumMemberships).toHaveBeenCalledTimes(2);
  });

  it('updates an existing mapping', async () => {
    const { c, api } = await setup();
    c.openEditMapping('gm-1');
    c.mappingRoleId.set('gr-2');
    c.saveMapping();
    expect(api.updateGremiumGroupMapping).toHaveBeenCalledWith('gm-1', {
      oidcGroup: 'stupa-vorsitz',
      gremiumRoleId: 'gr-2',
    });
    expect(api.createGremiumGroupMapping).not.toHaveBeenCalled();
  });

  it('does not send a second save while one runs', async () => {
    const { c, api } = await setup();
    c.openEditMapping('gm-1');
    c.mappingSaving.set(true);
    c.saveMapping();
    expect(api.updateGremiumGroupMapping).not.toHaveBeenCalled();
  });

  it.each([
    [409, 'Diese Gruppe ist schon zugeordnet, oder die Rolle gehört zu einem anderen Gremium.'],
    [422, 'Ungültiger Gruppenname: leer oder mit dem reservierten Präfix „vote:“.'],
    [500, 'Aktion fehlgeschlagen.'],
  ])('a save that answers %s names the reason and keeps the dialog open', async (status, text) => {
    const api = makeApi({
      createGremiumGroupMapping: jest.fn(() => throwError(() => ({ status }))),
    });
    const { c, toast } = await setup(api);
    c.openAddMapping();
    c.mappingGroup.set('stupa');
    c.mappingRoleId.set('gr-1');
    c.saveMapping();
    expect(toast.error).toHaveBeenCalledWith(text);
    expect(c.mappingOpen()).toBe(true);
    expect(c.mappingSaving()).toBe(false);
  });

  it('deletes a mapping after the confirmation, then reloads', async () => {
    const { c, api, toast } = await setup();
    c.removeMapping(); // nothing to confirm
    expect(api.deleteGremiumGroupMapping).not.toHaveBeenCalled();
    c.mappingDeleteId.set('gm-2');
    c.removeMapping();
    expect(api.deleteGremiumGroupMapping).toHaveBeenCalledWith('gm-2');
    expect(c.mappingDeleteId()).toBeNull();
    expect(toast.success).toHaveBeenCalledWith('Mapping gelöscht. Die Mitglieder sind aktualisiert.');
    expect(api.listGremiumMemberships).toHaveBeenCalledTimes(2);
  });

  it('a failed delete shows a toast and keeps the confirmation', async () => {
    const api = makeApi({ deleteGremiumGroupMapping: jest.fn(() => throwError(() => new Error('x'))) });
    const { c, toast } = await setup(api);
    c.mappingDeleteId.set('gm-1');
    c.removeMapping();
    expect(toast.error).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
    expect(c.mappingDeleteId()).toBe('gm-1');
  });

  it('the row controls open the edit dialog and the delete confirmation', async () => {
    const { c } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten: stupa-vorsitz' }));
    expect(screen.getByRole('dialog', { name: 'Mapping bearbeiten' })).toBeInTheDocument();
    c.closeMapping();
    await userEvent.click(screen.getByRole('button', { name: 'Löschen: stupa-alt' }));
    expect(c.mappingDeleteId()).toBe('gm-2');
  });

  it('the add control opens the dialog, with a link to the roles page when none exist', async () => {
    const api = makeApi({ listGremiumRoles: jest.fn(() => of([])) });
    await setup(api);
    await userEvent.click(screen.getByRole('button', { name: 'Gruppe zuordnen' }));
    expect(screen.getByRole('dialog', { name: 'Gruppe zuordnen' })).toBeInTheDocument();
    expect(screen.getByRole('link')).toHaveAttribute('href', '/admin/gremien/g-1/roles');
  });

  // --- permission gating ----------------------------------------------------

  it('hides the mapping controls without admin.gremien', async () => {
    const { c } = await setup(makeApi(), makeDelegationsApi(), makeToast(), false);
    expect(c.canManage()).toBe(false);
    expect(c.mappingColumns().map((col: { key: string }) => col.key)).toEqual(['oidcGroup', 'roleLabel']);
    expect(screen.queryByRole('button', { name: 'Gruppe zuordnen' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Bearbeiten: stupa-vorsitz' })).toBeNull();
  });

  it('shows the mapping action column with admin.gremien', async () => {
    const { c } = await setup();
    expect(c.mappingColumns().map((col: { key: string }) => col.key)).toContain('actions');
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
