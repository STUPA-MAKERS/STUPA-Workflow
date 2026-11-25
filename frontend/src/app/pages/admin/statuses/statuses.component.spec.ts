import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { DEFAULT_STATUS_LISTS, type StatusListKind, StatusCatalog, provideTestStatuses } from '@core/api/statuses.service';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { StatusListBody } from '../admin.models';
import { AdminStatusesComponent } from './statuses.component';
import { toastWith } from '../../../../testing/load-error';

const USED = { planned: 2, ordered: 0, delivered: 1, cancelled: 3 } as const;

function makeApi() {
  return {
    getStatusList: jest.fn((kind: StatusListKind) =>
      of({
        kind,
        statuses: DEFAULT_STATUS_LISTS[kind].map((s) => ({
          ...s,
          used: kind === 'order' ? USED[s.key as keyof typeof USED] : 0,
        })),
      }),
    ),
    putStatusList: jest.fn((kind: StatusListKind, body: StatusListBody) =>
      of({ kind, statuses: body.statuses.map((s) => ({ ...s, used: 0 })) }),
    ),
  };
}

async function setup(opts: { perms?: string[]; api?: ReturnType<typeof makeApi> } = {}) {
  const api = opts.api ?? makeApi();
  const perms = new Set(opts.perms ?? ['admin.statuses']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(AdminStatusesComponent, {
    providers: [
      provideTestStatuses(),
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: ToastService, useFactory: () => toastWith(toast) },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, toast, c };
}

describe('AdminStatusesComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** § 003040: one section per list, each status as a numbered row. */
  it('shows the list of the Bestellungen and of the Veranstaltungen', async () => {
    const { api } = await setup();
    expect(api.getStatusList).toHaveBeenCalledWith('order');
    expect(api.getStatusList).toHaveBeenCalledWith('event');
    expect(screen.getByRole('heading', { name: 'Status & Phasen' })).toBeInTheDocument();
    expect(screen.getByText('Bestellungen')).toBeInTheDocument();
    expect(screen.getByText('Veranstaltungen')).toBeInTheDocument();
    const names = screen.getAllByLabelText(/^Name von Status 1/) as HTMLInputElement[];
    expect(names.map((field) => field.value)).toEqual(['Geplant', 'Geplant']);
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
  });

  /** § 003040: a new status, moved up, saves with its new position; only the changed list. */
  it('adds a status, moves it up and saves the list in the new order', async () => {
    const { c, api, toast } = await setup();
    c.add('event');
    c.setName('event', 3, 'In Planung');
    c.move('event', 3, -1);
    c.move('event', 2, -1);
    expect(c.body()).not.toBeNull();
    c.save();
    expect(api.putStatusList).toHaveBeenCalledTimes(1);
    const [kind, body] = api.putStatusList.mock.calls[0] as [StatusListKind, StatusListBody];
    expect(kind).toBe('event');
    expect(body.statuses.map((s) => s.key)).toEqual(['planned', 'in_planung', 'settled', 'cancelled']);
    expect(body.statuses.map((s) => s.start)).toEqual([true, false, false, false]);
    expect(body.statuses[1]).toEqual({ key: 'in_planung', name: { de: 'In Planung' }, tone: 'neutral', phase: 'open', start: false });
    expect(body.replacements).toEqual({});
    expect(toast.success).toHaveBeenCalled();
  });

  /** § 003035: the first status is the start, so it needs the phase open; each phase once. */
  it('refuses a list without an open start or without a phase', async () => {
    const { c } = await setup();
    c.move('event', 0, 1);
    expect(c.body()).toBeNull();
    expect(c.phaseError('event', 0)).toBe('Der erste Status ist der Start und braucht die Phase Offen.');
    c.move('event', 0, 1);
    c.remove('event', 2);
    expect(c.body()).toBeNull();
    expect(c.missing('event')).toBe('Es fehlt ein Status mit der Phase Verworfen.');
    c.discard();
    expect(c.body()).toEqual({});
  });

  /** § 003038: a removed status in use needs a replacement, and the date stays on Bestellungen. */
  it('asks a replacement for a removed status in use', async () => {
    const { c, api } = await setup();
    c.remove('order', 3);
    c.add('order');
    c.setName('order', 3, 'Zurückgegeben');
    c.patch('order', 3, { phase: 'void', tone: 'muted' });
    expect(c.removed('order').map((r: { key: string }) => r.key)).toEqual(['cancelled']);
    expect(c.removedLabel('order', c.removed('order')[0])).toBe('Ersatz für „Storniert“ (3 Bestellungen)');
    expect(c.replacementOptions('order').map((o: { value: string }) => o.value)).toEqual(['planned', 'ordered', 'delivered']);
    expect(c.body()).toBeNull();
    c.setReplacement('order', 'cancelled', 'delivered');
    const body = c.body().order as StatusListBody;
    expect(body.replacements).toEqual({ cancelled: 'delivered' });
    expect(body.statuses[3].key).toBe('zurueckgegeben');
    expect(body.statuses[1].setsDate).toBe('orderedOn');
    c.save();
    expect(api.putStatusList).toHaveBeenCalledWith('order', body);
  });

  it('names the reason of a refused save and tells the catalog of a save', async () => {
    const api = makeApi();
    api.putStatusList.mockReturnValueOnce(throwError(() => ({ status: 409, error: { code: 'status_in_flow' } })));
    const { c, toast, fixture } = await setup({ api });
    c.setName('event', 0, 'Kommt');
    c.save();
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Ablaufs'));
    c.save();
    const catalog = fixture.debugElement.injector.get(StatusCatalog);
    expect(catalog.label('event', 'planned')).toBe('Kommt');
  });

  it('shows no list without the right', async () => {
    const { api } = await setup({ perms: [] });
    expect(api.getStatusList).not.toHaveBeenCalled();
    expect(screen.getByText('Für diese Seite fehlt das Recht, Status & Phasen zu verwalten.')).toBeInTheDocument();
  });
});

