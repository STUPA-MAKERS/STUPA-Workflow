import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import type { AdminPrincipal, Role } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { UsersComponent } from './users.component';

const authStub = { principal: () => null } as unknown as AuthService;

const ROLES: Role[] = [
  { id: 'r-admin', key: 'admin', label: { de: 'administrator', en: 'administrator' }, permissions: ['admin.roles'] },
  { id: 'r-member', key: 'member', label: { de: 'mitglied', en: 'member' }, permissions: ['application.read'] },
];

const PRINCIPALS: AdminPrincipal[] = [
  {
    id: 'p-1',
    sub: 'kc|alex',
    email: 'alex@x.de',
    displayName: 'Alex Admin',
    lastLogin: '2026-06-06T18:20:00+00:00',
    assignments: [
      { id: 'a-1', principalId: 'p-1', roleId: 'r-admin', gremiumId: null, grantedBy: 'bootstrap', validFrom: null, validUntil: null, delegateVoting: false },
    ],
  },
  { id: 'p-3', sub: 'kc|sam', email: null, displayName: 'Sam Neu', lastLogin: null, assignments: [] },
];

function makeApi(over: Partial<Record<keyof AdminApiService, unknown>> = {}) {
  return {
    listRoles: jest.fn(() => of(ROLES)),
    listPermissions: jest.fn(() => of(['admin.roles', 'application.read', 'flow.configure'])),
    listPrincipals: jest.fn(() => of(PRINCIPALS)),
    listGremienOptions: jest.fn(() => of([{ id: 'g-1', name: 'StuPa' }])),
    assignRole: jest.fn(() => of({ id: 'a-new' })),
    revokeRole: jest.fn(() => of(void 0)),
    saveRolePermissions: jest.fn((id: string, perms: string[]) => of({ ...ROLES[0], id, permissions: perms })),
    ...over,
  };
}

async function setup(api = makeApi()) {
  const view = await render(UsersComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: authStub },
    ],
  });
  return { ...view, api };
}

describe('UsersComponent (#70/#72/#73)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists principals and shows capitalized role tags (#73)', async () => {
    await setup();
    expect(screen.getByText('Alex Admin')).toBeInTheDocument();
    // label "administrator" → capitalized "Administrator" for display, value unchanged
    expect(screen.getAllByText('Administrator').length).toBeGreaterThan(0);
    expect(screen.queryByText('administrator')).not.toBeInTheDocument();
    expect(screen.getByText('Keine Rollen zugewiesen.')).toBeInTheDocument();
  });

  it('searches by query', async () => {
    const { api } = await setup();
    await userEvent.type(screen.getByRole('searchbox', { name: 'Benutzer suchen' }), 'alex');
    await userEvent.click(screen.getByRole('button', { name: 'Suchen' }));
    expect(api.listPrincipals).toHaveBeenLastCalledWith('alex');
  });

  it('assigns a role with optional validity window (#72)', async () => {
    const { api, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const inst = fixture.componentInstance as any;
    inst.patchDraft('p-3', { roleId: 'r-member', validFrom: '2026-07-01', validUntil: '2026-12-31' });
    inst.assign(PRINCIPALS[1]);
    expect(api.assignRole).toHaveBeenCalledWith({
      principalId: 'p-3',
      roleId: 'r-member',
      gremiumId: null,
      validFrom: '2026-07-01T00:00:00Z',
      validUntil: '2026-12-31T00:00:00Z',
    });
  });

  it('does not assign without a role selected', async () => {
    const { api, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const inst = fixture.componentInstance as any;
    inst.assign(PRINCIPALS[1]);
    expect(api.assignRole).not.toHaveBeenCalled();
  });

  it('revokes a role (#72)', async () => {
    const { api, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const inst = fixture.componentInstance as any;
    inst.revoke(PRINCIPALS[0].assignments[0]);
    expect(api.revokeRole).toHaveBeenCalledWith('a-1');
  });

  it('renders the principals as a table', async () => {
    await setup();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'OIDC-Subject' })).toBeInTheDocument();
  });
});
