import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { type DelegationSubstitute, DelegationsApiService } from '@core/api/delegations.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { of, throwError } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal } from '../admin.models';
import { SubstitutePoolComponent } from './substitute-pool.component';

const ENTRIES: DelegationSubstitute[] = [
  {
    id: 's-1',
    gremiumId: 'g-1',
    memberId: null,
    memberName: null,
    substituteId: 'p-9',
    substituteName: 'Fabi Fachschaft',
  },
  {
    id: 's-2',
    gremiumId: 'g-1',
    memberId: 'p-2',
    memberName: 'Robin',
    substituteId: 'p-3',
    substituteName: 'Sam',
  },
  {
    id: 's-3',
    gremiumId: 'g-1',
    memberId: 'p-4',
    memberName: null,
    substituteId: 'p-5',
    substituteName: null,
  },
];
const PEOPLE: AdminPrincipal[] = [
  {
    id: 'p-7',
    sub: 'kc|kim',
    email: 'kim@x.de',
    displayName: 'Kim',
    assignments: [],
    oidcGroups: [],
  },
  { id: 'p-8', sub: 'kc|ki', email: null, displayName: '', assignments: [], oidcGroups: [] },
  {
    id: 'p-0',
    sub: 'kc|off',
    email: 'off@x.de',
    displayName: 'Off',
    active: false,
    assignments: [],
    oidcGroups: [],
  },
];

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

function makeDelegations(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    substitutes: jest.fn(() => of(clone(ENTRIES))),
    addSubstitute: jest.fn((b: { substituteId: string; memberId: string | null }) =>
      of({
        id: 's-new',
        gremiumId: 'g-1',
        memberId: b.memberId,
        memberName: null,
        substituteId: b.substituteId,
        substituteName: 'Kim',
      }),
    ),
    removeSubstitute: jest.fn(() => of(void 0)),
    ...over,
  };
}

function makeAdmin(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listPrincipals: jest.fn(() => of(clone(PEOPLE))),
    listGremiumMemberships: jest.fn(() =>
      of([
        {
          id: 'm1',
          principalId: 'p-4',
          gremiumId: 'g-1',
          gremiumRoleId: 'r',
          displayName: 'Toni',
          email: null,
        },
        {
          id: 'm2',
          principalId: 'p-2',
          gremiumId: 'g-1',
          gremiumRoleId: 'r',
          displayName: null,
          email: 'robin@x.de',
        },
        {
          id: 'm3',
          principalId: 'p-2',
          gremiumId: 'g-1',
          gremiumRoleId: 'r2',
          displayName: null,
          email: 'robin@x.de',
        },
        {
          id: 'm4',
          principalId: 'p-6',
          gremiumId: 'g-1',
          gremiumRoleId: 'r',
          displayName: null,
          email: null,
        },
        // A deactivated member represents nobody, so it is no choice.
        {
          id: 'm5',
          principalId: 'p-9',
          gremiumId: 'g-1',
          gremiumRoleId: 'r',
          displayName: 'Ehemalig',
          email: null,
          active: false,
        },
      ]),
    ),
    ...over,
  };
}

async function setup(
  opts: {
    delegations?: ReturnType<typeof makeDelegations>;
    admin?: ReturnType<typeof makeAdmin>;
    members?: unknown;
  } = {},
) {
  const delegations = opts.delegations ?? makeDelegations();
  const admin = opts.admin ?? makeAdmin();
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(SubstitutePoolComponent, {
    providers: [
      { provide: DelegationsApiService, useValue: delegations },
      { provide: AdminApiService, useValue: admin },
      { provide: ToastService, useValue: toast },
    ],
    componentInputs: {
      gremiumId: 'g-1',
      ...(opts.members !== undefined ? { members: opts.members } : {}),
    },
  });
  // NgModel writes its value after a microtask.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, delegations, admin, toast };
}

describe('SubstitutePoolComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the entries with the member they represent', async () => {
    await setup();
    const rows = within(screen.getByRole('list', { name: 'Einzelne Einträge' })).getAllByRole(
      'listitem',
    );
    expect(rows[0]).toHaveTextContent('Fabi Fachschaft');
    expect(rows[0]).toHaveTextContent('Alle Mitglieder');
    expect(rows[1]).toHaveTextContent('Robin');
    // A missing name falls back to the member list, then to a placeholder.
    expect(rows[2]).toHaveTextContent('Toni');
    expect(rows[2]).toHaveTextContent('(ohne Namen)');
  });

  it('removes an entry at once', async () => {
    const { delegations, toast } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Eintrag entfernen: Sam' }));
    expect(delegations.removeSubstitute).toHaveBeenCalledWith('s-2');
    expect(screen.queryByText('Sam')).toBeNull();
    expect(toast.success).toHaveBeenCalledWith('Eintrag entfernt.');
  });

  it('keeps an entry when the remove fails', async () => {
    const delegations = makeDelegations({
      removeSubstitute: jest.fn(() => throwError(() => ({ status: 403 }))),
    });
    const { toast } = await setup({ delegations });
    await userEvent.click(screen.getByRole('button', { name: 'Eintrag entfernen: Sam' }));
    expect(screen.getByText('Sam')).toBeInTheDocument();
    expect(toast.error).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
  });

  it('adds an entry for one member through the person search', async () => {
    const { delegations, admin, toast } = await setup();
    await userEvent.click(screen.getByRole('button', { name: /Eintrag hinzufügen/ }));
    const dialog = screen.getByRole('dialog', { name: 'Eintrag hinzufügen' });
    const add = within(dialog).getByText('Hinzufügen').closest('button')!;
    expect(add).toBeDisabled();
    await userEvent.type(within(dialog).getByRole('searchbox', { name: /Person suchen/ }), 'ki');
    await waitFor(() => expect(admin.listPrincipals).toHaveBeenCalledWith('ki'));
    // An inactive person is no choice; a person without a name shows the subject.
    expect(await within(dialog).findByRole('button', { name: /Kim/ })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'kc|ki' })).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: /Off/ })).toBeNull();
    await userEvent.click(within(dialog).getByRole('button', { name: /Kim/ }));
    expect(within(dialog).getByRole('status')).toHaveTextContent('Gewählt: Kim');
    // The members are the choices of "Vertritt", one per person.
    const select = within(dialog).getByRole('combobox', { name: 'Vertritt' }) as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent?.trim())).toEqual([
      'Alle Mitglieder',
      '(ohne Namen)',
      'robin@x.de',
      'Toni',
    ]);
    await userEvent.selectOptions(select, 'p-4');
    await userEvent.click(add);
    expect(delegations.addSubstitute).toHaveBeenCalledWith({
      gremiumId: 'g-1',
      memberId: 'p-4',
      substituteId: 'p-7',
    });
    expect(toast.success).toHaveBeenCalledWith('Eintrag hinzugefügt.');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('names a duplicate, a self-substitution and another failure in the dialog', async () => {
    const delegations = makeDelegations({
      addSubstitute: jest
        .fn()
        .mockReturnValueOnce(throwError(() => ({ status: 409 })))
        .mockReturnValueOnce(throwError(() => ({ status: 422 })))
        .mockReturnValueOnce(throwError(() => ({ status: 500 }))),
    });
    await setup({ delegations });
    await userEvent.click(screen.getByRole('button', { name: /Eintrag hinzufügen/ }));
    const dialog = screen.getByRole('dialog');
    await userEvent.type(within(dialog).getByRole('searchbox'), 'kim');
    await userEvent.click(await within(dialog).findByRole('button', { name: /Kim/ }));
    const add = within(dialog).getByText('Hinzufügen').closest('button')!;
    await userEvent.click(add);
    expect(within(dialog).getByRole('alert')).toHaveTextContent(
      'Dieser Eintrag existiert bereits.',
    );
    await userEvent.click(add);
    expect(within(dialog).getByRole('alert')).toHaveTextContent(
      'Eine Person kann sich nicht selbst vertreten.',
    );
    await userEvent.click(add);
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Aktion fehlgeschlagen.');
  });

  it('says so when the search finds nobody and when it fails', async () => {
    const admin = makeAdmin({
      listPrincipals: jest
        .fn()
        .mockReturnValueOnce(of([]))
        .mockReturnValueOnce(throwError(() => ({ status: 500 })))
        .mockReturnValue(of(clone(PEOPLE))),
    });
    await setup({ admin });
    await userEvent.click(screen.getByRole('button', { name: /Eintrag hinzufügen/ }));
    const search = screen.getByRole('searchbox');
    await userEvent.type(search, 'zz');
    expect(await screen.findByText('Keine Person gefunden.')).toBeInTheDocument();
    await userEvent.type(search, 'z');
    await waitFor(() => expect(admin.listPrincipals).toHaveBeenCalledTimes(2));
    // The stream lives on after a failure.
    await userEvent.clear(search);
    expect(screen.queryByText('Keine Person gefunden.')).toBeNull();
    await userEvent.type(search, 'k');
    expect(await screen.findByRole('button', { name: /Kim/ })).toBeInTheDocument();
  });

  it('takes the members from the input and loads no memberships', async () => {
    const admin = makeAdmin();
    await setup({ admin, members: [{ id: 'p-4', name: 'Toni T.' }] });
    expect(admin.listGremiumMemberships).not.toHaveBeenCalled();
    expect(screen.getAllByRole('listitem')[2]).toHaveTextContent('Toni T.');
  });

  it('names a failed load and an empty pool', async () => {
    await setup({
      delegations: makeDelegations({
        substitutes: jest.fn(() => throwError(() => ({ status: 403 }))),
      }),
    });
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Die Stellvertretungen konnten nicht geladen werden.',
    );
  });

  it('names a failed load and an empty pool (2)', async () => {
    await setup({
      delegations: makeDelegations({ substitutes: jest.fn(() => of([])) }),
      admin: makeAdmin({
        listGremiumMemberships: jest.fn(() => throwError(() => ({ status: 403 }))),
      }),
    });
    expect(screen.getByText('Keine Stellvertretungen benannt.')).toBeInTheDocument();
  });

  it('loads again for another gremium', async () => {
    const { delegations, fixture } = await setup();
    fixture.componentRef.setInput('gremiumId', 'g-2');
    fixture.detectChanges();
    expect(delegations.substitutes).toHaveBeenLastCalledWith('g-2');
  });

  it('guards add and remove and drops a choice when the search text changes', async () => {
    const delegations = makeDelegations();
    const { fixture } = await setup({ delegations });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.add();
    expect(delegations.addSubstitute).not.toHaveBeenCalled();
    c.pick(PEOPLE[0]);
    expect(c.selected()).toEqual(PEOPLE[0]);
    c.onSearch('Kim');
    expect(c.selected()).toEqual(PEOPLE[0]);
    c.onSearch('Kimberly');
    expect(c.selected()).toBeNull();
    c.onSearch('  ');
    expect(c.searching()).toBe(false);
    c.adding.set(true);
    c.pick(PEOPLE[0]);
    c.add();
    expect(delegations.addSubstitute).not.toHaveBeenCalled();
    c.removing.set(new Set(['s-1']));
    c.remove(ENTRIES[0]);
    expect(delegations.removeSubstitute).not.toHaveBeenCalled();
    expect(c.label({ ...PEOPLE[1], sub: 'kc|x' })).toBe('kc|x');
    expect(c.label({ ...PEOPLE[1], email: 'e@x.de' })).toBe('e@x.de');
  });
});
