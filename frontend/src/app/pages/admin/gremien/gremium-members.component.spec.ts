import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { provideRouter } from '@angular/router';
import type { AdminPrincipal, Gremium, Role } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { GremiumMembersComponent } from './gremium-members.component';

const GREMIUM: Gremium = {
  id: 'g-1',
  name: 'StuPa',
  slug: 'stupa',
  cdVariant: 'stupa',
  defaultLang: 'de',
  allowVoteDelegation: false,
};
const ROLES: Role[] = [{ id: 'r-member', key: 'member', label: { de: 'mitglied', en: 'member' }, permissions: [] }];
const PRINCIPALS: AdminPrincipal[] = [
  {
    id: 'p-1',
    sub: 'kc|alex',
    email: 'alex@x.de',
    displayName: 'Alex',
    lastLogin: null,
    assignments: [
      { id: 'a-1', principalId: 'p-1', roleId: 'r-member', gremiumId: 'g-1', delegateVoting: false },
    ],
  },
  { id: 'p-2', sub: 'kc|sam', email: 'sam@x.de', displayName: 'Sam', lastLogin: null, assignments: [] },
];

function makeApi() {
  return {
    listGremien: jest.fn(() => of([GREMIUM])),
    listRoles: jest.fn(() => of(ROLES)),
    listPrincipals: jest.fn(() => of(PRINCIPALS)),
    assignRole: jest.fn(() => of({ id: 'a-new' })),
    revokeRole: jest.fn(() => of(void 0)),
  };
}

async function setup(api = makeApi()) {
  const view = await render(GremiumMembersComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => 'g-1' } } } },
    ],
  });
  return { ...view, api };
}

describe('GremiumMembersComponent (#18)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the members assigned to this committee', async () => {
    await setup();
    expect(await screen.findByText('Alex')).toBeInTheDocument();
    // Sam hat keine Zuweisung in g-1 → nicht als Mitglied gelistet.
    expect(screen.queryByText('Sam')).not.toBeInTheDocument();
  });

  it('adds a member via typeahead pick + role', async () => {
    const { api, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openAdd();
    c.onSearch('sam');
    c.pick(PRINCIPALS[1]);
    c.addRoleId.set('r-member');
    c.addMember();
    expect(api.assignRole).toHaveBeenCalledWith(
      expect.objectContaining({ principalId: 'p-2', roleId: 'r-member', gremiumId: 'g-1' }),
    );
  });
});
