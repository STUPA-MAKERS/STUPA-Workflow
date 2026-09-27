import { of, throwError } from 'rxjs';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import type { AdminPrincipal, GroupMapping, Role, RoleAssignment } from '../admin.models';
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
    oidcGroups: ['stupa-referat', 'vote:g-1', 'unmapped'],
  },
  {
    id: 'p-3',
    sub: 'kc|sam',
    email: null,
    displayName: 'Sam Neu',
    lastLogin: null,
    assignments: [],
    oidcGroups: [],
  },
];

const MAPPINGS: GroupMapping[] = [
  { id: 'gm-1', oidcGroup: 'stupa-referat', roleId: 'r-ref', gremiumId: null },
  // The same role as the bootstrap assignment. The column shows it once.
  { id: 'gm-2', oidcGroup: 'stupa-referat', roleId: 'r-admin', gremiumId: null },
  // A reserved group never gives a role, not even through a mapping.
  { id: 'gm-3', oidcGroup: 'vote:g-1', roleId: 'r-member', gremiumId: null },
];

function makeAuth(sub: string | null, canMappings = true) {
  return {
    principal: () => (sub === null ? null : { sub }),
    can: (p: string) => p === 'admin.users' || (canMappings && p === 'admin.group_mappings'),
  } as unknown as AuthService;
}

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listRoles: jest.fn(() => of(ROLES.map((r) => ({ ...r })))),
    listPrincipals: jest.fn(() =>
      of(PRINCIPALS.map((p) => ({ ...p, assignments: [...p.assignments] }))),
    ),
    listGroupMappings: jest.fn(() => of(MAPPINGS.map((m) => ({ ...m })))),
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
      provideRouter([]),
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

  it('lists principals with capitalized, read-only role tags', async () => {
    await setup();
    expect(screen.getByText('Alex Admin')).toBeInTheDocument();
    expect(screen.getAllByText('Administrator').length).toBeGreaterThan(0);
    expect(screen.getByText('Referent')).toBeInTheDocument();
    expect(screen.queryByText('administrator')).not.toBeInTheDocument();
    expect(screen.getByText('Keine Rollen zugewiesen.')).toBeInTheDocument();
    // No role editing is left: no assign, edit or revoke control.
    expect(screen.queryByRole('button', { name: /Entziehen|Zuweisung|Rolle \+/ })).toBeNull();
  });

  it('shows the OIDC groups of each user, or a placeholder', async () => {
    await setup();
    expect(screen.getByRole('columnheader', { name: 'OIDC-Gruppen' })).toBeInTheDocument();
    expect(screen.getByText('stupa-referat')).toBeInTheDocument();
    expect(screen.getByText('unmapped')).toBeInTheDocument();
    expect(screen.getByText('Keine Gruppen.')).toBeInTheDocument();
  });

  it('roleIds merges the global bootstrap roles with the mapped roles', async () => {
    const { inst } = await setup();
    // The scoped assignment is left out, the admin role appears once, the vote: group
    // gives nothing.
    expect(inst.roleIds(PRINCIPALS[0])).toEqual(['r-admin', 'r-ref']);
    expect(inst.roleIds(PRINCIPALS[1])).toEqual([]);
  });

  it('shows the hint with a link to the group mappings when permitted', async () => {
    await setup();
    expect(
      screen.getByText(/Die Rollen kommen aus den OIDC-Gruppen/),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Gruppen-Mappings verwalten' })).toHaveAttribute(
      'href',
      '/admin/group-mappings',
    );
  });

  it('without admin.group_mappings: no link and no mapping request', async () => {
    const api = makeApi();
    const { inst } = await setup(api, makeAuth(null, false));
    expect(api.listGroupMappings).not.toHaveBeenCalled();
    expect(screen.queryByRole('link', { name: 'Gruppen-Mappings verwalten' })).toBeNull();
    expect(inst.roleIds(PRINCIPALS[0])).toEqual(['r-admin']);
  });

  it('a failed mapping load falls back to the bootstrap roles', async () => {
    const api = makeApi({ listGroupMappings: jest.fn(() => throwError(() => new Error('x'))) });
    const { inst } = await setup(api);
    expect(inst.roleIds(PRINCIPALS[0])).toEqual(['r-admin']);
  });

  it('mySub is null without a logged-in principal', async () => {
    const { inst } = await setup();
    expect(inst.mySub()).toBeNull();
  });

  it('mySub is set when a principal is logged in', async () => {
    const { inst } = await setup(makeApi(), makeAuth('kc|alex'));
    expect(inst.mySub()).toBe('kc|alex');
  });

  it('rowId exposes the principal id', async () => {
    const { inst } = await setup();
    expect(inst.rowId(PRINCIPALS[0])).toBe('p-1');
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

  it('isSelf is true only when sub matches the logged-in sub', async () => {
    const { inst } = await setup(makeApi(), makeAuth('kc|alex'));
    expect(inst.isSelf(PRINCIPALS[0])).toBe(true);
    expect(inst.isSelf(PRINCIPALS[1])).toBe(false);
  });

  it('isSelf is false when there is no logged-in principal', async () => {
    const { inst } = await setup();
    expect(inst.isSelf(PRINCIPALS[0])).toBe(false);
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

  it('renders the principals as a table without the oidc-subject column', async () => {
    await setup();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'OIDC-Subject' })).not.toBeInTheDocument();
  });
});
