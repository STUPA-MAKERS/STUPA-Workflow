import { provideTestStatuses } from '@core/api/statuses.service';
import { provideRouter } from '@angular/router';
import { render } from '@testing-library/angular';
import { Subject, of, throwError } from 'rxjs';
import { type EventOption, type EventPage, EventsApiService } from '@core/api/events.service';
import { AuthService } from '@core/auth/auth.service';
import { type ListQuery, type ListRow, type LoadState, ToastService } from '@stupa-makers/ui-kit';
import { eventItem } from '../../../testing/event-fixtures';
import { EVENTS_PAGE_SIZE, EventsPageComponent } from './events-page.component';
import { EventsRefresh } from './events-refresh';

const PAGE: EventPage = {
  items: [
    eventItem(),
    eventItem({ id: 'e-2', title: 'Lesung', status: 'settled', startsOn: null, endsOn: null, startTime: null, endTime: null, place: null, teamName: null }),
  ],
  total: 3,
};

const TEAMS: readonly EventOption[] = [
  { id: 't-1', name: 'Kultur' },
  { id: 't-2', name: 'Sport' },
];

const query = (filters: Record<string, unknown> = {}, search = ''): ListQuery =>
  ({ search, filters, sort: null }) as unknown as ListQuery;

interface Options {
  readonly permissions?: readonly string[];
  readonly teams?: readonly EventOption[] | null;
  readonly series?: readonly EventOption[] | null;
}

async function setup(options: Options = {}) {
  localStorage.setItem('ap.locale', 'de');
  const permissions = options.permissions ?? ['finance.export'];
  const fail = () => throwError(() => ({ status: 500 }));
  const api = {
    page: jest.fn(() => of(PAGE)),
    teams: jest.fn(() => (options.teams === null ? fail() : of(options.teams ?? TEAMS))),
    series: jest.fn(() => (options.series === null ? fail() : of(options.series ?? [{ id: 's-1', name: 'Erstiparty' }]))),
    exportXlsx: jest.fn(() => of(new Blob(['x']))),
  };
  const view = await render(EventsPageComponent, {
    providers: [
      provideTestStatuses(),
      provideRouter([]),
      { provide: EventsApiService, useValue: api },
      { provide: AuthService, useValue: { can: (p: string) => permissions.includes(p) } },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.componentInstance as any;
  const toast = view.fixture.debugElement.injector.get(ToastService);
  const refresh = view.fixture.debugElement.injector.get(EventsRefresh);
  const rows = (): LoadState<readonly ListRow[]> => cmp.rows();
  return { ...view, cmp, api, toast, refresh, rows };
}

describe('EventsPageComponent', () => {
  afterEach(() => localStorage.clear());

  /** §F/collaboration/events/003027 and 003028: the rows of `Kommend`, the default segment. */
  it('lists the Events of the segment "Kommend" with status, dates, place and link', async () => {
    const { cmp, api, rows } = await setup();
    cmp.onQuery(query({ team: 't-1' }, ' party '));
    expect(api.page).toHaveBeenLastCalledWith({
      team: 't-1',
      series: undefined,
      q: 'party',
      segment: 'upcoming',
      limit: EVENTS_PAGE_SIZE,
      offset: 0,
    });
    const state = rows();
    expect(state.state).toBe('ready');
    if (state.state !== 'ready') return;
    expect(state.more).toBe(true);
    expect(state.data[0]).toMatchObject({
      id: 'e-1',
      title: 'Erstiparty',
      status: { label: 'Geplant', kind: 'neutral' },
      link: { commands: ['/events', 'e-1'] },
    });
    expect(state.data[0].meta).toEqual([expect.stringMatching(/21\.11\.2026, 19:00–02:00$/), 'Hof', 'Kultur']);
    expect(state.data[1]).toMatchObject({ meta: [], status: { label: 'Abgerechnet' } });
  });

  /** §F/collaboration/events/003028: four segments in their order, `Kommend` first, no count. */
  it('offers the segments and the chips Team and Reihe', async () => {
    const { cmp } = await setup();
    const [segment, ...chips] = cmp.filters();
    expect(segment).toMatchObject({ key: 'segment', value: 'upcoming' });
    expect(segment.options.map((o: { label: string }) => o.label)).toEqual(['Kommend', 'Vergangen', 'Erledigt', 'Verworfen']);
    expect(chips.map((f: { key: string }) => f.key)).toEqual(['team', 'series']);
    cmp.onQuery(query({ segment: 'void' }));
    cmp.onQuery(query({ segment: 'nonsense' }));
  });

  it('leaves the chips out with one team and no series', async () => {
    const one = await setup({ teams: [TEAMS[0]], series: [] });
    expect(one.cmp.filters().map((f: { key: string }) => f.key)).toEqual(['segment']);
  });

  it('leaves the chips out when their read failed', async () => {
    const failed = await setup({ teams: null, series: null });
    expect(failed.cmp.filters().map((f: { key: string }) => f.key)).toEqual(['segment']);
    expect(failed.cmp.actions().map((a: { key: string }) => a.key)).toEqual(['export']);
  });

  /** §F/collaboration/events/003027: only a member of a team creates an Event. */
  it.each([
    [TEAMS, ['finance.export'], ['new', 'export']],
    [TEAMS, [], ['new']],
    [[], ['finance.export'], ['export']],
    [[], [], []],
  ])('offers the actions to a person with the teams %j and the permissions %j', async (teams, permissions, keys) => {
    const { cmp } = await setup({ teams, permissions });
    expect(cmp.actions().map((a: { key: string }) => a.key)).toEqual(keys);
  });

  it('reads the next rows and adds them to the list', async () => {
    const { cmp, api, rows } = await setup();
    cmp.onQuery(query());
    cmp.more();
    expect(api.page).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 2 }));
    const state = rows();
    expect(state.state === 'ready' && state.data).toHaveLength(4);
  });

  it('shows the empty state, keeps the old rows while it reads and offers a retry', async () => {
    const { cmp, api, rows } = await setup();
    api.page.mockReturnValueOnce(of({ items: [], total: 0 }));
    cmp.onQuery(query());
    expect(rows()).toMatchObject({ state: 'empty', heading: 'Keine Veranstaltungen' });
    cmp.onQuery(query());
    const late = new Subject<EventPage>();
    api.page.mockReturnValueOnce(late);
    cmp.onQuery(query({ segment: 'past' }));
    expect(rows()).toMatchObject({ state: 'loading' });
    expect((rows() as { previous?: unknown[] }).previous).toHaveLength(2);
    api.page.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.onQuery(query({ segment: 'done' }));
    late.next({ items: [], total: 0 });
    late.error({ status: 500 });
    const failed = rows();
    expect(failed).toMatchObject({ state: 'error', message: 'Die Veranstaltungen konnten nicht geladen werden.' });
    if (failed.state === 'error') failed.retry?.();
    expect(rows()).toMatchObject({ state: 'ready' });
    expect(api.page).toHaveBeenLastCalledWith(expect.objectContaining({ segment: 'done', offset: 0 }));
  });

  it('shows the first read as loading without rows', async () => {
    const { cmp, api, rows } = await setup();
    cmp.events.set([]);
    api.page.mockReturnValueOnce(new Subject<EventPage>());
    cmp.onQuery(query());
    expect(rows()).toEqual({ state: 'loading' });
  });

  /** §F/collaboration/events/003034: the export takes the segment and the filter. */
  it('exports the list with its filter and says when the export fails', async () => {
    const { cmp, api, toast } = await setup();
    const show = jest.spyOn(toast, 'show');
    const created = jest.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: jest.fn() });
    cmp.onQuery(query({ segment: 'past', series: 's-1' }));
    cmp.onAction('new');
    expect(api.exportXlsx).not.toHaveBeenCalled();
    cmp.onAction('export');
    expect(api.exportXlsx).toHaveBeenLastCalledWith({ team: undefined, series: 's-1', q: undefined, segment: 'past' });
    expect(created).toHaveBeenCalled();
    api.exportXlsx.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.onAction('export');
    expect(show).toHaveBeenCalledWith('Der Export ist fehlgeschlagen.', 'error');
  });

  it('reads the list again when the pane changed an Event', async () => {
    const { cmp, api, refresh } = await setup();
    cmp.onQuery(query());
    const before = api.page.mock.calls.length;
    refresh.touch();
    expect(api.page).toHaveBeenCalledTimes(before + 1);
  });
});
