import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { DelegationsApiService } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { of, throwError } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import type { GremiumMembership, GremiumRole } from '../admin.models';
import { GremiumMembersComponent, MEMBER_PREVIEW } from './gremium-members.component';

const ROLES: GremiumRole[] = [
  { id: 'r-v', gremiumId: 'g-1', key: 'vorstand', name: { de: 'Vorstand' }, forced: true },
  { id: 'r-m', gremiumId: 'g-1', key: 'manager', name: { de: 'Manager' }, forced: true },
  { id: 'r-p', gremiumId: 'g-1', key: 'protokoll', name: { en: 'Minutes' } },
  { id: 'r-x', gremiumId: 'g-1', key: 'member', name: { de: 'Mitglied' }, forced: true },
];

function member(
  id: string,
  name: string | null,
  role: string,
  email: string | null = `${id}@x.de`,
): GremiumMembership {
  return {
    id: `m-${id}`,
    principalId: id,
    gremiumId: 'g-1',
    gremiumRoleId: role,
    displayName: name,
    email,
  };
}

const MEMBERS: GremiumMembership[] = [
  member('p-1', 'Zoe', 'r-x'),
  member('p-2', 'Anna', 'r-x'),
  member('p-3', 'Mara', 'r-v'),
  member('p-4', null, 'r-p'),
  member('p-5', 'Jonas', 'r-m'),
  member('p-6', null, 'r-gone', null),
];

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listGremienOptions: jest.fn(() => of([{ id: 'g-1', name: 'Studierendenparlament' }])),
    listGremiumRoles: jest.fn(() => of([...ROLES])),
    listGremiumMemberships: jest.fn(() => of([...MEMBERS])),
    listPrincipals: jest.fn(() => of([])),
    ...over,
  };
}

async function setup(
  opts: { api?: ReturnType<typeof makeApi>; perms?: string[]; pools?: string[] } = {},
) {
  const api = opts.api ?? makeApi();
  const perms = opts.perms ?? ['admin.gremien', 'admin.group_mappings'];
  const pools = opts.pools ?? [];
  const delegations = {
    substitutes: jest.fn(() => of([])),
    addSubstitute: jest.fn(),
    removeSubstitute: jest.fn(),
  };
  const view = await render(GremiumMembersComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: DelegationsApiService, useValue: delegations },
      { provide: ToastService, useValue: { success: jest.fn(), error: jest.fn() } },
      {
        provide: AuthService,
        useValue: {
          can: (p: string) => perms.includes(p),
          canInGremium: (_g: string, p: string) => pools.includes(p),
        },
      },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: convertToParamMap({ id: 'g-1' }) } },
      },
    ],
  });
  // NgModel writes its value after a microtask.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, delegations };
}

const names = () =>
  within(screen.getByRole('list', { name: 'Mitglieder' }))
    .getAllByRole('listitem')
    .map((li) => li.querySelector('.gmm__name')?.textContent?.trim());

describe('GremiumMembersComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('names the gremium and the member count and links to the group mappings', async () => {
    await setup();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Mitglieder: Studierendenparlament',
    );
    expect(screen.getByText('6 Mitglieder')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Gruppen-Zuordnung' })).toHaveAttribute(
      'href',
      '/admin/group-mappings',
    );
  });

  it('lists the members read-only, sorted by role and then by name', async () => {
    await setup();
    // Board, manager, own roles, member; a member without a name or e-mail says so.
    expect(names()).toEqual(['Mara', 'Jonas', 'p-4@x.de', 'Anna', 'Zoe', '(ohne Namen)']);
    const list = screen.getByRole('list', { name: 'Mitglieder' });
    expect(within(list).getAllByText('Mitglied')).toHaveLength(2);
    // The role without a German name falls back to its key; an unknown role is a dash.
    expect(within(list).getByText('Protokoll')).toBeInTheDocument();
    expect(within(list).getAllByText('—')).toHaveLength(2);
    // Read-only: no control on a member row.
    expect(within(list).queryAllByRole('button')).toHaveLength(0);
  });

  it('shows the first rows and all of them on request', async () => {
    const many = Array.from({ length: MEMBER_PREVIEW + 2 }, (_, i) =>
      member(`q-${i}`, `Person ${String(i).padStart(2, '0')}`, 'r-x'),
    );
    await setup({ api: makeApi({ listGremiumMemberships: jest.fn(() => of(many)) }) });
    expect(names()).toHaveLength(MEMBER_PREVIEW);
    expect(screen.getByText(`${MEMBER_PREVIEW} von ${MEMBER_PREVIEW + 2}`)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: `Alle ${MEMBER_PREVIEW + 2} anzeigen` }),
    );
    expect(names()).toHaveLength(MEMBER_PREVIEW + 2);
    await userEvent.click(screen.getByRole('button', { name: 'Weniger anzeigen' }));
    expect(names()).toHaveLength(MEMBER_PREVIEW);
  });

  it('hides the mappings link and the pool without their permissions', async () => {
    const { delegations } = await setup({ perms: ['admin.gremien'] });
    expect(screen.queryByRole('link', { name: 'Gruppen-Zuordnung' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Stellvertretungen' })).toBeNull();
    expect(delegations.substitutes).not.toHaveBeenCalled();
  });

  it('shows the pool with admin.delegations or with session.manage in the gremium', async () => {
    const { delegations: delegations0, api: api0 } = await setup({
      perms: ['admin.gremien', 'admin.delegations'],
    });
    expect(screen.getByRole('heading', { name: 'Stellvertretungen' })).toBeInTheDocument();
    expect(delegations0.substitutes).toHaveBeenCalledWith('g-1');
    // The page passes its members: the pool loads none itself.
    expect(api0.listGremiumMemberships).toHaveBeenCalledTimes(1);
  });

  it('shows the pool with admin.delegations or with session.manage in the gremium (2)', async () => {
    await setup({ perms: ['admin.gremien'], pools: ['session.manage'] });
    expect(screen.getByRole('heading', { name: 'Stellvertretungen' })).toBeInTheDocument();
  });

  it('names a failed load and never shows an empty list for it', async () => {
    await setup({
      api: makeApi({ listGremiumMemberships: jest.fn(() => throwError(() => ({ status: 403 }))) }),
    });
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Die Mitglieder konnten nicht geladen werden.',
    );
    expect(screen.queryByText('Noch keine Mitglieder in diesem Gremium.')).toBeNull();
    expect(screen.queryByText(/\d Mitglieder$/)).toBeNull();
  });

  it('says so for a gremium without members and survives failed side reads', async () => {
    await setup({
      api: makeApi({
        listGremiumMemberships: jest.fn(() => of([])),
        listGremienOptions: jest.fn(() => throwError(() => ({ status: 500 }))),
        listGremiumRoles: jest.fn(() => throwError(() => ({ status: 500 }))),
      }),
    });
    expect(screen.getByText('Noch keine Mitglieder in diesem Gremium.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Mitglieder: …');
    expect(screen.getByText('0 Mitglieder')).toBeInTheDocument();
  });

  it('says "1 Mitglied" for one member', async () => {
    await setup({ api: makeApi({ listGremiumMemberships: jest.fn(() => of([MEMBERS[0]])) }) });
    expect(screen.getByText('1 Mitglied')).toBeInTheDocument();
  });

  it('shows each person once and an unknown gremium as an ellipsis', async () => {
    await setup({
      api: makeApi({
        listGremienOptions: jest.fn(() => of([{ id: 'g-other', name: 'Other' }])),
        listGremiumMemberships: jest.fn(() => of([MEMBERS[0], { ...MEMBERS[0], id: 'm-dup' }])),
      }),
    });
    expect(names()).toEqual(['Zoe']);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Mitglieder: …');
  });
});
