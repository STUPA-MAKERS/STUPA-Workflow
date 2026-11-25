import { of, throwError } from 'rxjs';
import { ActivatedRoute } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import {
  DEFAULT_STATUS_LISTS,
  type StatusListKind,
  StatusCatalog,
  provideTestStatuses,
} from '@core/api/statuses.service';
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

async function setup(
  opts: { kind?: StatusListKind; perms?: string[]; api?: ReturnType<typeof makeApi> } = {},
) {
  const api = opts.api ?? makeApi();
  const kind = opts.kind ?? 'order';
  const perms = new Set(opts.perms ?? ['admin.order_phases', 'admin.event_phases']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(AdminStatusesComponent, {
    providers: [
      provideTestStatuses(),
      { provide: ActivatedRoute, useValue: { snapshot: { data: { statusList: kind } } } },
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

  /** § 003040: the page Bestellphasen holds the list of the Bestellungen, each as a numbered row. */
  it('shows the list of its page only', async () => {
    const { api } = await setup();
    expect(api.getStatusList).toHaveBeenCalledTimes(1);
    expect(api.getStatusList).toHaveBeenCalledWith('order');
    expect(screen.getByRole('heading', { name: 'Bestellphasen' })).toBeInTheDocument();
    const names = screen.getAllByLabelText(/^Name von Phase \d/) as HTMLInputElement[];
    expect(names.map((field) => field.value)).toEqual([
      'Geplant',
      'Bestellt',
      'Geliefert',
      'Storniert',
    ]);
    expect(screen.getByLabelText(/^Art von Phase 1/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Datum von Phase 1/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
  });

  /** § 003040: a new phase, moved up, saves with its new position; the event page sends its list. */
  it('adds a phase, moves it up and saves the list in the new order', async () => {
    const { c, api, toast } = await setup({ kind: 'event' });
    expect(screen.getByRole('heading', { name: 'Veranstaltungsphasen' })).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Datum von Phase/)).toBeNull();
    c.add();
    c.setName(3, 'In Planung');
    c.move(3, -1);
    c.move(2, -1);
    expect(c.body()).not.toBeNull();
    c.save();
    expect(api.putStatusList).toHaveBeenCalledTimes(1);
    const [kind, body] = api.putStatusList.mock.calls[0] as [StatusListKind, StatusListBody];
    expect(kind).toBe('event');
    expect(body.statuses.map((s) => s.key)).toEqual([
      'planned',
      'in_planung',
      'settled',
      'cancelled',
    ]);
    expect(body.statuses.map((s) => s.start)).toEqual([true, false, false, false]);
    expect(body.statuses[1]).toEqual({
      key: 'in_planung',
      name: { de: 'In Planung' },
      tone: 'neutral',
      phase: 'open',
      start: false,
    });
    expect(body.replacements).toEqual({});
    expect(toast.success).toHaveBeenCalled();
  });

  /** § 003035: the first phase is the start, so it needs the kind open; each kind once. */
  it('refuses a list without an open start or without a kind', async () => {
    const { c } = await setup({ kind: 'event' });
    c.move(0, 1);
    expect(c.body()).toBeNull();
    expect(c.phaseError(0)).toBe('Die erste Phase ist der Start und braucht die Art Offen.');
    c.move(0, 1);
    c.remove(2);
    expect(c.body()).toBeNull();
    expect(c.missing()).toBe('Es fehlt eine Phase der Art Verworfen.');
    c.discard();
    expect(c.body()).not.toBeNull();
    expect(c.form.dirty()).toBe(false);
  });

  /** § 003038: the delete of a phase in use asks where its Bestellungen go; Abbrechen keeps it. */
  it('asks the target of a deleted phase in a sheet', async () => {
    const { c, api } = await setup();
    c.remove(3);
    expect(c.rows()).toHaveLength(4);
    expect(c.deleteTitle()).toBe('„Storniert“ löschen');
    expect(c.deleteSub()).toBe('Bestellungen in dieser Phase: 3');
    expect(c.targets().map((o: { value: string }) => o.value)).toEqual([
      'planned',
      'ordered',
      'delivered',
    ]);
    c.cancelDelete();
    expect(c.rows()).toHaveLength(4);
    c.remove(3);
    c.replaceWith('delivered');
    expect(c.deleting()).toBeNull();
    expect(c.rows()).toHaveLength(3);
    c.add();
    c.setName(3, 'Zurückgegeben');
    c.patch(3, { phase: 'void', tone: 'muted' });
    // The target takes the moved Bestellungen, so its own delete asks again and passes them on.
    c.remove(2);
    expect(c.deleteSub()).toBe('Bestellungen in dieser Phase: 4');
    c.replaceWith('ordered');
    c.add();
    c.setName(3, 'Fertig');
    c.patch(3, { phase: 'done' });
    const body = c.body() as StatusListBody;
    expect(body.replacements).toEqual({ cancelled: 'ordered', delivered: 'ordered' });
    expect(body.statuses.map((s) => s.key)).toEqual([
      'planned',
      'ordered',
      'zurueckgegeben',
      'fertig',
    ]);
    c.save();
    expect(api.putStatusList).toHaveBeenCalledWith('order', body);
  });

  /** § 003038: a new phase or one without elements goes at once. */
  it('deletes a phase without elements at once', async () => {
    const { c } = await setup();
    c.remove(1);
    expect(c.deleting()).toBeNull();
    expect(c.rows().map((r: { key: string }) => r.key)).toEqual([
      'planned',
      'delivered',
      'cancelled',
    ]);
  });

  it('names the reason of a refused save and tells the catalog of a save', async () => {
    const api = makeApi();
    api.putStatusList.mockReturnValueOnce(
      throwError(() => ({ status: 409, error: { code: 'status_in_flow' } })),
    );
    const { c, toast, fixture } = await setup({ api, kind: 'event' });
    c.setName(0, 'Kommt');
    c.save();
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Ablaufs'));
    c.save();
    const catalog = fixture.debugElement.injector.get(StatusCatalog);
    expect(catalog.label('event', 'planned')).toBe('Kommt');
  });

  it('names a phase in use, and leaves an unknown problem to the default text', async () => {
    const api = makeApi();
    api.putStatusList
      .mockReturnValueOnce(throwError(() => ({ status: 409, error: { code: 'status_in_use' } })))
      .mockReturnValueOnce(throwError(() => ({ status: 500, error: {} })));
    const { c, toast } = await setup({ api, kind: 'event' });
    c.setName(0, 'Kommt');
    c.save();
    expect(toast.error).toHaveBeenLastCalledWith(expect.stringContaining('noch genutzt'));
    c.save();
    expect(toast.error).toHaveBeenCalledTimes(2);
  });

  it('ignores a delete or a pick without its row', async () => {
    const { c } = await setup({ kind: 'event' });
    expect(c.columns()).toBe(2);
    expect([c.deleteTitle(), c.deleteSub()]).toEqual(['', '']);
    c.remove(9);
    c.replaceWith('planned');
    expect(c.rows()).toHaveLength(3);
    c.add();
    c.remove(3);
    expect(c.rows()).toHaveLength(3);
  });

  it('shows the load error with a retry', async () => {
    const api = makeApi();
    api.getStatusList.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    const { c } = await setup({ api });
    expect(c.screenState()).toEqual(
      expect.objectContaining({
        state: 'error',
        message: 'Die Phasen konnten nicht geladen werden.',
      }),
    );
    c.screenState().retry();
    expect(api.getStatusList).toHaveBeenCalledTimes(2);
    expect(c.screenState()).toEqual({ state: 'ready' });
  });

  it('shows no list without the right of its page', async () => {
    const { api } = await setup({ perms: ['admin.event_phases'] });
    expect(api.getStatusList).not.toHaveBeenCalled();
    expect(
      screen.getByText('Für diese Seite fehlt das Recht, Bestellphasen zu verwalten.'),
    ).toBeInTheDocument();
  });
});
