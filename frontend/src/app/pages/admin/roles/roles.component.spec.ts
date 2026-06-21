import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { ToastService } from '@stupa-makers/ui-kit';
import type { Role } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { AdminRolesComponent } from './roles.component';

const ROLES: Role[] = [
  { id: 'r-admin', key: 'admin', label: { de: 'administrator', en: 'administrator' }, permissions: ['admin.roles'] },
  { id: 'r-member', key: 'member', label: { de: 'mitglied', en: 'member' }, permissions: ['application.read'] },
  { id: 'r-ref', key: 'referent', label: { en: 'officer' }, permissions: [] },
];

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listRoles: jest.fn(() => of(ROLES.map((r) => ({ ...r, permissions: [...r.permissions] })))),
    listPermissions: jest.fn(() => of(['admin.roles', 'application.read', 'flow.configure'])),
    saveRolePermissions: jest.fn((id: string, perms: string[]) => of({ ...ROLES[1], id, permissions: perms })),
    renameRole: jest.fn((id: string, label: Record<string, string>) => of({ ...ROLES[1], id, label })),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    createRole: jest.fn((body: any) => of({ id: 'r-new', key: body.key, label: body.label, permissions: [] })),
    deleteRole: jest.fn(() => of(void 0)),
    ...over,
  };
}

function makeToast() {
  return { success: jest.fn(), error: jest.fn() };
}

async function setup(api = makeApi(), toast = makeToast()) {
  const view = await render(AdminRolesComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const inst = view.fixture.componentInstance as any;
  return { ...view, api, toast, inst };
}

describe('AdminRolesComponent (#12)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists roles with capitalized labels and loads the permission catalog', async () => {
    const { inst } = await setup();
    expect(screen.getAllByText('Administrator').length).toBeGreaterThan(0);
    expect(screen.getByText('admin')).toBeInTheDocument();
    expect(inst.permissions()).toEqual(['admin.roles', 'application.read', 'flow.configure']);
  });

  it('roleLabel falls back locale→de→key', async () => {
    const { inst } = await setup();
    expect(inst.roleLabel(ROLES[0])).toBe('administrator');
    // de locale present
    expect(inst.roleLabel({ label: { de: 'x' }, key: 'k' })).toBe('x');
    // no de, falls to key (en is not the active locale fallback)
    expect(inst.roleLabel({ label: { en: 'y' }, key: 'k' })).toBe('k');
    expect(inst.roleLabel({ label: {}, key: 'k' })).toBe('k');
  });

  it('roleLabel uses en when locale en', async () => {
    localStorage.setItem('ap.locale', 'en');
    const { inst } = await setup();
    expect(inst.roleLabel(ROLES[2])).toBe('officer');
  });

  it('isLocked is true only for admin', async () => {
    const { inst } = await setup();
    expect(inst.isLocked({ key: 'admin' })).toBe(true);
    expect(inst.isLocked({ key: 'member' })).toBe(false);
  });

  it('canDelete protects admin + member only (#38)', async () => {
    const { inst } = await setup();
    expect(inst.canDelete({ key: 'admin' })).toBe(false);
    expect(inst.canDelete({ key: 'member' })).toBe(false);
    expect(inst.canDelete({ key: 'referent' })).toBe(true);
  });

  it('onRowClick toggles the row expansion both ways (#40)', async () => {
    const { inst } = await setup();
    expect(inst.rowExpanded(ROLES[2])).toBe(false);
    inst.onRowClick(ROLES[2]);
    expect(inst.rowExpanded(ROLES[2])).toBe(true);
    expect(inst.expanded().has('r-ref')).toBe(true);
    inst.onRowClick(ROLES[2]);
    expect(inst.rowExpanded(ROLES[2])).toBe(false);
  });

  it('togglePerm adds and removes a permission on the local role', async () => {
    const { inst } = await setup();
    inst.togglePerm(ROLES[1], 'flow.configure', true);
    let role = inst.roles().find((r: Role) => r.id === 'r-member');
    expect(role.permissions).toContain('flow.configure');
    inst.togglePerm(role, 'application.read', false);
    role = inst.roles().find((r: Role) => r.id === 'r-member');
    expect(role.permissions).not.toContain('application.read');
    expect(role.permissions).toContain('flow.configure');
  });

  it('saveRole persists and replaces the role; success toast', async () => {
    const { inst, api, toast } = await setup();
    inst.togglePerm(ROLES[1], 'flow.configure', true);
    inst.togglePerm(inst.roles().find((r: Role) => r.id === 'r-member'), 'application.read', false);
    inst.saveRole(inst.roles().find((r: Role) => r.id === 'r-member'));
    expect(api.saveRolePermissions).toHaveBeenCalledWith('r-member', ['flow.configure']);
    expect(toast.success).toHaveBeenCalled();
  });

  it('saveRole error path shows an error toast', async () => {
    const api = makeApi({ saveRolePermissions: jest.fn(() => throwError(() => new Error('x'))) });
    const { inst, toast } = await setup(api);
    inst.saveRole(inst.roles().find((r: Role) => r.id === 'r-member'));
    expect(toast.error).toHaveBeenCalled();
  });

  it('nameDraft returns label-derived default then the patched draft', async () => {
    const { inst } = await setup();
    expect(inst.nameDraft(ROLES[1])).toEqual({ de: 'mitglied', en: 'member' });
    // referent has no de label → empty string
    expect(inst.nameDraft(ROLES[2])).toEqual({ de: '', en: 'officer' });
    // role with neither de nor en → both empty
    expect(inst.nameDraft({ id: 'r-x', key: 'x', label: {}, permissions: [] })).toEqual({ de: '', en: '' });
    inst.patchName(ROLES[1], 'de', 'Mitglied!');
    expect(inst.nameDraft(ROLES[1])).toEqual({ de: 'Mitglied!', en: 'member' });
    inst.patchName(ROLES[1], 'en', 'Member!');
    expect(inst.nameDraft(ROLES[1])).toEqual({ de: 'Mitglied!', en: 'Member!' });
  });

  it('renameRole persists and updates the role; success toast', async () => {
    const { inst, api, toast } = await setup();
    inst.patchName(ROLES[1], 'de', 'Mitglied');
    inst.patchName(ROLES[1], 'en', 'Member');
    inst.renameRole(inst.roles().find((r: Role) => r.id === 'r-member'));
    expect(api.renameRole).toHaveBeenCalledWith('r-member', { de: 'Mitglied', en: 'Member' });
    expect(toast.success).toHaveBeenCalled();
    const updated = inst.roles().find((r: Role) => r.id === 'r-member');
    expect(updated.label).toEqual({ de: 'Mitglied', en: 'Member' });
  });

  it('renameRole error path shows an error toast', async () => {
    const api = makeApi({ renameRole: jest.fn(() => throwError(() => new Error('x'))) });
    const { inst, toast } = await setup(api);
    inst.renameRole(inst.roles().find((r: Role) => r.id === 'r-member'));
    expect(toast.error).toHaveBeenCalled();
  });

  it('openAdd resets the draft and patchDraft mutates it', async () => {
    const { inst } = await setup();
    inst.openAdd();
    expect(inst.addOpen()).toBe(true);
    expect(inst.draft()).toEqual({ key: '', labelDe: '', labelEn: '' });
    inst.patchDraft('key', 'x');
    expect(inst.draft().key).toBe('x');
  });

  it('createRole is a no-op when the key is blank', async () => {
    const { inst, api } = await setup();
    inst.openAdd();
    inst.patchDraft('key', '   ');
    inst.createRole();
    expect(api.createRole).not.toHaveBeenCalled();
  });

  it('creates a role with only the labels that are non-empty', async () => {
    const { inst, api, toast } = await setup();
    inst.openAdd();
    inst.patchDraft('key', 'referent');
    inst.patchDraft('labelDe', 'Referent');
    inst.createRole();
    expect(api.createRole).toHaveBeenCalledWith({ key: 'referent', label: { de: 'Referent' }, permissions: [] });
    expect(inst.roles().some((r: Role) => r.id === 'r-new')).toBe(true);
    expect(inst.addOpen()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
  });

  it('createRole includes both labels when both set', async () => {
    const { inst, api } = await setup();
    inst.openAdd();
    inst.patchDraft('key', 'kasse');
    inst.patchDraft('labelDe', 'Kasse');
    inst.patchDraft('labelEn', 'Treasury');
    inst.createRole();
    expect(api.createRole).toHaveBeenCalledWith({
      key: 'kasse',
      label: { de: 'Kasse', en: 'Treasury' },
      permissions: [],
    });
  });

  it('createRole with no labels sends an empty label map', async () => {
    const { inst, api } = await setup();
    inst.openAdd();
    inst.patchDraft('key', 'bare');
    inst.createRole();
    expect(api.createRole).toHaveBeenCalledWith({ key: 'bare', label: {}, permissions: [] });
  });

  it('createRole error path shows an error toast and keeps dialog open', async () => {
    const api = makeApi({ createRole: jest.fn(() => throwError(() => new Error('x'))) });
    const { inst, toast } = await setup(api);
    inst.openAdd();
    inst.patchDraft('key', 'x');
    inst.createRole();
    expect(toast.error).toHaveBeenCalled();
    expect(inst.addOpen()).toBe(true);
  });

  it('askDelete + confirmDelete removes the role; no-op without target', async () => {
    const { inst, api, toast } = await setup();
    inst.confirmDelete(); // no target → no call
    expect(api.deleteRole).not.toHaveBeenCalled();

    inst.askDelete(ROLES[1]);
    expect(inst.confirmRole()).toEqual(ROLES[1]);
    inst.confirmDelete();
    expect(api.deleteRole).toHaveBeenCalledWith('r-member');
    expect(inst.roles().some((r: Role) => r.id === 'r-member')).toBe(false);
    expect(inst.confirmRole()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
  });

  it('confirmDelete error path shows an error toast', async () => {
    const api = makeApi({ deleteRole: jest.fn(() => throwError(() => new Error('x'))) });
    const { inst, toast } = await setup(api);
    inst.askDelete(ROLES[1]);
    inst.confirmDelete();
    expect(toast.error).toHaveBeenCalled();
  });
});
