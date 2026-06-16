import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@shared/ui';
import type { AdminPrincipal, Role, RoleAssignment } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { UsersComponent } from './users.component';

const ROLES: Role[] = [
  { id: 'r-admin', key: 'admin', label: { de: 'administrator', en: 'administrator' }, permissions: ['admin.roles'] },
  { id: 'r-member', key: 'member', label: { de: 'mitglied', en: 'member' }, permissions: ['application.read'] },
  { id: 'r-ref', key: 'referent', label: { en: 'officer' }, permissions: [] },
];

const ADMIN_ASSIGN: RoleAssignment = {
  id: 'a-1', principalId: 'p-1', roleId: 'r-admin', gremiumId: null,
  grantedBy: 'bootstrap', validFrom: null, validUntil: null, delegateVoting: false,
};
const SCOPED_ASSIGN: RoleAssignment = {
  id: 'a-2', principalId: 'p-1', roleId: 'r-ref', gremiumId: 'g-1',
  grantedBy: 'bootstrap', validFrom: null, validUntil: null, delegateVoting: false,
};

const PRINCIPALS: AdminPrincipal[] = [
  {
    id: 'p-1', sub: 'kc|alex', email: 'alex@x.de', displayName: 'Alex Admin',
    lastLogin: '2026-06-06T18:20:00+00:00',
    assignments: [ADMIN_ASSIGN, SCOPED_ASSIGN],
  },
  { id: 'p-3', sub: 'kc|sam', email: null, displayName: 'Sam Neu', lastLogin: null, assignments: [] },
];

function makeAuth(sub: string | null) {
  return { principal: () => (sub === null ? null : { sub }) } as unknown as AuthService;
}

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listRoles: jest.fn(() => of(ROLES.map((r) => ({ ...r })))),
    listPrincipals: jest.fn(() => of(PRINCIPALS.map((p) => ({ ...p, assignments: [...p.assignments] })))),
    assignRole: jest.fn(() => of({ id: 'a-new' })),
    revokeRole: jest.fn(() => of(void 0)),
    setPrincipalActive: jest.fn(() => of({ id: 'p-1', active: true })),
    ...over,
  };
}

function makeToast() {
  return { success: jest.fn(), error: jest.fn() };
}

async function setup(api = makeApi(), auth = makeAuth(null), toast = makeToast()) {
  const view = await render(UsersComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: auth },
      { provide: ToastService, useValue: toast },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const inst = view.fixture.componentInstance as any;
  return { ...view, api, toast, inst };
}

describe('UsersComponent (#70/#72/#73)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists principals and shows capitalized role tags (#73)', async () => {
    await setup();
    expect(screen.getByText('Alex Admin')).toBeInTheDocument();
    expect(screen.getAllByText('Administrator').length).toBeGreaterThan(0);
    expect(screen.queryByText('administrator')).not.toBeInTheDocument();
    expect(screen.getByText('Keine Rollen zugewiesen.')).toBeInTheDocument();
  });

  it('mySub is null without a logged-in principal', async () => {
    const { inst } = await setup();
    expect(inst.mySub()).toBeNull();
  });

  it('mySub is set when a principal is logged in', async () => {
    const { inst } = await setup(makeApi(), makeAuth('kc|alex'));
    expect(inst.mySub()).toBe('kc|alex');
  });

  it('globalAssignments filters out gremium-scoped assignments', async () => {
    const { inst } = await setup();
    expect(inst.globalAssignments(PRINCIPALS[0])).toEqual([ADMIN_ASSIGN]);
    expect(inst.globalAssignments(PRINCIPALS[1])).toEqual([]);
  });

  it('rowId + rowExpanded reflect the expanded set', async () => {
    const { inst } = await setup();
    expect(inst.rowId(PRINCIPALS[0])).toBe('p-1');
    expect(inst.rowExpanded(PRINCIPALS[0])).toBe(false);
    inst.toggleAssign('p-1');
    expect(inst.rowExpanded(PRINCIPALS[0])).toBe(true);
  });

  it('roleLabel resolves locale→de→key, raw id when unknown', async () => {
    const { inst } = await setup();
    expect(inst.roleLabel('r-admin')).toBe('administrator');
    expect(inst.roleLabel('unknown')).toBe('unknown');
    // r-ref has no de → key
    expect(inst.roleLabel('r-ref')).toBe('referent');
  });

  it('roleLabel uses en when locale en', async () => {
    localStorage.setItem('ap.locale', 'en');
    const { inst } = await setup();
    expect(inst.roleLabel('r-ref')).toBe('officer');
  });

  it('userLabel prefers displayName, then email, then sub', async () => {
    const { inst } = await setup();
    expect(inst.userLabel({ displayName: 'Name', email: 'e', sub: 's' })).toBe('Name');
    expect(inst.userLabel({ displayName: '', email: 'e@x', sub: 's' })).toBe('e@x');
    expect(inst.userLabel({ displayName: null, email: null, sub: 'sub-only' })).toBe('sub-only');
  });

  it('roleOptions exposes every role with a capitalized label', async () => {
    const { inst } = await setup();
    expect(inst.roleOptions()).toEqual([
      { value: 'r-admin', label: 'Administrator' },
      { value: 'r-member', label: 'Mitglied' },
      { value: 'r-ref', label: 'Referent' }, // r-ref has no de → key, capitalized
    ]);
  });

  it('isAdminRole protects admin + member only', async () => {
    const { inst } = await setup();
    expect(inst.isAdminRole('r-admin')).toBe(true);
    expect(inst.isAdminRole('r-member')).toBe(true);
    expect(inst.isAdminRole('r-ref')).toBe(false);
    expect(inst.isAdminRole('unknown')).toBe(false);
  });

  it('isSelf is true only when sub matches the logged-in sub', async () => {
    const { inst } = await setup(makeApi(), makeAuth('kc|alex'));
    expect(inst.isSelf(PRINCIPALS[0])).toBe(true);
    expect(inst.isSelf(PRINCIPALS[1])).toBe(false);
  });

  it('isSelf is false when there is no logged-in principal', async () => {
    const { inst } = await setup();
    expect(inst.isSelf(PRINCIPALS[0])).toBe(false);
  });

  it('toggleAssign + isExpanded toggle a row open and closed', async () => {
    const { inst } = await setup();
    expect(inst.isExpanded('p-1')).toBe(false);
    inst.toggleAssign('p-1');
    expect(inst.isExpanded('p-1')).toBe(true);
    inst.toggleAssign('p-1');
    expect(inst.isExpanded('p-1')).toBe(false);
  });

  it('draftFor returns an empty draft by default and patchDraft merges', async () => {
    const { inst } = await setup();
    expect(inst.draftFor('p-3')).toEqual({ roleId: '', validFrom: '', validUntil: '' });
    inst.patchDraft('p-3', { roleId: 'r-member' });
    expect(inst.draftFor('p-3')).toEqual({ roleId: 'r-member', validFrom: '', validUntil: '' });
    inst.patchDraft('p-3', { validFrom: '2026-07-01' });
    expect(inst.draftFor('p-3')).toEqual({ roleId: 'r-member', validFrom: '2026-07-01', validUntil: '' });
  });

  it('searches by query', async () => {
    const { api } = await setup();
    await userEvent.type(screen.getByRole('searchbox', { name: 'Benutzer suchen' }), 'alex');
    await userEvent.click(screen.getByRole('button', { name: 'Suchen' }));
    expect(api.listPrincipals).toHaveBeenLastCalledWith('alex');
  });

  it('search error path shows an error toast', async () => {
    const api = makeApi({ listPrincipals: jest.fn(() => throwError(() => new Error('x'))) });
    const { toast } = await setup(api);
    expect(toast.error).toHaveBeenCalled();
  });

  it('does not assign without a role selected', async () => {
    const { api, inst } = await setup();
    inst.assign(PRINCIPALS[1]);
    expect(api.assignRole).not.toHaveBeenCalled();
  });

  it('assigns a role with optional validity window and resets state (#72)', async () => {
    const { api, inst } = await setup();
    inst.toggleAssign('p-3'); // expand it first
    inst.patchDraft('p-3', { roleId: 'r-member', validFrom: '2026-07-01', validUntil: '2026-12-31' });
    inst.assign(PRINCIPALS[1]);
    expect(api.assignRole).toHaveBeenCalledWith({
      principalId: 'p-3',
      roleId: 'r-member',
      gremiumId: null,
      validFrom: '2026-07-01T00:00:00Z',
      validUntil: '2026-12-31T00:00:00Z',
    });
    // draft reset + row collapsed + reloaded
    expect(inst.draftFor('p-3')).toEqual({ roleId: '', validFrom: '', validUntil: '' });
    expect(inst.isExpanded('p-3')).toBe(false);
    expect(api.listPrincipals).toHaveBeenCalledTimes(2);
  });

  it('assigns with empty validity → null dates (isoOrNull empty branch)', async () => {
    const { api, inst, toast } = await setup();
    inst.patchDraft('p-3', { roleId: 'r-member' });
    inst.assign(PRINCIPALS[1]);
    expect(api.assignRole).toHaveBeenCalledWith({
      principalId: 'p-3',
      roleId: 'r-member',
      gremiumId: null,
      validFrom: null,
      validUntil: null,
    });
    expect(toast.success).toHaveBeenCalled();
  });

  it('assigns passing through a full ISO datetime unchanged (isoOrNull non-10 branch)', async () => {
    const { api, inst } = await setup();
    inst.patchDraft('p-3', { roleId: 'r-member', validFrom: '2026-07-01T08:00:00Z' });
    inst.assign(PRINCIPALS[1]);
    expect(api.assignRole).toHaveBeenCalledWith(
      expect.objectContaining({ validFrom: '2026-07-01T08:00:00Z', validUntil: null }),
    );
  });

  it('assign error path shows an error toast', async () => {
    const api = makeApi({ assignRole: jest.fn(() => throwError(() => new Error('x'))) });
    const { inst, toast } = await setup(api);
    inst.patchDraft('p-3', { roleId: 'r-member' });
    inst.assign(PRINCIPALS[1]);
    expect(toast.error).toHaveBeenCalled();
  });

  it('setActive activates and deactivates with the matching toast', async () => {
    const { api, inst, toast } = await setup();
    inst.setActive(PRINCIPALS[0], true);
    expect(api.setPrincipalActive).toHaveBeenCalledWith('p-1', true);
    inst.setActive(PRINCIPALS[0], false);
    expect(api.setPrincipalActive).toHaveBeenCalledWith('p-1', false);
    expect(toast.success).toHaveBeenCalledTimes(2);
  });

  it('setActive error path shows an error toast', async () => {
    const api = makeApi({ setPrincipalActive: jest.fn(() => throwError(() => new Error('x'))) });
    const { inst, toast } = await setup(api);
    inst.setActive(PRINCIPALS[0], true);
    expect(toast.error).toHaveBeenCalled();
  });

  it('revokes a role (#72)', async () => {
    const { api, inst, toast } = await setup();
    inst.revoke(ADMIN_ASSIGN);
    expect(api.revokeRole).toHaveBeenCalledWith('a-1');
    expect(toast.success).toHaveBeenCalled();
  });

  it('revoke error path shows an error toast', async () => {
    const api = makeApi({ revokeRole: jest.fn(() => throwError(() => new Error('x'))) });
    const { inst, toast } = await setup(api);
    inst.revoke(ADMIN_ASSIGN);
    expect(toast.error).toHaveBeenCalled();
  });

  it('renders the principals as a table without the oidc-subject column', async () => {
    await setup();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'OIDC-Subject' })).not.toBeInTheDocument();
  });
});
