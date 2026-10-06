import { of, throwError } from 'rxjs';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
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
  { id: 'gm-1', oidcGroup: 'stupa-referat', roleId: 'r-ref' },
  // The same role as the bootstrap assignment. The column shows it once.
  { id: 'gm-2', oidcGroup: 'stupa-referat', roleId: 'r-admin' },
  // A reserved group never gives a role, not even through a mapping.
  { id: 'gm-3', oidcGroup: 'vote:g-1', roleId: 'r-member' },
];

function makeAuth(sub: string | null, canMappings = true, canMerge = false, canErase = false) {
  return {
    principal: () => (sub === null ? null : { sub }),
    can: (p: string) =>
      p === 'admin.users' ||
      (canMappings && p === 'admin.group_mappings') ||
      (canMerge && p === 'admin.users.merge') ||
      (canErase && p === 'privacy.manage'),
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
    previewPrincipalMerge: jest.fn(() => of(null)),
    mergePrincipal: jest.fn(() => of(null)),
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
    expect(inst.search.text()).toBe('kc|alex');
    expect(api.listPrincipals).toHaveBeenCalledTimes(1);
  });

  it('lists principals with the capitalized, read-only roles on one line', async () => {
    await setup();
    expect(screen.getByText('Alex Admin')).toBeInTheDocument();
    expect(screen.getByText('Administrator, Referent')).toBeInTheDocument();
    expect(screen.queryByText(/administrator/)).not.toBeInTheDocument();
    expect(screen.getByText('Keine Rollen zugewiesen.')).toBeInTheDocument();
    // The e-mail address shows in full; a principal without one shows none.
    expect(screen.getByText('alex@x.de')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    // No role editing is left: no assign, edit or revoke control.
    expect(screen.queryByRole('button', { name: /Entziehen|Zuweisung|Rolle \+/ })).toBeNull();
  });

  it('shows the OIDC groups of each user, or a placeholder', async () => {
    await setup();
    expect(screen.getAllByText('OIDC-Gruppen')).toHaveLength(2);
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
    expect(screen.getByRole('link', { name: 'Gruppen-Zuordnung' })).toHaveAttribute(
      'href',
      '/admin/group-mappings',
    );
  });

  it('without admin.group_mappings: no link and no mapping request', async () => {
    const api = makeApi();
    const { inst } = await setup(api, makeAuth(null, false));
    expect(api.listGroupMappings).not.toHaveBeenCalled();
    expect(screen.queryByRole('link', { name: 'Gruppen-Zuordnung' })).toBeNull();
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

  it('userLabel prefers displayName, then email, then "Ohne Namen" (D7)', async () => {
    const { inst } = await setup();
    expect(inst.userLabel({ displayName: 'Name', email: 'e', sub: 's' })).toBe('Name');
    expect(inst.userLabel({ displayName: '', email: 'e@x', sub: 's' })).toBe('e@x');
    expect(inst.userLabel({ displayName: null, email: null, sub: 'sub-only' })).toBe('Ohne Namen');
  });

  it('a nameless account shows "Ohne Namen" with the sub only in the tooltip (D7)', async () => {
    const nameless = { ...PRINCIPALS[1], id: 'p-5', sub: 'kc|ghost', displayName: null, email: null };
    const api = makeApi({ listPrincipals: jest.fn(() => of([nameless])) });
    const { inst } = await setup(api);
    const name = screen.getByText('Ohne Namen');
    expect(name).toHaveAttribute('title', 'kc|ghost');
    expect(screen.queryByText('kc|ghost')).toBeNull();
    expect(inst.userTitle(PRINCIPALS[0])).toBe('Alex Admin');
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

  describe('live search', () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    it('searches while the user types, without a "Suchen" button', async () => {
      const { api } = await setup();
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      expect(screen.queryByRole('button', { name: 'Suchen' })).toBeNull();
      api.listPrincipals.mockClear();
      await user.type(screen.getByRole('searchbox', { name: 'Benutzer suchen' }), 'alex');
      // The debounce folds the four key presses into one request.
      expect(api.listPrincipals).not.toHaveBeenCalled();
      jest.advanceTimersByTime(260);
      expect(api.listPrincipals).toHaveBeenCalledTimes(1);
      expect(api.listPrincipals).toHaveBeenLastCalledWith('alex');
    });

    it('sends no request for one character and runs at once on Enter', async () => {
      const { api } = await setup();
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      api.listPrincipals.mockClear();
      const box = screen.getByRole('searchbox', { name: 'Benutzer suchen' });
      await user.type(box, 'a');
      jest.advanceTimersByTime(260);
      expect(api.listPrincipals).not.toHaveBeenCalled();
      await user.type(box, 'l{Enter}');
      expect(api.listPrincipals).toHaveBeenCalledWith('al');
    });

    it('lists every user again when the × clears the field', async () => {
      const { api } = await setup();
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
      await user.type(screen.getByRole('searchbox', { name: 'Benutzer suchen' }), 'alex');
      jest.advanceTimersByTime(260);
      api.listPrincipals.mockClear();
      await user.click(screen.getByRole('button', { name: 'Suche leeren' }));
      expect(api.listPrincipals).toHaveBeenCalledWith('');
      expect(screen.getByRole('searchbox', { name: 'Benutzer suchen' })).toHaveValue('');
    });
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

  it('deactivates from the row, and the own account only with a reason', async () => {
    const { api } = await setup(makeApi(), makeAuth('kc|sam'));
    const own = screen.getAllByRole('button', { name: /^Deaktivieren: / });
    // Alex can be deactivated; Sam is the signed-in user.
    expect(own[0]).toBeEnabled();
    expect(own[1]).toBeDisabled();
    expect(own[1]).toHaveAttribute('title', 'Du kannst dein eigenes Konto nicht deaktivieren.');
    // The button names its person, so a list of the buttons tells the rows apart.
    expect(own[0]).toHaveAccessibleName('Deaktivieren: Alex Admin');
    await userEvent.click(own[0]);
    expect(api.setPrincipalActive).toHaveBeenCalledWith('p-1', false);
  });

  it('greys out an inactive principal and offers "Aktivieren"', async () => {
    const api = makeApi({
      listPrincipals: jest.fn(() => of([{ ...PRINCIPALS[1], active: false }])),
    });
    const { container } = await setup(api);
    expect(container.querySelector('.au__row--off')).not.toBeNull();
    expect(screen.getByText('deaktiviert')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Aktivieren: / }));
    expect(api.setPrincipalActive).toHaveBeenCalledWith('p-3', true);
  });

  it('shows the last login as a date, else "nie"', async () => {
    await setup();
    expect(screen.getByText('nie')).toBeInTheDocument();
    expect(screen.getByText(/06\.06\.2026/)).toBeInTheDocument();
  });

  it('shows the empty state when the search finds nobody', async () => {
    await setup(makeApi({ listPrincipals: jest.fn(() => of([])) }));
    expect(screen.getByText('Keine Benutzer gefunden.')).toBeInTheDocument();
  });

  describe('account merge', () => {
    const MERGED: AdminPrincipal = {
      id: 'p-9',
      sub: 'e03ad7d7',
      email: 'alt@x.de',
      displayName: 'Alex Alt',
      lastLogin: null,
      assignments: [],
      oidcGroups: [],
      active: false,
      mergedIntoId: 'p-1',
      mergedIntoName: 'Alex Admin',
      mergedAt: '2026-10-05T09:00:00+00:00',
    };

    it('a merged account shows "zusammengeführt in" and no action', async () => {
      const api = makeApi({ listPrincipals: jest.fn(() => of([MERGED, { ...MERGED, id: 'p-8', mergedIntoName: null }])) });
      const { container } = await setup(api, makeAuth(null, true, true));
      expect(screen.getByText('zusammengeführt in Alex Admin')).toBeInTheDocument();
      expect(screen.getByText('zusammengeführt in Konto ohne Namen')).toBeInTheDocument();
      expect(screen.queryByText('deaktiviert')).toBeNull();
      expect(container.querySelectorAll('.au__row--off')).toHaveLength(2);
      expect(screen.queryByRole('button', { name: /Aktivieren|Deaktivieren|Weitere Aktionen/ })).toBeNull();
    });

    it('without admin.users.merge the row has no menu', async () => {
      await setup(makeApi(), makeAuth(null));
      expect(screen.queryByRole('button', { name: /^Weitere Aktionen/ })).toBeNull();
    });

    it('the row menu opens the merge dialog; the own account cannot be merged', async () => {
      const { inst } = await setup(makeApi(), makeAuth('kc|alex', true, true));
      const menus = screen.getAllByRole('button', { name: /^Weitere Aktionen: / });
      expect(menus).toHaveLength(2);
      const own = inst.menuFor(PRINCIPALS[0])[0].items[0];
      expect(own.disabledReason).toBe(
        'Dein eigenes Konto kannst du nicht in ein anderes Konto zusammenführen.',
      );
      const other = inst.menuFor(PRINCIPALS[1])[0].items[0];
      expect(other).toMatchObject({ id: 'merge', danger: true, disabledReason: null });
      inst.onMenu({ id: 'other', label: 'x' }, PRINCIPALS[1]);
      expect(inst.mergeSource()).toBeNull();
      inst.onMenu(other, PRINCIPALS[1]);
      expect(inst.mergeSource()).toEqual(PRINCIPALS[1]);
    });

    it('"Konto löschen (DSGVO)" needs privacy.manage and opens the privacy page (D1)', async () => {
      const { inst, fixture } = await setup(makeApi(), makeAuth(null, true, false, true));
      expect(screen.getAllByRole('button', { name: /^Weitere Aktionen: / })).toHaveLength(2);
      const items = inst.menuFor(PRINCIPALS[1])[0].items;
      expect(items.map((i: { id: string }) => i.id)).toEqual(['erase']);
      expect(items[0]).toMatchObject({ label: 'Konto löschen (DSGVO)', danger: true });
      const router = fixture.debugElement.injector.get(Router);
      const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);
      inst.onMenu(items[0], PRINCIPALS[1]);
      expect(nav).toHaveBeenCalledWith(['/admin/privacy'], { queryParams: { person: 'kc|sam' } });
    });

    it('with both permissions the menu holds merge and erase', async () => {
      const { inst } = await setup(makeApi(), makeAuth(null, true, true, true));
      expect(inst.menuFor(PRINCIPALS[1])[0].items.map((i: { id: string }) => i.id)).toEqual(['merge', 'erase']);
    });

    it('a merge reloads the list', async () => {
      const { api, inst } = await setup(makeApi(), makeAuth(null, true, true));
      api.listPrincipals.mockClear();
      inst.onMerged();
      expect(api.listPrincipals).toHaveBeenCalled();
    });
  });
});
