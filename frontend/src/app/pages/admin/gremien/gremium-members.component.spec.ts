import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { provideRouter } from '@angular/router';
import type { AdminPrincipal, GremiumMembership, GremiumRole } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { GremiumMembersComponent } from './gremium-members.component';

const ROLES: GremiumRole[] = [
  { id: 'gr-1', gremiumId: 'g-1', key: 'vorsitz', name: { de: 'Vorsitz', en: 'Chair' } },
];
const PRINCIPALS: AdminPrincipal[] = [
  { id: 'p-1', sub: 'kc|alex', email: 'alex@x.de', displayName: 'Alex', lastLogin: null, assignments: [] },
  { id: 'p-2', sub: 'kc|sam', email: 'sam@x.de', displayName: 'Sam', lastLogin: null, assignments: [] },
];
const MEMBERSHIPS: GremiumMembership[] = [
  { id: 'm-1', principalId: 'p-1', gremiumId: 'g-1', gremiumRoleId: 'gr-1', validFrom: null, validUntil: null },
];

function makeApi() {
  return {
    listGremien: jest.fn(() => of([{ id: 'g-1', name: 'StuPa', slug: 'stupa', cdVariant: 'stupa', defaultLang: 'de', allowVoteDelegation: false }])),
    listGremiumRoles: jest.fn(() => of(ROLES)),
    listPrincipals: jest.fn(() => of(PRINCIPALS)),
    listGremiumMemberships: jest.fn(() => of(MEMBERSHIPS)),
    createGremiumMembership: jest.fn(() => of({ id: 'm-new' })),
    deleteGremiumMembership: jest.fn(() => of(void 0)),
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

describe('GremiumMembersComponent (#18/#62)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists this committee’s memberships', async () => {
    await setup();
    expect(await screen.findByText('Alex')).toBeInTheDocument();
    expect(screen.getByText('Vorsitz')).toBeInTheDocument();
  });

  it('adds a membership via typeahead pick + gremium role + term', async () => {
    const { api, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openAdd();
    c.onSearch('sam');
    c.pick(PRINCIPALS[1]);
    c.addRoleId.set('gr-1');
    c.addFrom.set('2026-01-01');
    c.addMember();
    expect(api.createGremiumMembership).toHaveBeenCalledWith(
      'g-1',
      expect.objectContaining({ principalId: 'p-2', gremiumRoleId: 'gr-1', validFrom: '2026-01-01' }),
    );
  });

  it('removes a membership', async () => {
    const { api, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.removeMember('m-1');
    expect(api.deleteGremiumMembership).toHaveBeenCalledWith('m-1');
  });
});
