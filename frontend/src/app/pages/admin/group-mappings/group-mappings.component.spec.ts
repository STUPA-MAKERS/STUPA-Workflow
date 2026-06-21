import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { ToastService } from '@stupa-makers/ui-kit';
import type { GroupMapping, Role } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { GroupMappingsComponent } from './group-mappings.component';

const MAPPINGS: GroupMapping[] = [
  { id: 'm1', oidcGroup: 'stupa-vorstand', roleId: 'r1', gremiumId: 'g1' },
  { id: 'm2', oidcGroup: 'fsr-info', roleId: 'r1', gremiumId: null },
  { id: 'm3', oidcGroup: 'ghost-role', roleId: 'unknown-role', gremiumId: 'unknown-gremium' },
];

const ROLES: Role[] = [
  { id: 'r1', key: 'board', label: { de: 'Vorstand', en: 'Board' }, permissions: [] },
  { id: 'r2', key: 'officer', label: { en: 'Officer' }, permissions: [] },
];

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listGroupMappings: jest.fn(() => of(MAPPINGS.map((m) => ({ ...m })))),
    listRoles: jest.fn(() => of(ROLES.map((r) => ({ ...r })))),
    listGremienOptions: jest.fn(() => of([{ id: 'g1', name: 'StuPa' }])),
    createGroupMapping: jest.fn(() => of({ id: 'm-new', oidcGroup: 'x', roleId: 'r1', gremiumId: null })),
    updateGroupMapping: jest.fn(() => of({ id: 'm1', oidcGroup: 'x', roleId: 'r1', gremiumId: null })),
    deleteGroupMapping: jest.fn(() => of(void 0)),
    ...over,
  };
}

function makeToast() {
  return { success: jest.fn(), error: jest.fn() };
}

async function setup(api = makeApi(), toast = makeToast()) {
  const view = await render(GroupMappingsComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, toast, c };
}

describe('GroupMappingsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists mappings with resolved role + committee, "global" for none, raw fallbacks for unknown', async () => {
    const { c } = await setup();
    expect(await screen.findByText('stupa-vorstand')).toBeInTheDocument();
    expect(screen.getByText('fsr-info')).toBeInTheDocument();
    expect(screen.getAllByText('Vorstand').length).toBeGreaterThan(0);
    expect(screen.getByText('StuPa')).toBeInTheDocument();
    // null gremium → global marker.
    expect(screen.getByText('— (global)')).toBeInTheDocument();

    const rows = c.rows();
    // unknown role id resolves to the raw id, unknown gremium id resolves to raw id
    const ghost = rows.find((r: { id: string }) => r.id === 'm3');
    expect(ghost.roleLabel).toBe('unknown-role');
    expect(ghost.gremiumLabel).toBe('unknown-gremium');
    // null gremium → empty gremiumLabel
    const fsr = rows.find((r: { id: string }) => r.id === 'm2');
    expect(fsr.gremiumLabel).toBe('');
  });

  it('roleName + roleOptions follow locale→de→key fallbacks', async () => {
    const { c } = await setup();
    expect(c.roleName(ROLES[0])).toBe('Vorstand');
    // r2 has no de → falls to key (de locale active)
    expect(c.roleName(ROLES[1])).toBe('officer');
    const opts = c.roleOptions();
    expect(opts).toEqual([
      { value: 'r1', label: 'Vorstand' },
      { value: 'r2', label: 'officer' },
    ]);
  });

  it('roleName uses en when locale en', async () => {
    localStorage.setItem('ap.locale', 'en');
    const { c } = await setup();
    expect(c.roleName(ROLES[0])).toBe('Board');
    expect(c.roleName(ROLES[1])).toBe('Officer');
  });

  it('gremiumOptions begins with the global option', async () => {
    const { c } = await setup();
    expect(c.gremiumOptions()).toEqual([
      { value: '', label: '— (global)' },
      { value: 'g1', label: 'StuPa' },
    ]);
  });

  it('falls back to empty lists when roles/gremien loads error', async () => {
    const api = makeApi({
      listRoles: jest.fn(() => throwError(() => new Error('x'))),
      listGremienOptions: jest.fn(() => throwError(() => new Error('y'))),
    });
    const { c } = await setup(api);
    expect(c.roleOptions()).toEqual([]);
    expect(c.gremiumOptions()).toEqual([{ value: '', label: '— (global)' }]);
  });

  it('shows an error toast when mappings fail to load', async () => {
    const api = makeApi({ listGroupMappings: jest.fn(() => throwError(() => new Error('x'))) });
    const { c, toast } = await setup(api);
    expect(toast.error).toHaveBeenCalled();
    expect(c.rows()).toEqual([]);
  });

  it('openAdd resets the form and opens the dialog', async () => {
    const { c } = await setup();
    c.editId.set('m1');
    c.oidcGroup.set('keep');
    c.openAdd();
    expect(c.editId()).toBeNull();
    expect(c.oidcGroup()).toBe('');
    expect(c.roleId()).toBe('');
    expect(c.gremiumId()).toBe('');
    expect(c.dialogOpen()).toBe(true);
  });

  it('openEdit loads a mapping (gremiumId present and null→empty)', async () => {
    const { c } = await setup();
    c.openEdit('m1');
    expect(c.editId()).toBe('m1');
    expect(c.oidcGroup()).toBe('stupa-vorstand');
    expect(c.roleId()).toBe('r1');
    expect(c.gremiumId()).toBe('g1');
    expect(c.dialogOpen()).toBe(true);
    // null gremium → empty
    c.openEdit('m2');
    expect(c.gremiumId()).toBe('');
  });

  it('openEdit is a no-op for an unknown id', async () => {
    const { c } = await setup();
    c.openEdit('nope');
    expect(c.dialogOpen()).toBe(false);
  });

  it('save is a no-op when oidcGroup or roleId is missing', async () => {
    const { c, api } = await setup();
    c.oidcGroup.set('  ');
    c.roleId.set('r1');
    c.save();
    expect(api.createGroupMapping).not.toHaveBeenCalled();
    c.oidcGroup.set('grp');
    c.roleId.set('');
    c.save();
    expect(api.createGroupMapping).not.toHaveBeenCalled();
  });

  it('creates a mapping (no editId → POST, global gremium → null)', async () => {
    const { c, api, toast } = await setup();
    c.openAdd();
    c.oidcGroup.set('  new-grp  ');
    c.roleId.set('r1');
    c.gremiumId.set('');
    c.save();
    expect(api.createGroupMapping).toHaveBeenCalledWith({ oidcGroup: 'new-grp', roleId: 'r1', gremiumId: null });
    expect(api.updateGroupMapping).not.toHaveBeenCalled();
    expect(c.dialogOpen()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
    expect(api.listGroupMappings).toHaveBeenCalledTimes(2); // initial + refresh
  });

  it('updates a mapping when editing (PATCH, concrete gremium)', async () => {
    const { c, api } = await setup();
    c.openEdit('m1');
    c.oidcGroup.set('changed');
    c.gremiumId.set('g1');
    c.save();
    expect(api.updateGroupMapping).toHaveBeenCalledWith('m1', {
      oidcGroup: 'changed',
      roleId: 'r1',
      gremiumId: 'g1',
    });
    expect(api.createGroupMapping).not.toHaveBeenCalled();
  });

  it('save error path shows an error toast and keeps the dialog open', async () => {
    const api = makeApi({ createGroupMapping: jest.fn(() => throwError(() => new Error('x'))) });
    const { c, toast } = await setup(api);
    c.openAdd();
    c.oidcGroup.set('grp');
    c.roleId.set('r1');
    c.save();
    expect(toast.error).toHaveBeenCalled();
    expect(c.dialogOpen()).toBe(true);
  });

  it('remove is a no-op without a confirm id', async () => {
    const { c, api } = await setup();
    c.remove();
    expect(api.deleteGroupMapping).not.toHaveBeenCalled();
  });

  it('removes a mapping after confirmation', async () => {
    const { c, api, toast } = await setup();
    c.confirmId.set('m1');
    c.remove();
    expect(api.deleteGroupMapping).toHaveBeenCalledWith('m1');
    expect(c.confirmId()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
  });

  it('remove error path shows an error toast and keeps confirmId', async () => {
    const api = makeApi({ deleteGroupMapping: jest.fn(() => throwError(() => new Error('x'))) });
    const { c, toast } = await setup(api);
    c.confirmId.set('m1');
    c.remove();
    expect(toast.error).toHaveBeenCalled();
    expect(c.confirmId()).toBe('m1');
  });

  it('opens the add dialog from the toolbar button', async () => {
    await setup();
    await userEvent.click(await screen.findByRole('button', { name: 'Mapping hinzufügen' }));
    expect(screen.getByPlaceholderText('Gruppenname aus dem IdP')).toBeInTheDocument();
  });
});
