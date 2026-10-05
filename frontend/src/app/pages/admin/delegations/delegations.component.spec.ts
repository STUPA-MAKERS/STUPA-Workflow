import { provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { type Delegation, DelegationsApiService } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { of, throwError } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import { DelegationsComponent, localToday } from './delegations.component';

function delegation(over: Partial<Delegation>): Delegation {
  return {
    id: 'd-x',
    meetingId: 'm-1',
    meetingTitle: 'Sitzung A',
    meetingDate: '2999-07-01',
    gremiumId: 'g-1',
    gremiumName: 'StuPa',
    delegatorId: 'p-1',
    delegatorName: 'Alice',
    delegateId: 'p-2',
    delegateName: 'Bob',
    delegateVoting: true,
    viaPool: false,
    createdAt: '2026-06-01T10:00:00Z',
    revocable: true,
    direction: null,
    ...over,
  };
}

const DELEGATIONS: Delegation[] = [
  delegation({
    id: 'd-2',
    meetingId: 'm-2',
    meetingTitle: 'Sitzung B',
    meetingDate: '2999-08-01',
    delegatorName: 'Cleo',
    delegateName: 'Dan',
    delegateVoting: false,
    viaPool: true,
  }),
  delegation({ id: 'd-1' }),
  delegation({
    id: 'd-3',
    meetingId: 'm-3',
    meetingTitle: null,
    meetingDate: null,
    delegatorName: null,
    delegateName: null,
  }),
  delegation({
    id: 'd-old',
    meetingId: 'm-0',
    meetingTitle: 'Alte Sitzung',
    meetingDate: '2001-01-01',
  }),
];

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    list: jest.fn(() => of(clone(DELEGATIONS))),
    revoke: jest.fn(() => of(void 0)),
    substitutes: jest.fn(() => of([])),
    addSubstitute: jest.fn(),
    removeSubstitute: jest.fn(),
    ...over,
  };
}

function makeAdmin(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listGremienOptions: jest.fn(() =>
      of([
        { id: 'g-1', name: 'Studierendenparlament' },
        { id: 'g-2', name: 'AStA' },
      ]),
    ),
    listGremiumMemberships: jest.fn(() => of([])),
    listPrincipals: jest.fn(() => of([])),
    ...over,
  };
}

async function setup(api = makeApi(), admin = makeAdmin()) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(DelegationsComponent, {
    providers: [
      provideRouter([]),
      { provide: DelegationsApiService, useValue: api },
      { provide: AdminApiService, useValue: admin },
      { provide: ToastService, useValue: toast },
      { provide: AuthService, useValue: { can: () => true } },
    ],
  });
  // NgModel writes its value after a microtask.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, admin, toast };
}

const activeList = () => screen.getAllByRole('list')[0];

describe('DelegationsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the active delegations by meeting date, with the tags and the count', async () => {
    await setup();
    const rows = within(activeList()).getAllByRole('listitem');
    expect(rows.map((r) => r.querySelector('.dl__title')?.textContent?.trim())).toEqual([
      'Sitzung A',
      'Sitzung B',
      'Sitzung',
    ]);
    expect(within(rows[0]).getByText('Stimmrecht')).toBeInTheDocument();
    expect(within(rows[0]).queryByText('Pool')).toBeNull();
    expect(within(rows[1]).getByText('Pool')).toBeInTheDocument();
    expect(within(rows[1]).queryByText('Stimmrecht')).toBeNull();
    expect(within(rows[0]).getByRole('link', { name: 'Sitzung A' })).toHaveAttribute(
      'href',
      '/meetings/m-1',
    );
    // Without names the row says so; it never shows an id.
    expect(within(rows[2]).getAllByText('(ohne Namen)')).toHaveLength(2);
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('keeps the delegations of past meetings behind a toggle', async () => {
    await setup();
    expect(screen.queryByText('Alte Sitzung')).toBeNull();
    const toggle = screen.getByRole('button', { name: /Frühere Vertretungen \(1\)/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(toggle);
    expect(screen.getByText('Alte Sitzung')).toBeInTheDocument();
  });

  it('revokes after the confirmation and removes the row', async () => {
    const api = makeApi();
    const { toast } = await setup(api);
    await userEvent.click(screen.getByRole('button', { name: 'Widerrufen: Alice → Bob' }));
    const dialog = screen.getByRole('dialog', { name: 'Vertretung widerrufen' });
    expect(dialog).toHaveTextContent(
      'Die Vertretung von Alice durch Bob in „Sitzung A“ wird gelöscht.',
    );
    expect(api.revoke).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByText('Widerrufen'));
    expect(api.revoke).toHaveBeenCalledWith('d-1');
    expect(screen.queryByText('Sitzung A')).toBeNull();
    expect(toast.success).toHaveBeenCalledWith('Vertretung widerrufen.');
  });

  it('keeps the row and names a failed revoke', async () => {
    const api = makeApi({ revoke: jest.fn(() => throwError(() => ({ status: 403 }))) });
    const { toast } = await setup(api);
    await userEvent.click(screen.getByRole('button', { name: 'Widerrufen: Alice → Bob' }));
    await userEvent.click(within(screen.getByRole('dialog')).getByText('Widerrufen'));
    expect(toast.error).toHaveBeenCalledWith('Widerruf fehlgeschlagen.');
    expect(screen.getByText('Sitzung A')).toBeInTheDocument();
  });

  it('cancels a revoke', async () => {
    const api = makeApi();
    await setup(api);
    await userEvent.click(screen.getByRole('button', { name: 'Widerrufen: Alice → Bob' }));
    await userEvent.click(within(screen.getByRole('dialog')).getByText('Abbrechen'));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(api.revoke).not.toHaveBeenCalled();
  });

  it('names a failed load and shows no list', async () => {
    await setup(makeApi({ list: jest.fn(() => throwError(() => ({ status: 500 }))) }));
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Die Vertretungen konnten nicht geladen werden.',
    );
  });

  it('says so when no delegation is active', async () => {
    await setup(makeApi({ list: jest.fn(() => of([])) }));
    expect(screen.getByText('Keine aktiven Vertretungen.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Frühere Vertretungen/ })).toBeNull();
  });

  it('shows the pool of the first gremium and switches it with the gremium chip', async () => {
    const api = makeApi();
    await setup(api);
    expect(api.substitutes).toHaveBeenLastCalledWith('g-1');
    await userEvent.click(screen.getByRole('button', { name: 'Gremium: Studierendenparlament' }));
    await userEvent.click(screen.getByRole('option', { name: 'AStA' }));
    expect(api.substitutes).toHaveBeenLastCalledWith('g-2');
  });

  it('shows no gremium chip for a single gremium and no pool without a gremium', async () => {
    const one = makeAdmin({
      listGremienOptions: jest.fn(() => of([{ id: 'g-1', name: 'StuPa' }])),
    });
    await setup(makeApi(), one);
    expect(screen.queryByRole('button', { name: /^Gremium:/ })).toBeNull();
    expect(screen.getByRole('heading', { name: 'Stellvertretungen' })).toBeInTheDocument();
  });

  it('shows no gremium chip for a single gremium and no pool without a gremium (2)', async () => {
    await setup(
      makeApi(),
      makeAdmin({ listGremienOptions: jest.fn(() => throwError(() => ({ status: 500 }))) }),
    );
    expect(screen.queryByRole('heading', { name: 'Stellvertretungen' })).toBeNull();
  });

  it('formats today as a local date', () => {
    expect(localToday(new Date(2026, 0, 5, 23, 30))).toBe('2026-01-05');
  });

  it('sorts rows of one date by title and guards the revoke', async () => {
    const same = [
      delegation({ id: 'a', meetingTitle: 'Zeta', meetingDate: '2999-01-01' }),
      delegation({ id: 'b', meetingTitle: null, meetingDate: '2999-01-01' }),
      delegation({ id: 'c', meetingTitle: 'Alpha', meetingDate: '2999-01-01' }),
      delegation({ id: 'p1', meetingTitle: 'Alt 1', meetingDate: '2000-01-01' }),
      delegation({ id: 'p2', meetingTitle: 'Alt 2', meetingDate: '2001-01-01' }),
    ];
    const api = makeApi({ list: jest.fn(() => of(same)) });
    const { fixture } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.active().map((d: Delegation) => d.id)).toEqual(['b', 'c', 'a']);
    // Past meetings: the newest first.
    expect(c.past().map((d: Delegation) => d.id)).toEqual(['p2', 'p1']);
    c.revoke();
    c.confirmRevoke.set(same[0]);
    c.busy.set(true);
    c.revoke();
    expect(api.revoke).not.toHaveBeenCalled();
  });
});
