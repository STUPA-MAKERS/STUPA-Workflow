import { of, throwError } from 'rxjs';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import type { AdminPrincipal, Role, RoleAssignment } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { UsersComponent } from './users.component';

const ROLES: Role[] = [
  {
    id: 'r-admin',
    key: 'admin',
    label: { de: 'administrator', en: 'administrator' },
    permissions: ['admin.roles'],
  },
  {
    id: 'r-member',
    key: 'member',
    label: { de: 'mitglied', en: 'member' },
    permissions: ['application.read'],
  },
  { id: 'r-ref', key: 'referent', label: { en: 'officer' }, permissions: [] },
];

const ADMIN_ASSIGN: RoleAssignment = {
  id: 'a-1',
  principalId: 'p-1',
  roleId: 'r-admin',
  gremiumId: null,
  grantedBy: 'bootstrap',
  validFrom: null,
  validUntil: null,
  delegateVoting: false,
};
const SCOPED_ASSIGN: RoleAssignment = {
  id: 'a-2',
  principalId: 'p-1',
  roleId: 'r-ref',
  gremiumId: 'g-1',
  grantedBy: 'bootstrap',
  validFrom: null,
  validUntil: null,
  delegateVoting: false,
};

const PRINCIPALS: AdminPrincipal[] = [
  {
    id: 'p-1',
    sub: 'kc|alex',
    email: 'alex@x.de',
    displayName: 'Alex Admin',
    lastLogin: '2026-06-06T18:20:00+00:00',
    assignments: [ADMIN_ASSIGN, SCOPED_ASSIGN],
  },
  {
    id: 'p-3',
    sub: 'kc|sam',
    email: null,
    displayName: 'Sam Neu',
    lastLogin: null,
    assignments: [],
  },
];

function makeAuth(sub: string | null, canManage = true) {
  return {
    principal: () => (sub === null ? null : { sub }),
    can: (p: string) => canManage && p === 'admin.users',
  } as unknown as AuthService;
}

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listRoles: jest.fn(() => of(ROLES.map((r) => ({ ...r })))),
    listPrincipals: jest.fn(() =>
      of(PRINCIPALS.map((p) => ({ ...p, assignments: [...p.assignments] }))),
    ),
    assignRole: jest.fn(() => of({ id: 'a-new' })),
    revokeRole: jest.fn(() => of(void 0)),
    setPrincipalActive: jest.fn(() => of({ id: 'p-1', active: true })),
    ...over,
  };
}

function makeToast() {
  return { success: jest.fn(), error: jest.fn() };
}

async function setup(
  api = makeApi(),
  auth = makeAuth(null),
  toast = makeToast(),
  queryParams: Record<string, string> = {},
) {
  const view = await render(UsersComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: auth },
      { provide: ToastService, useValue: toast },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { queryParamMap: convertToParamMap(queryParams) },
          queryParamMap: of(convertToParamMap(queryParams)),
        },
      },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const inst = view.fixture.componentInstance as any;
  return { ...view, api, toast, inst };
}

describe('UsersComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('searches for the person the URL names', async () => {
    // Where a global-search hit on a person lands. A bare `/admin/users` would open the
    // unfiltered list and leave the reader to search the same name a second time.
    const api = makeApi();
    const { inst } = await setup(api, makeAuth(null), makeToast(), { q: 'kc|alex' });
    expect(api.listPrincipals).toHaveBeenCalledWith('kc|alex');
    expect(inst.query()).toBe('kc|alex');
  });

  it('lists principals and shows capitalized role tags', async () => {
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
    // r-ref has no German label, so the key is the fallback.
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
      { value: 'r-ref', label: 'Referent' }, // no German label, so the capitalized key wins
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
    expect(inst.draftFor('p-3')).toEqual({
      roleId: 'r-member',
      validFrom: '2026-07-01',
      validUntil: '',
    });
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

  it('assigns a role with optional validity window and resets state', async () => {
    const { api, inst } = await setup();
    inst.toggleAssign('p-3');
    inst.patchDraft('p-3', {
      roleId: 'r-member',
      validFrom: '2026-07-01',
      validUntil: '2026-12-31',
    });
    inst.assign(PRINCIPALS[1]);
    expect(api.assignRole).toHaveBeenCalledWith({
      principalId: 'p-3',
      roleId: 'r-member',
      gremiumId: null,
      validFrom: '2026-07-01T00:00:00Z',
      validUntil: '2026-12-31T00:00:00Z',
    });
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

  it('revokes a role', async () => {
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

  describe('edit a role assignment', () => {
    it('offers the edit control only with admin.users', async () => {
      await setup(makeApi(), makeAuth(null, false));
      expect(
        screen.queryByRole('button', { name: /Zuweisung bearbeiten/ }),
      ).not.toBeInTheDocument();
    });

    it('shows an edit control per assigned role', async () => {
      await setup();
      expect(
        screen.getAllByRole('button', { name: /Zuweisung bearbeiten/ }).length,
      ).toBeGreaterThan(0);
    });

    it('prefills the dialog from the assignment and cuts the date to YYYY-MM-DD', async () => {
      const { inst } = await setup();
      inst.openEdit({ ...ADMIN_ASSIGN, validUntil: '2026-12-31T00:00:00Z' });
      expect(inst.editDraft()).toEqual({
        roleId: 'r-admin',
        validFrom: '',
        validUntil: '2026-12-31',
      });
      inst.closeEdit();
      expect(inst.editing()).toBeNull();
    });

    it('sends only the changed fields and reloads the list', async () => {
      const api = makeApi({
        updateRoleAssignment: jest.fn(() => of({ ...ADMIN_ASSIGN, roleId: 'r-ref' })),
      });
      const { inst, toast } = await setup(api);
      inst.openEdit(ADMIN_ASSIGN);
      inst.patchEdit({ roleId: 'r-ref', validUntil: '2026-12-31' });
      inst.saveEdit();
      expect(api.updateRoleAssignment).toHaveBeenCalledWith('a-1', {
        roleId: 'r-ref',
        validUntil: '2026-12-31T00:00:00Z',
      });
      expect(toast.success).toHaveBeenCalledWith('Zuweisung aktualisiert.');
      expect(inst.editing()).toBeNull();
      // The list reloads: once on init and once after the save.
      expect(api.listPrincipals).toHaveBeenCalledTimes(2);
    });

    it('keeps an already set expiry when the field is cleared', async () => {
      const api = makeApi({ updateRoleAssignment: jest.fn(() => of(ADMIN_ASSIGN)) });
      const { inst } = await setup(api);
      inst.openEdit({ ...ADMIN_ASSIGN, validUntil: '2026-12-31T00:00:00Z' });
      inst.patchEdit({ roleId: 'r-ref', validUntil: '' });
      inst.saveEdit();
      // No `validUntil` in the body: the route reads null as "do not touch",
      // so sending it would be a silent no-op instead of a clear.
      expect(api.updateRoleAssignment).toHaveBeenCalledWith('a-1', { roleId: 'r-ref' });
    });

    it('closes without a request when nothing changed', async () => {
      const api = makeApi({ updateRoleAssignment: jest.fn(() => of(ADMIN_ASSIGN)) });
      const { inst } = await setup(api);
      inst.openEdit(ADMIN_ASSIGN);
      inst.saveEdit();
      expect(api.updateRoleAssignment).not.toHaveBeenCalled();
      expect(inst.editing()).toBeNull();
    });

    it.each([
      [403, 'Die eigene Admin-Zuweisung lässt sich nicht ändern.'],
      [500, 'Zuweisung konnte nicht geändert werden.'],
    ])('explains a %s answer', async (status, message) => {
      const api = makeApi({
        updateRoleAssignment: jest.fn(() => throwError(() => ({ status }))),
      });
      const { inst, toast } = await setup(api);
      inst.openEdit(ADMIN_ASSIGN);
      inst.patchEdit({ roleId: 'r-ref' });
      inst.saveEdit();
      expect(toast.error).toHaveBeenCalledWith(message);
      expect(inst.savingEdit()).toBe(false);
    });

    it('ignores a save without a target, without a role, or while one runs', async () => {
      const api = makeApi({ updateRoleAssignment: jest.fn(() => of(ADMIN_ASSIGN)) });
      const { inst } = await setup(api);
      inst.saveEdit();
      inst.openEdit(ADMIN_ASSIGN);
      inst.patchEdit({ roleId: '' });
      inst.saveEdit();
      inst.patchEdit({ roleId: 'r-ref' });
      inst.savingEdit.set(true);
      inst.saveEdit();
      expect(api.updateRoleAssignment).not.toHaveBeenCalled();
    });
  });
});
