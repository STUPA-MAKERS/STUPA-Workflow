import { provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { ToastService } from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import type {
  GremiumMembershipMapping,
  GremiumRole,
  GremiumRoleMapping,
  GroupMapping,
  Role,
} from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { GroupMappingsComponent } from './group-mappings.component';

const GLOBAL: GroupMapping[] = [
  { id: 'm1', oidcGroup: 'stupa-vorstand', roleId: 'r1' },
  { id: 'm2', oidcGroup: 'ghost-role', roleId: 'unknown-role' },
];
const MEMBERSHIP: GremiumMembershipMapping[] = [
  { id: 'mm1', gremiumId: 'g1', oidcGroup: 'stupa-mitglieder' },
  { id: 'mm2', gremiumId: 'unknown-gremium', oidcGroup: 'ghost-gremium' },
];
const ROLE_MAPPINGS: GremiumRoleMapping[] = [
  { id: 'rm1', gremiumId: 'g1', gremiumRoleId: 'gr1', oidcGroup: 'stupa-praesidium' },
  { id: 'rm2', gremiumId: 'g1', gremiumRoleId: 'gr-x', oidcGroup: 'stupa-alt' },
  { id: 'rm3', gremiumId: 'g2', gremiumRoleId: 'gr3', oidcGroup: 'asta-vorstand' },
];

const ROLES: Role[] = [
  { id: 'r1', key: 'board', label: { de: 'Vorstand', en: 'Board' }, permissions: [] },
  { id: 'r2', key: 'officer', label: { en: 'Officer' }, permissions: [] },
];
const GREMIUM_ROLES: Record<string, GremiumRole[]> = {
  g1: [
    { id: 'gr1', gremiumId: 'g1', key: 'board', name: { de: 'Präsidium', en: 'Presidium' } },
    { id: 'gr2', gremiumId: 'g1', key: 'member', name: { en: 'Member' } },
  ],
  g2: [{ id: 'gr3', gremiumId: 'g2', key: 'board', name: { de: 'Vorstand' } }],
  g3: [],
};

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listRoles: jest.fn(() => of(ROLES.map((r) => ({ ...r })))),
    listGremienOptions: jest.fn(() =>
      of([
        { id: 'g1', name: 'StuPa' },
        { id: 'g2', name: 'AStA' },
        { id: 'g3', name: 'FSR' },
      ]),
    ),
    listGremiumRoles: jest.fn((gid: string) => of([...(GREMIUM_ROLES[gid] ?? [])])),
    listGroupMappings: jest.fn(() => of(GLOBAL.map((m) => ({ ...m })))),
    createGroupMapping: jest.fn(() => of({ id: 'm-new' })),
    updateGroupMapping: jest.fn(() => of({ id: 'm1' })),
    deleteGroupMapping: jest.fn(() => of(void 0)),
    listMembershipMappings: jest.fn(() => of(MEMBERSHIP.map((m) => ({ ...m })))),
    createMembershipMapping: jest.fn(() => of({ id: 'mm-new' })),
    updateMembershipMapping: jest.fn(() => of({ id: 'mm1' })),
    deleteMembershipMapping: jest.fn(() => of(void 0)),
    listRoleMappings: jest.fn(() => of(ROLE_MAPPINGS.map((m) => ({ ...m })))),
    createRoleMapping: jest.fn(() => of({ id: 'rm-new' })),
    updateRoleMapping: jest.fn(() => of({ id: 'rm1' })),
    deleteRoleMapping: jest.fn(() => of(void 0)),
    ...over,
  };
}

function makeToast() {
  return { success: jest.fn(), error: jest.fn() };
}

async function setup(api = makeApi(), toast = makeToast(), can = true) {
  const view = await render(GroupMappingsComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
      { provide: AuthService, useValue: { can: () => can } },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, toast, c };
}

describe('GroupMappingsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows three separate sections, each with its own table', async () => {
    await setup();
    for (const name of ['Globale Rollen', 'Gremien-Mitgliedschaft', 'Gremien-Rollen']) {
      expect(screen.getByRole('heading', { level: 2, name })).toBeInTheDocument();
    }
    const global = screen.getByRole('region', { name: 'Globale Rollen' });
    expect(within(global).getByText('stupa-vorstand')).toBeInTheDocument();
    expect(within(global).queryByText('StuPa')).toBeNull();
    const membership = screen.getByRole('region', { name: 'Gremien-Mitgliedschaft' });
    expect(within(membership).getByText('stupa-mitglieder')).toBeInTheDocument();
    const role = screen.getByRole('region', { name: 'Gremien-Rollen' });
    expect(within(role).getByText('Präsidium')).toBeInTheDocument();
  });

  it('resolves names and never shows a raw id', async () => {
    const { c } = await setup();
    expect(c.globalRows()).toEqual([
      { id: 'm1', oidcGroup: 'stupa-vorstand', roleLabel: 'Vorstand' },
      { id: 'm2', oidcGroup: 'ghost-role', roleLabel: '(unbekannt)' },
    ]);
    expect(c.membershipRows()).toEqual([
      { id: 'mm1', oidcGroup: 'stupa-mitglieder', gremiumLabel: 'StuPa' },
      { id: 'mm2', oidcGroup: 'ghost-gremium', gremiumLabel: '(unbekannt)' },
    ]);
    expect(c.roleRows()).toEqual([
      { id: 'rm1', oidcGroup: 'stupa-praesidium', gremiumLabel: 'StuPa', roleLabel: 'Präsidium' },
      { id: 'rm2', oidcGroup: 'stupa-alt', gremiumLabel: 'StuPa', roleLabel: '(unbekannt)' },
      { id: 'rm3', oidcGroup: 'asta-vorstand', gremiumLabel: 'AStA', roleLabel: 'Vorstand' },
    ]);
  });

  it('loads the roles of each gremium of the role mappings once, quietly', async () => {
    const { api } = await setup();
    expect(api.listGremiumRoles).toHaveBeenCalledTimes(2);
    expect(api.listGremiumRoles).toHaveBeenCalledWith('g1', { quiet: true });
    expect(api.listGremiumRoles).toHaveBeenCalledWith('g2', { quiet: true });
  });

  it('shows each section as rows "group → target", a gremium role after its gremium', async () => {
    const { c } = await setup();
    expect(c.sections().map((sec: { kind: string }) => sec.kind)).toEqual(['global', 'membership', 'role']);
    expect(c.sections()[0].rows[0]).toEqual({ id: 'm1', oidcGroup: 'stupa-vorstand', target: 'Vorstand', role: null });
    expect(c.sections()[2].rows[0]).toEqual({
      id: 'rm1',
      oidcGroup: 'stupa-praesidium',
      target: 'StuPa',
      role: 'Präsidium',
    });
    const role = screen.getByRole('region', { name: 'Gremien-Rollen' });
    expect(within(role).getByText('Präsidium').tagName).toBe('STRONG');
    // The reserved prefix stands once at the foot of the page.
    expect(screen.getByText('Das Präfix „vote:“ ist reserviert.')).toBeInTheDocument();
  });

  it('role names follow the locale → de → key fallbacks', async () => {
    const { c } = await setup();
    expect(c.roleOptions()).toEqual([
      { value: 'r1', label: 'Vorstand' },
      { value: 'r2', label: 'officer' },
    ]);
    expect(c.gremiumOptions()).toEqual([
      { value: 'g1', label: 'StuPa' },
      { value: 'g2', label: 'AStA' },
      { value: 'g3', label: 'FSR' },
    ]);
  });

  it('uses the en labels with the en locale', async () => {
    localStorage.setItem('ap.locale', 'en');
    const { c } = await setup();
    expect(c.roleOptions()[1]).toEqual({ value: 'r2', label: 'Officer' });
    expect(c.roleRows()[0].roleLabel).toBe('Presidium');
  });

  it('falls back to empty sources when roles or gremien fail to load', async () => {
    const api = makeApi({
      listRoles: jest.fn(() => throwError(() => new Error('x'))),
      listGremienOptions: jest.fn(() => throwError(() => new Error('y'))),
      listGremiumRoles: jest.fn(() => throwError(() => new Error('z'))),
    });
    const { c } = await setup(api);
    expect(c.roleOptions()).toEqual([]);
    expect(c.gremiumOptions()).toEqual([]);
    expect(c.roleRows()[0].roleLabel).toBe('(unbekannt)');
  });

  it.each([
    ['listGroupMappings', 'global'],
    ['listMembershipMappings', 'membership'],
    ['listRoleMappings', 'role'],
  ])('a failed %s shows a toast and ends the %s loading state', async (method, kind) => {
    const api = makeApi({ [method]: jest.fn(() => throwError(() => new Error('x'))) });
    const { c, toast } = await setup(api);
    expect(toast.error).toHaveBeenCalledWith('Die Zuordnungen konnten nicht geladen werden.');
    expect(c.loading()[kind]).toBe(false);
  });

  it('shows the empty state of each section', async () => {
    const api = makeApi({
      listGroupMappings: jest.fn(() => of([])),
      listMembershipMappings: jest.fn(() => of([])),
      listRoleMappings: jest.fn(() => of([])),
    });
    await setup(api);
    expect(screen.getByText('Noch keine OIDC-Gruppe einer globalen Rolle zugeordnet.')).toBeInTheDocument();
    expect(screen.getByText(/Noch keine OIDC-Gruppe einem Gremium zugeordnet/)).toBeInTheDocument();
    expect(screen.getByText('Noch keine OIDC-Gruppe einer Gremien-Rolle zugeordnet.')).toBeInTheDocument();
  });

  // --- dialogs -----------------------------------------------------------------

  it('the global dialog has a role select and no gremium field', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Globale Rolle zuordnen' }));
    const dialog = screen.getByRole('dialog', { name: 'Globale Rolle zuordnen' });
    expect(within(dialog).getByLabelText(/OIDC-Gruppe/)).toBeInTheDocument();
    expect(within(dialog).getByText('Rolle')).toBeInTheDocument();
    expect(within(dialog).queryByText('Gremium')).toBeNull();
  });

  it('the membership dialog has a gremium select and no role field', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Mitgliedschaft zuordnen' }));
    const dialog = screen.getByRole('dialog', { name: 'Mitgliedschaft zuordnen' });
    expect(within(dialog).getByText('Gremium')).toBeInTheDocument();
    expect(within(dialog).queryByText('Rolle')).toBeNull();
  });

  it('the role dialog has a gremium filter, a gremium role select and the rule hint', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Gremien-Rolle zuordnen' }));
    const dialog = screen.getByRole('dialog', { name: 'Gremien-Rolle zuordnen' });
    expect(within(dialog).getByText('Gremium')).toBeInTheDocument();
    expect(within(dialog).getByText('Gremien-Rolle')).toBeInTheDocument();
    expect(within(dialog).getByText(/die Rolle mit den meisten Rechten/)).toBeInTheDocument();
  });

  it('openAdd resets the form', async () => {
    const { c } = await setup();
    c.oidcGroup.set('x');
    c.roleId.set('r1');
    c.gremiumId.set('g1');
    c.gremiumRoleId.set('gr1');
    c.editId.set('m1');
    c.openAdd('membership');
    expect(c.dialog()).toBe('membership');
    expect(c.editId()).toBeNull();
    expect([c.oidcGroup(), c.roleId(), c.gremiumId(), c.gremiumRoleId()]).toEqual(['', '', '', '']);
    expect(c.dialogTitle()).toBe('admin.groupMappings.membership.add');
  });

  it('openEdit seeds each kind of dialog', async () => {
    const { c } = await setup();
    c.openEdit('global', 'm1');
    expect([c.dialog(), c.editId(), c.oidcGroup(), c.roleId()]).toEqual(['global', 'm1', 'stupa-vorstand', 'r1']);
    expect(c.dialogTitle()).toBe('admin.groupMappings.global.editTitle');
    c.openEdit('membership', 'mm1');
    expect([c.oidcGroup(), c.gremiumId(), c.roleId()]).toEqual(['stupa-mitglieder', 'g1', '']);
    c.openEdit('role', 'rm1');
    expect([c.oidcGroup(), c.gremiumId(), c.gremiumRoleId()]).toEqual(['stupa-praesidium', 'g1', 'gr1']);
    expect(c.gremiumRoleOptions()).toEqual([
      { value: 'gr1', label: 'Präsidium' },
      { value: 'gr2', label: 'member' },
    ]);
  });

  it('openEdit ignores an unknown id', async () => {
    const { c } = await setup();
    c.openEdit('role', 'nope');
    expect(c.dialog()).toBeNull();
  });

  it('the gremium select of the role dialog loads that gremium roles and clears the role', async () => {
    const { c, api } = await setup();
    c.openAdd('role');
    expect(c.dialogGremiumRoles()).toEqual([]);
    c.onDialogGremium('g3');
    expect(api.listGremiumRoles).toHaveBeenCalledWith('g3', { quiet: true });
    expect(c.dialogGremiumRoles()).toEqual([]);
    c.onDialogGremium('g1');
    c.gremiumRoleId.set('gr1');
    // The same gremium again keeps the role.
    c.onDialogGremium('g1');
    expect(c.gremiumRoleId()).toBe('gr1');
    c.onDialogGremium('g2');
    expect(c.gremiumRoleId()).toBe('');
    // g1 and g2 came with the mappings already. Only g3 was new.
    expect(api.listGremiumRoles).toHaveBeenCalledTimes(3);
    // Clearing the gremium loads nothing.
    c.onDialogGremium('');
    expect(api.listGremiumRoles).toHaveBeenCalledTimes(3);
  });

  it('the membership dialog does not load gremium roles', async () => {
    const { c, api } = await setup();
    c.openAdd('membership');
    c.onDialogGremium('g3');
    expect(c.gremiumId()).toBe('g3');
    expect(api.listGremiumRoles).toHaveBeenCalledTimes(2);
  });

  it('shows a link to the roles page when the gremium has no roles', async () => {
    const { c, fixture } = await setup();
    c.openAdd('role');
    c.onDialogGremium('g3');
    fixture.detectChanges();
    expect(screen.getByText('Dieses Gremium hat noch keine Rollen.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Rollen verwalten' })).toHaveAttribute('href', '/admin/gremien/g3/roles');
  });

  it('hides the roles link without admin.gremium_roles', async () => {
    const { c, fixture } = await setup(makeApi(), makeToast(), false);
    c.openAdd('role');
    c.onDialogGremium('g3');
    fixture.detectChanges();
    expect(screen.getByText('Dieses Gremium hat noch keine Rollen.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Rollen verwalten' })).toBeNull();
  });

  it('validates the group name and the select of each kind', async () => {
    const { c } = await setup();
    expect(c.valid()).toBe(false); // no dialog
    c.openAdd('global');
    c.oidcGroup.set('  ');
    c.roleId.set('r1');
    expect(c.valid()).toBe(false);
    c.oidcGroup.set(' vote:abc ');
    expect(c.groupReserved()).toBe(true);
    expect(c.valid()).toBe(false);
    c.oidcGroup.set('grp');
    expect(c.valid()).toBe(true);
    c.roleId.set('');
    expect(c.valid()).toBe(false);

    c.openAdd('membership');
    c.oidcGroup.set('grp');
    expect(c.valid()).toBe(false);
    c.gremiumId.set('g1');
    expect(c.valid()).toBe(true);

    c.openAdd('role');
    c.oidcGroup.set('grp');
    c.onDialogGremium('g1');
    expect(c.valid()).toBe(false);
    c.gremiumRoleId.set('gr1');
    expect(c.valid()).toBe(true);
  });

  it('shows the reserved-prefix error inline', async () => {
    const { c, fixture } = await setup();
    c.openAdd('membership');
    c.oidcGroup.set('vote:x');
    fixture.detectChanges();
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Das Präfix „vote:“ ist reserviert.')).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/OIDC-Gruppe/)).toHaveAttribute('aria-invalid', 'true');
  });

  it('save is a no-op without a dialog, when invalid, or while a save runs', async () => {
    const { c, api } = await setup();
    c.save();
    c.openAdd('global');
    c.save();
    c.oidcGroup.set('grp');
    c.roleId.set('r1');
    c.saving.set(true);
    c.save();
    expect(api.createGroupMapping).not.toHaveBeenCalled();
  });

  it.each([
    ['global', 'createGroupMapping', 'listGroupMappings', { roleId: 'r1' }],
    ['membership', 'createMembershipMapping', 'listMembershipMappings', { gremiumId: 'g1' }],
    ['role', 'createRoleMapping', 'listRoleMappings', { gremiumRoleId: 'gr1' }],
  ])('creates a %s mapping with a trimmed group, then reloads that list', async (kind, create, list, extra) => {
    const { c, api, toast } = await setup();
    c.openAdd(kind);
    c.oidcGroup.set('  new-grp ');
    c.roleId.set('r1');
    c.gremiumId.set('g1');
    c.gremiumRoleId.set('gr1');
    c.save();
    expect(api[create]).toHaveBeenCalledWith({ oidcGroup: 'new-grp', ...extra });
    expect(c.dialog()).toBeNull();
    expect(c.saving()).toBe(false);
    expect(toast.success).toHaveBeenCalledWith('Zuordnung gespeichert.');
    expect(api[list]).toHaveBeenCalledTimes(2);
  });

  it.each([
    ['global', 'm1', 'updateGroupMapping', { oidcGroup: 'stupa-vorstand', roleId: 'r2' }],
    ['membership', 'mm1', 'updateMembershipMapping', { oidcGroup: 'stupa-mitglieder', gremiumId: 'g2' }],
    ['role', 'rm1', 'updateRoleMapping', { oidcGroup: 'stupa-praesidium', gremiumRoleId: 'gr2' }],
  ])('updates a %s mapping', async (kind, id, update, body) => {
    const { c, api } = await setup();
    c.openEdit(kind, id);
    if (kind === 'global') c.roleId.set('r2');
    if (kind === 'membership') c.gremiumId.set('g2');
    if (kind === 'role') c.gremiumRoleId.set('gr2');
    c.save();
    expect(api[update]).toHaveBeenCalledWith(id, body);
  });

  it.each([
    [409, 'Diese Zuordnung gibt es schon.'],
    [422, 'Ungültiger Gruppenname: leer oder mit dem reservierten Präfix „vote:“.'],
    [404, 'Das Gremium oder die Rolle gibt es nicht mehr. Lade die Seite neu.'],
    [500, 'Aktion fehlgeschlagen.'],
    [undefined, 'Aktion fehlgeschlagen.'],
  ])('a save that answers %s names the reason and keeps the dialog open', async (status, text) => {
    const api = makeApi({ createMembershipMapping: jest.fn(() => throwError(() => ({ status }))) });
    const { c, toast } = await setup(api);
    c.openAdd('membership');
    c.oidcGroup.set('grp');
    c.gremiumId.set('g1');
    c.save();
    expect(toast.error).toHaveBeenCalledWith(text);
    expect(c.dialog()).toBe('membership');
    expect(c.saving()).toBe(false);
  });

  it('closeDialog closes the dialog', async () => {
    const { c } = await setup();
    c.openAdd('global');
    c.closeDialog();
    expect(c.dialog()).toBeNull();
  });

  // --- delete ------------------------------------------------------------------

  it.each([
    ['global', 'm1', 'deleteGroupMapping', 'listGroupMappings'],
    ['membership', 'mm1', 'deleteMembershipMapping', 'listMembershipMappings'],
    ['role', 'rm1', 'deleteRoleMapping', 'listRoleMappings'],
  ])('deletes a %s mapping after the confirmation', async (kind, id, del, list) => {
    const { c, api, toast } = await setup();
    c.askDelete(kind, id);
    expect(c.confirmBody()).toBe(`admin.groupMappings.${kind}.deleteBody`);
    c.remove();
    expect(api[del]).toHaveBeenCalledWith(id);
    expect(c.confirm()).toBeNull();
    expect(toast.success).toHaveBeenCalledWith('Zuordnung gelöscht.');
    expect(api[list]).toHaveBeenCalledTimes(2);
  });

  it('remove is a no-op without a confirmation', async () => {
    const { c, api } = await setup();
    expect(c.confirmBody()).toBe('admin.groupMappings.title');
    c.remove();
    expect(api.deleteGroupMapping).not.toHaveBeenCalled();
  });

  it('a failed delete shows a toast and keeps the confirmation', async () => {
    const api = makeApi({ deleteRoleMapping: jest.fn(() => throwError(() => new Error('x'))) });
    const { c, toast } = await setup(api);
    c.askDelete('role', 'rm1');
    c.remove();
    expect(toast.error).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
    expect(c.confirm()).toEqual({ kind: 'role', id: 'rm1' });
  });

  it('the row controls open the edit dialog and the delete confirmation', async () => {
    const { c } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten: stupa-praesidium' }));
    expect(screen.getByRole('dialog', { name: 'Gremien-Rolle bearbeiten' })).toBeInTheDocument();
    c.closeDialog();
    await userEvent.click(screen.getByRole('button', { name: 'Löschen: stupa-mitglieder' }));
    expect(c.confirm()).toEqual({ kind: 'membership', id: 'mm1' });
  });
});
