import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import type { TestRequest } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import { mapMeeting } from '@core/api/mappers';
import type { MeetingOutWire } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { WsService } from '@core/ws/ws.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { runAxe } from '../../../../testing/a11y';
import { MeetingAgendaService } from '../meeting-agenda.service';
import { MeetingDialogsService } from '../meeting-dialogs.service';
import { MeetingSessionService } from '../meeting-session.service';
import { OVERVIEW_NOW } from '../meetings-overview.util';
import { MeetingsTimelineService } from '../meetings-timeline.service';
import { MeetingsCalendarComponent, UPCOMING_COUNT } from './meetings-calendar.component';

/** "Now" of the board: Tuesday, 29.09.2026, 18:50. */
const NOW = new Date(2026, 8, 29, 18, 50);

function wire(id: string, title: string, date: string | null, over: Partial<MeetingOutWire> = {}): MeetingOutWire {
  return {
    id,
    title,
    status: 'planned',
    date,
    startTime: '18:00:00',
    endTime: null,
    activeApplicationId: null,
    currentAgendaItemId: null,
    gremiumId: 'g-1',
    gremiumName: 'Studierendenparlament',
    protocolId: null,
    protokollantName: null,
    canManage: true,
    votes: [],
    createdAt: '2026-09-01T00:00:00Z',
    ...over,
  };
}

const LIVE = wire('m-34', '34. Sitzung des Studierendenparlaments', '2026-09-29', {
  status: 'live',
  startedAt: new Date(2026, 8, 29, 18, 4).toISOString(),
  agendaItemCount: 8,
  currentAgendaItem: { position: 3, title: 'Zuschuss Erstsemester-Party' },
  votes: [
    {
      id: 'v-1',
      applicationId: null,
      agendaItemId: null,
      title: null,
      question: null,
      options: [],
      status: 'open',
      result: null,
      counts: null,
      leading: null,
      closesAt: null,
      voted: 14,
      present: 19,
      revealed: false,
    },
  ],
});
const CLOSED = wire('m-33', '33. Sitzung', '2026-09-15', { status: 'closed', startTime: '18:04:00' });
const FA = wire('m-12', '12. Sitzung des Finanzausschusses', '2026-10-02', {
  startTime: '17:30:00',
  gremiumName: 'Finanzausschuss',
  canManage: false,
});
const MONTH = [LIVE, CLOSED, FA];

let restoreMedia: (() => void) | null = null;
afterEach(() => {
  restoreMedia?.();
  restoreMedia = null;
});

async function setup(opts: { wide?: boolean; canCreate?: boolean } = {}) {
  if (opts.wide) restoreMedia = matchMediaQueries(MEDIA.wide);
  const on = { viewChange: jest.fn(), create: jest.fn() };
  const view = await render(MeetingsCalendarComponent, {
    inputs: { canCreate: opts.canCreate ?? true },
    on,
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([{ path: '**', children: [] }]),
      MeetingsTimelineService,
      MeetingDialogsService,
      MeetingSessionService,
      MeetingAgendaService,
      { provide: OVERVIEW_NOW, useValue: () => NOW },
      { provide: USE_MOCK_API, useValue: false },
      {
        provide: AuthService,
        useValue: {
          can: () => false,
          isAdmin: () => false,
          gremien: () => [{ id: 'g-1', name: 'StuPa' }],
          sessionManageGremien: () => ['g-1'],
          inSubstitutePool: () => false,
        },
      },
      { provide: WsService, useValue: {} },
    ],
  });
  const injector = view.fixture.debugElement.injector;
  const http = injector.get(HttpTestingController);
  const timeline = injector.get(MeetingsTimelineService);
  const dialogs = injector.get(MeetingDialogsService);
  const router = injector.get(Router);
  return { ...view, http, timeline, dialogs, router, on };
}

type View = Awaited<ReturnType<typeof setup>>;

function monthReq(http: HttpTestingController): TestRequest {
  return http.expectOne((r) => r.url === '/api/meetings' && r.params.has('dateFrom'));
}

/** Answer the Gremien and the first month. */
function load(view: View, items: MeetingOutWire[] = MONTH, gremien: { id: string; name: string }[] = []): TestRequest {
  view.http.expectOne('/api/meetings/gremien').flush(gremien);
  const req = monthReq(view.http);
  req.flush(items);
  view.fixture.detectChanges();
  return req;
}

// The tests click through whole views; a busy runner needs more than the default 5 s.
jest.setTimeout(15_000);

describe('MeetingsCalendarComponent', () => {
  it('reads the days of the month grid and marks today', async () => {
    const view = await setup();
    const req = load(view);
    expect(req.request.params.get('dateFrom')).toBe('2026-08-31');
    expect(req.request.params.get('dateTo')).toBe('2026-10-04');
    expect(req.request.params.has('gremiumId')).toBe(false);
    expect(screen.getByRole('heading', { name: 'September 2026' })).toBeInTheDocument();
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent?.trim())).toEqual([
      'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So',
    ]);
    expect(screen.getAllByRole('row')).toHaveLength(6);
    const today = screen.getByRole('button', { name: 'Dienstag, 29. September 2026, Heute, 1 Sitzung' });
    expect(today).toHaveAttribute('aria-current', 'date');
    expect(today).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('button', { name: 'Montag, 31. August 2026, keine Sitzung' })).toHaveAttribute('tabindex', '-1');
    expect(today.closest('.cal__cell')).toHaveClass('cal__cell--sel');
    expect(view.container.querySelector('.cal__num--today')?.textContent).toBe('29');
  });

  it('shows the meetings of each day: the time, "Live" and "+n"', async () => {
    const view = await setup();
    load(view, [
      ...MONTH,
      wire('m-a', 'A', '2026-10-02', { startTime: '09:00:00' }),
      wire('m-b', 'B', '2026-10-02', { startTime: null }),
    ]);
    const live = screen.getByRole('button', { name: /29\. September/ }).closest('.cal__cell') as HTMLElement;
    expect(within(live).getByText('Live')).toBeInTheDocument();
    expect(live.querySelector('.cal__entry')).toHaveClass('cal__entry--live');
    const closed = screen.getByRole('button', { name: /15\. September/ }).closest('.cal__cell') as HTMLElement;
    expect(within(closed).getByText('18:04')).toBeInTheDocument();
    expect(closed.querySelector('.cal__entry')).toHaveClass('cal__entry--closed');
    const full = screen.getByRole('button', { name: 'Freitag, 2. Oktober 2026, 3 Sitzungen' }).closest('.cal__cell') as HTMLElement;
    expect(full).toHaveClass('cal__cell--out');
    expect(Array.from(full.querySelectorAll('.cal__entryTitle')).map((e) => e.textContent)).toEqual([
      'A',
      '12. Sitzung des Finanzausschusses',
    ]);
    expect(within(full).getByText('+1 weitere')).toBeInTheDocument();
  });

  it('shows the selected live meeting with its item, the turnout and its actions', async () => {
    const view = await setup();
    load(view);
    const panel = screen.getByRole('complementary', { name: 'Gewählter Tag' });
    expect(within(panel).getByRole('heading', { name: 'Di., 29.09.2026 · Heute' })).toBeInTheDocument();
    const card = within(panel).getByRole('article', { name: '34. Sitzung des Studierendenparlaments' });
    expect(within(card).getByText('seit 18:04')).toBeInTheDocument();
    expect(within(card).getByText('TOP 3 von 8')).toBeInTheDocument();
    expect(within(card).getByText('38 %')).toBeInTheDocument();
    expect(within(card).getByText('Zuschuss Erstsemester-Party')).toBeInTheDocument();
    expect(within(card).getByText('14 / 19')).toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: /Sitzung öffnen/ }));
    await view.fixture.whenStable();
    expect(view.router.url).toBe('/meetings/m-34');
    const open = jest.spyOn(window, 'open').mockImplementation(() => null);
    await userEvent.click(within(card).getByRole('button', { name: /Beamer/ }));
    expect(open).toHaveBeenCalledWith('/voting/beamer/m-34', '_blank', 'noopener');
    open.mockRestore();
    const menu = async () => {
      await userEvent.click(within(card).getByRole('button', { name: /Weitere Aktionen/ }));
      return screen.findByRole('menu');
    };
    await userEvent.click(within(await menu()).getByRole('menuitem', { name: 'Sitzung bearbeiten' }));
    expect(view.dialogs.settingsMeeting()?.id).toBe('m-34');
    await userEvent.click(within(await menu()).getByRole('menuitem', { name: 'Sitzung löschen' }));
    expect(view.dialogs.deleteMeeting()?.id).toBe('m-34');
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('selects a day on a click; a day of another month shows that month', async () => {
    const view = await setup();
    load(view);
    await userEvent.click(screen.getByRole('button', { name: /15\. September/ }));
    const panel = screen.getByRole('complementary');
    expect(within(panel).getByRole('heading', { name: 'Di., 15.09.2026' })).toBeInTheDocument();
    const card = within(panel).getByRole('article', { name: '33. Sitzung' });
    // A closed meeting has no beamer; no live facts.
    expect(within(card).queryByRole('button', { name: /Beamer/ })).toBeNull();
    expect(within(card).queryByText(/TOP \d von/)).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /16\. September/ }));
    expect(within(panel).getByText('Keine Sitzung an diesem Tag.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /2\. Oktober/ }));
    expect(screen.getByRole('heading', { name: 'Oktober 2026' })).toBeInTheDocument();
    const req = monthReq(view.http);
    expect(req.request.params.get('dateFrom')).toBe('2026-09-28');
    expect(req.request.params.get('dateTo')).toBe('2026-11-01');
    req.flush([FA]);
    view.fixture.detectChanges();
    const fa = within(panel).getByRole('article', { name: '12. Sitzung des Finanzausschusses' });
    expect(within(fa).queryByRole('button', { name: /Weitere Aktionen/ })).toBeNull();
    expect(within(fa).queryByRole('button', { name: /Beamer/ })).toBeNull();
  });

  it('moves a month back and on, keeps the day where it can, and goes back to today', async () => {
    const view = await setup();
    load(view);
    await userEvent.click(screen.getByRole('button', { name: /31\. August/ }));
    monthReq(view.http).flush([]);
    expect(screen.getByRole('heading', { name: 'August 2026' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Nächster Monat' }));
    // Until the month arrives, an empty day shows a placeholder.
    expect(view.container.querySelector('.cal__daySec .skel')).not.toBeNull();
    monthReq(view.http).flush([]);
    view.fixture.detectChanges();
    // 31 does not exist in September: the last day.
    expect(screen.getByRole('heading', { name: 'Mi., 30.09.2026' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Voriger Monat' }));
    monthReq(view.http).flush([]);
    view.fixture.detectChanges();
    expect(screen.getByRole('heading', { name: 'So., 30.08.2026' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Heute' }));
    monthReq(view.http).flush(MONTH);
    view.fixture.detectChanges();
    expect(screen.getByRole('heading', { name: 'September 2026' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Di., 29.09.2026 · Heute' })).toBeInTheDocument();
  });

  it('moves the selected day with the arrow keys, Home and End', async () => {
    const view = await setup();
    load(view);
    const grid = screen.getByRole('grid');
    const sel = () => grid.querySelector('.cal__cell--sel .cal__day')?.getAttribute('aria-label');
    fireEvent.keyDown(grid, { key: 'ArrowLeft' });
    view.fixture.detectChanges();
    expect(sel()).toMatch(/^Montag, 28\. September/);
    fireEvent.keyDown(grid, { key: 'ArrowRight' });
    fireEvent.keyDown(grid, { key: 'End' });
    view.fixture.detectChanges();
    expect(sel()).toMatch(/^Sonntag, 4\. Oktober/);
    // The day of another month shows that month.
    monthReq(view.http).flush([]);
    fireEvent.keyDown(grid, { key: 'Home' });
    fireEvent.keyDown(grid, { key: 'ArrowUp' });
    view.fixture.detectChanges();
    expect(sel()).toMatch(/^Montag, 21\. September/);
    monthReq(view.http).flush([]);
    fireEvent.keyDown(grid, { key: 'ArrowDown' });
    fireEvent.keyDown(grid, { key: 'Enter' });
    view.fixture.detectChanges();
    expect(sel()).toMatch(/^Montag, 28\. September/);
    await view.fixture.whenStable();
    expect(document.activeElement).toBe(grid.querySelector('.cal__cell--sel .cal__day'));
  });

  it('lists the upcoming meetings without the live one; a click shows their day', async () => {
    const view = await setup();
    load(view);
    const upcoming = [LIVE, FA, ...Array.from({ length: 6 }, (_, i) => wire(`m-u${i}`, `Kommend ${i}`, `2026-10-${10 + i}`))];
    view.timeline.upcomingItems.set(upcoming.map(mapMeeting));
    view.fixture.detectChanges();
    const list = within(screen.getByRole('region', { name: 'Anstehend' })).getAllByRole('listitem');
    expect(list).toHaveLength(UPCOMING_COUNT);
    expect(within(list[0]).getByText('Fr, 17:30')).toBeInTheDocument();
    expect(within(list[0]).getByText('keine TOPs')).toBeInTheDocument();
    await userEvent.click(within(list[1]).getByRole('button', { name: 'Kommend 0' }));
    expect(screen.getByRole('heading', { name: 'Oktober 2026' })).toBeInTheDocument();
    monthReq(view.http).flush([]);
    view.fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Kommend 0' })).toHaveAttribute('aria-current', 'true');
    // A meeting without a date has no day to show; one without a time shows its weekday.
    const cmp = view.fixture.componentInstance;
    cmp.showMeeting({ ...view.timeline.upcomingItems()[0], date: null });
    expect(cmp.rowTime({ ...view.timeline.upcomingItems()[0], startTime: null })).toBe('Di');
    expect(cmp.rowTime({ ...view.timeline.upcomingItems()[0], date: null })).toBe('18:00');
    expect(cmp.tops({ ...view.timeline.upcomingItems()[0], agendaItemCount: undefined })).toBe('keine TOPs');
  });

  it('filters the grid and the upcoming list by the search of the overview', async () => {
    const view = await setup();
    load(view);
    view.timeline.searchQuery.set('finanz');
    view.fixture.detectChanges();
    expect(view.container.querySelectorAll('.cal__entry')).toHaveLength(1);
    expect(screen.getByText('Keine Sitzung an diesem Tag.')).toBeInTheDocument();
    const onSearch = jest.spyOn(view.timeline, 'onSearch').mockImplementation(() => undefined);
    await userEvent.type(screen.getByRole('searchbox'), 'x');
    expect(onSearch).toHaveBeenCalled();
  });

  it('reads the month again for another Gremium and drops a late answer', async () => {
    const view = await setup();
    load(view, MONTH, [{ id: 'g-1', name: 'StuPa' }, { id: 'g-2', name: 'Finanzausschuss' }]);
    await userEvent.click(screen.getByRole('button', { name: 'Gremium: Alle Gremien' }));
    await userEvent.click(within(screen.getByRole('listbox', { name: 'Gremium' })).getByRole('option', { name: 'Finanzausschuss' }));
    view.fixture.detectChanges();
    const first = monthReq(view.http);
    expect(first.request.params.get('gremiumId')).toBe('g-2');
    view.http.match((r) => r.url === '/api/meetings/timeline');
    view.timeline.gremiumFilter.set('g-gone');
    view.fixture.detectChanges();
    const second = monthReq(view.http);
    // The late answer of the first request changes nothing.
    first.flush([FA]);
    second.flush(null, { status: 500, statusText: 'e' });
    view.fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('Die Sitzungen des Monats konnten nicht geladen werden.');
    expect(screen.getByRole('button', { name: 'Gremium: Alle Gremien' })).toBeInTheDocument();
    view.timeline.gremiumFilter.set('');
    view.fixture.detectChanges();
    const third = monthReq(view.http);
    view.timeline.gremiumFilter.set('g-1');
    view.fixture.detectChanges();
    third.flush(null, { status: 500, statusText: 'e' });
    monthReq(view.http).flush(MONTH);
    view.fixture.detectChanges();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('applies a saved or deleted meeting to the month', async () => {
    const view = await setup();
    load(view);
    const live = view.fixture.componentInstance.items().find((m) => m.id === 'm-34');
    view.timeline.replaceInTimeline({ ...live!, title: '34. Sitzung (neu)' });
    view.fixture.detectChanges();
    expect(screen.getByRole('article', { name: '34. Sitzung (neu)' })).toBeInTheDocument();
    view.timeline.removeFromTimeline('m-34');
    view.fixture.detectChanges();
    expect(screen.getByText('Keine Sitzung an diesem Tag.')).toBeInTheDocument();
  });

  it('switches the view, creates a meeting and links the calendar subscription', async () => {
    const view = await setup({ wide: true });
    load(view);
    expect(view.fixture.nativeElement).toHaveClass('cal--wide');
    await userEvent.click(screen.getByRole('radio', { name: 'Liste' }));
    expect(view.on.viewChange).toHaveBeenCalledWith('list');
    await userEvent.click(screen.getByRole('button', { name: 'Neue Sitzung' }));
    expect(view.on.create).toHaveBeenCalled();
    expect(screen.getByRole('link', { name: 'Kalender-Abo' })).toHaveAttribute('href', '/account/calendar');
    view.fixture.componentRef.setInput('canCreate', false);
    view.fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Neue Sitzung' })).toBeNull();
  });
});
