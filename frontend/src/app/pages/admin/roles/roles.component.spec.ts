import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import type { Role } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { AdminRolesComponent } from './roles.component';

const ROLES: Role[] = [
  { id: 'r-admin', key: 'admin', label: { de: 'administrator', en: 'administrator' }, permissions: ['admin.roles'] },
  { id: 'r-member', key: 'member', label: { de: 'mitglied', en: 'member' }, permissions: ['application.read'] },
];

function makeApi() {
  return {
    listRoles: jest.fn(() => of(ROLES)),
    listPermissions: jest.fn(() => of(['admin.roles', 'application.read', 'flow.configure'])),
    saveRolePermissions: jest.fn((id: string, perms: string[]) => of({ ...ROLES[0], id, permissions: perms })),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    createRole: jest.fn((body: any) => of({ id: 'r-new', key: body.key, label: body.label, permissions: [] })),
    deleteRole: jest.fn(() => of(void 0)),
  };
}

async function setup(api = makeApi()) {
  const view = await render(AdminRolesComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
  });
  return { ...view, api };
}

describe('AdminRolesComponent (#12)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists roles with capitalized labels', async () => {
    await setup();
    expect(screen.getAllByText('Administrator').length).toBeGreaterThan(0);
    expect(screen.getByText('admin')).toBeInTheDocument();
  });

  it('toggles and saves permissions per role', async () => {
    const { api, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const inst = fixture.componentInstance as any;
    inst.togglePerm(ROLES[1], 'flow.configure', true);
    const role = inst.roles().find((r: Role) => r.id === 'r-member');
    expect(role.permissions).toContain('flow.configure');
    inst.togglePerm(role, 'application.read', false);
    inst.saveRole(inst.roles().find((r: Role) => r.id === 'r-member'));
    expect(api.saveRolePermissions).toHaveBeenCalledWith('r-member', ['flow.configure']);
  });

  it('creates a global role via the add dialog', async () => {
    const { api, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const inst = fixture.componentInstance as any;
    inst.openAdd();
    inst.patchDraft('key', 'referent');
    inst.patchDraft('labelDe', 'Referent');
    inst.createRole();
    expect(api.createRole).toHaveBeenCalledWith({
      key: 'referent',
      label: { de: 'Referent' },
      permissions: [],
    });
    expect(inst.roles().some((r: Role) => r.id === 'r-new')).toBe(true);
  });

  it('deletes custom roles but protects admin/member (#38)', async () => {
    const { api, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const inst = fixture.componentInstance as any;
    expect(inst.canDelete(ROLES[0])).toBe(false); // admin
    expect(inst.canDelete({ key: 'member' })).toBe(false);
    expect(inst.canDelete({ key: 'referent' })).toBe(true);
    // Löschen via Bestätigungs-Dialog (#40).
    inst.askDelete(ROLES[1]); // r-member id but deletable in the test path
    inst.confirmDelete();
    expect(api.deleteRole).toHaveBeenCalledWith('r-member');
    expect(inst.roles().some((r: Role) => r.id === 'r-member')).toBe(false);
  });
});
