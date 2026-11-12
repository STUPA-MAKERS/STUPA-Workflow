import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import type { TestRequest } from '@angular/common/http/testing';
import { Meta } from '@angular/platform-browser';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of } from 'rxjs';
import type { CalendarEntry } from '@core/api/calendar.service';
import { AuthService } from '@core/auth/auth.service';
import { LIVE_SEARCH_DEBOUNCE_MS, MEDIA, PageFrame } from '@stupa-makers/ui-kit';
import { appointment, calendarEntry } from '../../../testing/calendar-fixtures';
import { runAxe } from '../../../testing/a11y';
import { errorToasts, loadErrorToast, retryLoadError } from '../../../testing/load-error';
import { matchMediaQueries } from '../../../testing/meeting-fixtures';
import { CALENDAR_NOW } from './calendar-grid.util';
import { CalendarComponent } from './calendar.component';
import { VIEW_STORAGE_KEY } from './calendar.util';

/** "Now" of the tests: Wednesday, 11.11.2026, 10:00. */
const NOW = new Date(2026, 10, 11, 10, 0);

const MEETING = calendarEntry('m-35', {
  kind: 'meeting',
  title: '35. Sitzung',
  startsOn: '2026-11-12',
  endsOn: '2026-11-12',
  startTime: '18:00:00',
  endTime: '20:00:00',
  source: 'Studierendenparlament',
  gremiumIds: ['g-1'],
});
const CARD = calendarEntry('c-1', { kind: 'card', title: 'Angebot einholen', source: 'AStA-Board', mine: true });
const TERMIN = calendarEntry('a-1', {
  title: 'Jour fixe',
  startTime: '14:00:00',
  endTime: '15:30:00',
  place: 'AStA-Büro',
  source: 'Haushaltsausschuss',
  gremiumIds: ['g-2'],
  mine: true,
  myAnswer: 'accept',
});
const PRIVATE = calendarEntry('a-2', { title: 'Zahnarzt', startTime: '08:00:00' });
const SPAN = calendarEntry('a-3', { title: 'Klausurtagung', startsOn: '2026-11-17', endsOn: '2026-11-19' });
const EVENT = calendarEntry('e-1', {
  kind: 'event',
  title: 'Infoabend',
  startsOn: '2026-11-13',
  endsOn: '2026-11-13',
  startTime: '19:00:00',
  endTime: '20:30:00',
});
const MONTH = [CARD, PRIVATE, TERMIN, MEETING, EVENT, SPAN];
const GREMIEN = [
  { id: 'g-1', name: 'Studierendenparlament' },
  { id: 'g-2', name: 'Haushaltsausschuss' },
];

let restoreMedia: (() => void) | null = null;
afterEach(() => {
  restoreMedia?.();
  restoreMedia = null;
  localStorage.clear();
});

async function setup(
  opts: { media?: string[]; view?: string; url?: string; now?: () => Date; public?: boolean } = {},
) {
  if (opts.media) restoreMedia = matchMediaQueries(...opts.media);
  if (opts.view) localStorage.setItem(VIEW_STORAGE_KEY, opts.view);
  const view = await render(CalendarComponent, {
    initialRoute: opts.url ?? '/calendar',
    routes: [{ path: '**', children: [] }],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      { provide: CALENDAR_NOW, useValue: opts.now ?? (() => NOW) },
      { provide: AuthService, useValue: { can: () => false } },
      ...(opts.public
        ? [
            {
              provide: ActivatedRoute,
              useValue: { snapshot: { data: { public: true } }, queryParamMap: of(convertToParamMap({})) },
            },
          ]
        : []),
    ],
  });
  const injector = view.fixture.debugElement.injector;
  const http = injector.get(HttpTestingController);
  const router = injector.get(Router);
  const frame = injector.get(PageFrame);
  return { ...view, http, router, frame, cmp: view.fixture.componentInstance };
}

type View = Awaited<ReturnType<typeof setup>>;

function entriesReqs(view: View): TestRequest[] {
  return view.http.match((r) => r.url === '/api/calendar/entries');
}

/** Answer the Gremien and the first read of the entries. */
function load(view: View, items: readonly CalendarEntry[] = MONTH, gremien = GREMIEN): TestRequest {
  view.http.match('/api/meetings/committees').forEach((r) => r.flush(gremien));
  const [req, ...rest] = entriesReqs(view);
  expect(rest.length).toBe(0);
  req.flush({ items });
  view.fixture.detectChanges();
  return req;
}

/** Answer the next read of the entries. */
function reload(view: View, items: readonly CalendarEntry[] = MONTH): TestRequest {
  const [req, ...rest] = entriesReqs(view);
  expect(rest.length).toBe(0);
  req.flush({ items });
  view.fixture.detectChanges();
  return req;
}

const cell = (name: RegExp) => screen.getByRole('button', { name }).closest('.cal__cell') as HTMLElement;
const panel = () => screen.getByRole('complementary');
const cards = () => within(panel()).queryAllByRole('button').map((b) => b.querySelector('.cal__cardTitle')?.textContent);

jest.setTimeout(20_000);

describe('CalendarComponent (desktop)', () => {
  it('reads the days of the month grid and marks today', async () => {
    const view = await setup();
    expect(view.container.querySelector('app-skeleton')).not.toBeNull();
    const req = load(view);
    expect(req.request.params.get('from')).toBe('2026-10-26');
    expect(req.request.params.get('to')).toBe('2026-12-06');
    expect(req.request.params.has('mine')).toBe(false);
    expect(view.container.querySelector('app-skeleton')).toBeNull();
    expect(screen.getByRole('heading', { name: 'Kalender' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'November 2026' })).toBeInTheDocument();
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent?.trim())).toEqual([
      'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So',
    ]);
    const today = screen.getByRole('button', { name: 'Mittwoch, 11. November 2026, Heute, 3 Einträge' });
    expect(today).toHaveAttribute('aria-current', 'date');
    expect(today).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('button', { name: 'Donnerstag, 12. November 2026, 1 Eintrag' })).toHaveAttribute('tabindex', '-1');
    expect(screen.getByRole('button', { name: 'Montag, 26. Oktober 2026, keine Einträge' })).toBeInTheDocument();
    expect(today.closest('.cal__cell')).toHaveClass('cal__cell--sel');
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('shows the entries of each day with the kind or the time, and "+n" for the rest', async () => {
    const view = await setup();
    load(view);
    const today = cell(/11\. November/);
    expect(Array.from(today.querySelectorAll('.cal__entryTitle')).map((e) => e.textContent)).toEqual([
      'Angebot einholen',
      'Zahnarzt',
    ]);
    expect(Array.from(today.querySelectorAll('.cal__entryTime')).map((e) => e.textContent?.trim())).toEqual([
      'Karte',
      '08:00',
    ]);
    expect(within(today).getByText('+1 weitere')).toBeInTheDocument();
    expect(within(cell(/12\. November/)).getByText('18:00 – 20:00')).toBeInTheDocument();
    expect(view.container.querySelectorAll('.cal__more')).toHaveLength(1);
  });

  /** § 000726: an entry over several days is one bar across its days. */
  it('draws a three-day Termin as one bar across its days', async () => {
    const view = await setup();
    load(view);
    const bars = view.container.querySelectorAll<HTMLElement>('.cal__bar');
    expect(bars).toHaveLength(1);
    expect(bars[0]).toHaveTextContent('Klausurtagung');
    expect(bars[0].style.gridColumn).toBe('2 / 5');
    expect(cell(/17\. November/).querySelector('.cal__entry')).toBeNull();
    expect(screen.getByRole('button', { name: 'Mittwoch, 18. November 2026, 1 Eintrag' })).toBeInTheDocument();
  });

  it('shows the entries of the picked day as cards', async () => {
    const view = await setup();
    load(view);
    expect(panel()).toHaveAccessibleName('Mi, 11.11.2026 · Heute');
    expect(cards()).toEqual(['Angebot einholen', 'Zahnarzt', 'Jour fixe']);
    const termin = within(panel()).getByRole('button', { name: /Jour fixe/ });
    expect(termin).toHaveTextContent('Termin');
    expect(termin).toHaveTextContent('14:00 – 15:30');
    expect(termin).toHaveTextContent('Haushaltsausschuss · AStA-Büro');
    expect(termin).toHaveTextContent('Zusage');
    expect(within(panel()).getByRole('button', { name: /Angebot einholen/ })).not.toHaveTextContent('Ganztägig');
    await userEvent.click(screen.getByRole('button', { name: /14\. November/ }));
    expect(panel()).toHaveAccessibleName('Sa, 14.11.2026');
    expect(within(panel()).getByText('Keine Einträge an diesem Tag.')).toBeInTheDocument();
    expect(view.http.match(() => true).length).toBe(0);
  });

  /** § 000714: a card entry opens the card, a meeting entry opens the meeting. */
  it('opens the card of a card entry and the page of a meeting', async () => {
    const view = await setup();
    load(view);
    await userEvent.click(within(panel()).getByRole('button', { name: /Angebot einholen/ }));
    await view.fixture.whenStable();
    expect(view.router.url).toBe('/todos?card=c-1');
    view.cmp.openEntry(MEETING);
    await view.fixture.whenStable();
    expect(view.router.url).toBe('/meetings/m-35');
    view.cmp.openEntry(EVENT);
    await view.fixture.whenStable();
    expect(view.router.url).toBe('/todos?card=e-1');
  });

  it('opens a Termin in the dialog and keeps its answer in the card', async () => {
    const view = await setup();
    load(view);
    await userEvent.click(within(panel()).getByRole('button', { name: /Jour fixe/ }));
    view.http.expectOne('/api/calendar/appointments/a-1').flush(appointment({ myAnswer: 'accept' }));
    view.fixture.detectChanges();
    const dialog = await screen.findByRole('dialog', { name: 'Jour fixe' });
    await userEvent.click(within(dialog).getByRole('radio', { name: 'Absage' }));
    view.http.expectOne('/api/calendar/appointments/a-1/answer').flush(appointment({ myAnswer: 'decline' }));
    view.fixture.detectChanges();
    expect(view.cmp.detail()?.myAnswer).toBe('decline');
    expect(view.cmp.items().find((e) => e.id === 'a-1')?.myAnswer).toBe('decline');
    expect(view.cmp.items().find((e) => e.id === 'a-2')?.myAnswer).toBeNull();
    view.cmp.closeDetail();
    expect(view.cmp.detailOpen()).toBe(false);
    expect(view.router.url).toBe('/calendar');
  });

  /** § 000714: an external entry opens read-only, with the name of its calendar. */
  it('opens an external entry in a read-only dialog', async () => {
    const view = await setup();
    const extern = calendarEntry('x-1', { kind: 'external', title: 'Senatssitzung', source: 'Senatstermine' });
    load(view, [...MONTH, extern]);
    await userEvent.click(within(panel()).getByRole('button', { name: /Senatssitzung/ }));
    view.http.expectOne('/api/calendar/external/x-1').flush({
      id: 'x-1',
      title: 'Senatssitzung',
      startsOn: '2026-11-11',
      endsOn: '2026-11-11',
      startTime: '14:00:00',
      endTime: '17:00:00',
      place: 'Raum 113',
      description: 'Öffentlicher Teil',
      calendar: 'Senatstermine',
    });
    view.fixture.detectChanges();
    const dialog = await screen.findByRole('dialog', { name: 'Senatssitzung' });
    expect(within(dialog).getByText('Mi, 11.11.2026 · 14:00 – 17:00')).toBeInTheDocument();
    expect(within(dialog).getByText('Raum 113')).toBeInTheDocument();
    expect(within(dialog).getByText('Senatstermine')).toBeInTheDocument();
    expect(within(dialog).getByText('Öffentlicher Teil')).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Bearbeiten' })).toBeNull();
    expect(within(dialog).queryByRole('radio')).toBeNull();
    view.cmp.openEntry(extern);
    view.http.expectOne('/api/calendar/external/x-1').flush(null, { status: 404, statusText: 'Not Found' });
    expect(errorToasts()).toEqual(['Der Eintrag ließ sich nicht laden.']);
  });

  it('reports a Termin that cannot be read', async () => {
    const view = await setup();
    load(view);
    view.cmp.openEntry(TERMIN);
    view.http.expectOne('/api/calendar/appointments/a-1').flush(null, { status: 404, statusText: 'Not Found' });
    expect(errorToasts()).toEqual(['Der Termin konnte nicht geladen werden.']);
    expect(view.cmp.detailOpen()).toBe(false);
  });

  it('moves a month back and on, keeps the day of the month and goes back to today', async () => {
    const view = await setup();
    load(view);
    view.cmp.selectDay('2026-10-31');
    view.fixture.detectChanges();
    expect(screen.getByRole('heading', { name: 'Oktober 2026' })).toBeInTheDocument();
    expect(reload(view, []).request.params.get('from')).toBe('2026-09-28');
    await userEvent.click(screen.getByRole('button', { name: 'Nächster Monat' }));
    expect(screen.getByRole('heading', { name: 'November 2026' })).toBeInTheDocument();
    expect(view.cmp.selectedDay()).toBe('2026-11-30');
    reload(view);
    await userEvent.click(screen.getByRole('button', { name: 'Voriger Monat' }));
    expect(view.cmp.selectedDay()).toBe('2026-10-30');
    reload(view, []);
    await userEvent.click(screen.getByRole('button', { name: 'Heute' }));
    expect(view.cmp.selectedDay()).toBe('2026-11-11');
    expect(screen.getByRole('heading', { name: 'November 2026' })).toBeInTheDocument();
    reload(view);
    view.cmp.selectDay('no day');
    expect(view.cmp.selectedDay()).toBe('2026-11-11');
  });

  it('drops the answer of a read that a newer read replaced', async () => {
    const view = await setup();
    view.http.match('/api/meetings/committees').forEach((r) => r.flush(null, { status: 500, statusText: 'Error' }));
    const [first] = entriesReqs(view);
    view.cmp.step(1);
    view.fixture.detectChanges();
    const [second] = entriesReqs(view);
    first.flush({ items: MONTH });
    expect(view.cmp.items()).toEqual([]);
    expect(view.cmp.loading()).toBe(true);
    view.cmp.step(1);
    view.fixture.detectChanges();
    second.flush(null, { status: 500, statusText: 'Error' });
    expect(view.cmp.error()).toBe(false);
    reload(view, []);
    expect(view.cmp.loading()).toBe(false);
    expect(view.cmp.gremiumOptions()).toHaveLength(1);
  });

  it('moves the picked day with the keys and keeps the focus on it', async () => {
    const view = await setup();
    load(view);
    const grid = screen.getByRole('grid');
    const press = async (key: string) => {
      fireEvent.keyDown(grid, { key });
      view.fixture.detectChanges();
      await view.fixture.whenStable();
    };
    await press('ArrowRight');
    expect(view.cmp.selectedDay()).toBe('2026-11-12');
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /12\. November/ }));
    await press('ArrowDown');
    expect(view.cmp.selectedDay()).toBe('2026-11-19');
    await press('ArrowUp');
    await press('ArrowLeft');
    expect(view.cmp.selectedDay()).toBe('2026-11-11');
    await press('Home');
    expect(view.cmp.selectedDay()).toBe('2026-11-09');
    await press('End');
    expect(view.cmp.selectedDay()).toBe('2026-11-15');
    await press('a');
    expect(view.cmp.selectedDay()).toBe('2026-11-15');
    view.cmp.selectedDay.set('no day');
    await press('ArrowLeft');
    expect(view.cmp.selectedDay()).toBe('no day');
    expect(view.http.match(() => true).length).toBe(0);
  });

  /** § 000713: a picked Gremium hides the entries without a Gremium. */
  it('hides a private Termin when a Gremium is picked', async () => {
    const view = await setup();
    load(view);
    expect(view.cmp.gremiumOptions().map((o) => o.label)).toEqual(['Alle Gremien', 'Studierendenparlament', 'Haushaltsausschuss']);
    expect(view.cmp.gremiumText()).toBe('Alle Gremien');
    expect(cards()).toContain('Zahnarzt');
    view.cmp.gremium.set('g-2');
    view.fixture.detectChanges();
    expect(view.cmp.gremiumText()).toBe('Haushaltsausschuss');
    expect(cards()).toEqual(['Jour fixe']);
    expect(view.container.querySelector('.cal__bar')).toBeNull();
    view.cmp.gremium.set('gone');
    expect(view.cmp.gremiumText()).toBe('');
    expect(view.http.match(() => true).length).toBe(0);
  });

  it('filters by kind in the browser and asks the server for "Nur meine"', async () => {
    const view = await setup();
    load(view);
    expect(view.cmp.kindOptions().map((o) => o.label)).toEqual(['Sitzung', 'Karte', 'Termin', 'Extern']);
    expect(view.cmp.mineOptions().map((o) => o.label)).toEqual(['Alle Einträge', 'Nur meine']);
    view.cmp.kinds.set(['card']);
    view.fixture.detectChanges();
    expect(cards()).toEqual(['Angebot einholen']);
    expect(view.http.match(() => true).length).toBe(0);
    view.cmp.kinds.set([]);
    view.cmp.mine.set('mine');
    view.fixture.detectChanges();
    const req = reload(view, [CARD, TERMIN]);
    expect(req.request.params.get('mine')).toBe('true');
    expect(cards()).toEqual(['Angebot einholen', 'Jour fixe']);
  });

  it('shows no Gremium filter to a person without a Gremium', async () => {
    const view = await setup();
    load(view, MONTH, []);
    expect(screen.queryByRole('button', { name: /Gremium/ })).toBeNull();
    expect(screen.getByRole('button', { name: /Art/ })).toBeInTheDocument();
  });

  /** § 000728: the week view, kept per browser. */
  it('switches to the week view, keeps it and reads the week', async () => {
    const view = await setup();
    load(view);
    await userEvent.click(screen.getByRole('radio', { name: 'Woche' }));
    expect(localStorage.getItem(VIEW_STORAGE_KEY)).toBe('week');
    const req = reload(view);
    expect(req.request.params.get('from')).toBe('2026-11-09');
    expect(req.request.params.get('to')).toBe('2026-11-15');
    expect(screen.getByRole('heading', { name: '09.11. – 15.11.2026' })).toBeInTheDocument();
    const week = view.container.querySelector('app-calendar-week') as HTMLElement;
    const columns = week.querySelectorAll<HTMLElement>('.cw__col');
    expect(within(columns[2]).getByRole('button', { name: '14:00 – 15:30 Jour fixe' })).toBeInTheDocument();
    const allDay = week.querySelectorAll<HTMLElement>('.cw__cell');
    expect(within(allDay[2]).getByRole('button', { name: /Angebot einholen/ })).toBeInTheDocument();

    await userEvent.click(within(week).getByRole('button', { name: /13\. November 2026/ }));
    expect(view.cmp.selectedDay()).toBe('2026-11-13');
    await userEvent.click(screen.getByRole('button', { name: 'Nächste Woche' }));
    expect(view.cmp.selectedDay()).toBe('2026-11-20');
    expect(reload(view, []).request.params.get('from')).toBe('2026-11-16');
    await userEvent.click(screen.getByRole('button', { name: 'Vorige Woche' }));
    reload(view);
    await userEvent.click(within(week).getByRole('button', { name: '14:00 – 15:30 Jour fixe' }));
    view.http.expectOne('/api/calendar/appointments/a-1').flush(appointment());
    view.cmp.setView(null);
    expect(view.cmp.view()).toBe('month');
    view.fixture.detectChanges();
    reload(view);
  });

  /** § 000737: an Event is a block at its time and counts to the kind Termin. */
  it('shows a timed Event as a block in the week view, also with the filter Termin', async () => {
    const view = await setup({ view: 'week' });
    load(view);
    const column = () => view.container.querySelectorAll<HTMLElement>('.cw__col')[4];
    expect(within(column()).getByRole('button', { name: '19:00 – 20:30 Infoabend' }).style.top).toBe('66.5rem');
    view.cmp.kinds.set(['appointment']);
    view.fixture.detectChanges();
    expect(within(column()).getByRole('button', { name: '19:00 – 20:30 Infoabend' })).toBeInTheDocument();
    expect(view.cmp.visible().map((e) => e.id)).toEqual(['a-2', 'a-1', 'e-1', 'a-3']);
    expect(view.cmp.kindOptions().map((o) => o.value)).not.toContain('event');
  });

  it('creates a Termin on the picked day and shows it at once', async () => {
    const view = await setup();
    load(view);
    await userEvent.click(screen.getByRole('button', { name: /14\. November/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Termin anlegen' }));
    view.http.match('/api/meetings/committees').forEach((r) => r.flush(GREMIEN));
    const dialog = await screen.findByRole('dialog', { name: 'Termin anlegen' });
    await userEvent.type(within(dialog).getByLabelText(/Titel/), 'Neu');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Anlegen' }));
    const req = view.http.expectOne('/api/calendar/appointments');
    expect(req.request.body).toMatchObject({ title: 'Neu', startsOn: '2026-11-14', endsOn: '2026-11-14' });
    req.flush(
      appointment({ id: 'a-9', title: 'Neu', startsOn: '2026-11-14', endsOn: '2026-11-14', startTime: null, endTime: null, gremien: [] }),
    );
    view.fixture.detectChanges();
    expect(view.cmp.formOpen()).toBe(false);
    expect(cards()).toEqual(['Neu']);
    reload(view);
  });

  it('opens the edit dialog from the detail and closes the detail after a delete', async () => {
    const view = await setup();
    load(view);
    view.cmp.openEntry(TERMIN);
    view.http.expectOne('/api/calendar/appointments/a-1').flush(appointment());
    view.cmp.editAppointment(appointment());
    expect(view.cmp.detailOpen()).toBe(false);
    expect(view.cmp.formOpen()).toBe(true);
    expect(view.cmp.editing()?.id).toBe('a-1');
    view.cmp.onRemoved(appointment());
    expect(view.cmp.items().some((e) => e.id === 'a-1')).toBe(false);
    expect(view.cmp.items().some((e) => e.id === 'a-2')).toBe(true);
    view.cmp.createAppointment();
    expect(view.cmp.editing()).toBeNull();
    view.http.match('/api/meetings/committees').forEach((r) => r.flush([]));
  });

  it('opens the Termin of a mail link and removes the link on close', async () => {
    const view = await setup({ url: '/calendar?appointment=a-1' });
    load(view);
    view.http.expectOne('/api/calendar/appointments/a-1').flush(appointment());
    view.fixture.detectChanges();
    expect(await screen.findByRole('dialog', { name: 'Jour fixe' })).toBeInTheDocument();
    view.cmp.closeDetail();
    await view.fixture.whenStable();
    expect(view.router.url).toBe('/calendar');
  });

  it('shows a failed read as an error with a retry', async () => {
    const view = await setup();
    view.http.match('/api/meetings/committees').forEach((r) => r.flush([]));
    entriesReqs(view)[0].flush(null, { status: 500, statusText: 'Error' });
    view.fixture.detectChanges();
    expect(loadErrorToast()).toBe('Der Kalender konnte nicht geladen werden.');
    retryLoadError();
    reload(view);
    expect(cards()).toEqual(['Angebot einholen', 'Zahnarzt', 'Jour fixe']);
  });

  it('opens the calendar subscription from the header', async () => {
    const view = await setup();
    load(view);
    await userEvent.click(screen.getByRole('button', { name: 'Kalender-Abo' }));
    view.http.expectOne('/api/calendar/me').flush({ url: 'https://x/api/calendar/T.ics' });
    view.fixture.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Kalender-Abo' })).toHaveTextContent('https://x/api/calendar/T.ics');
  });

  it('fills the page when wide and frees it again', async () => {
    const view = await setup({ media: [MEDIA.wide] });
    load(view);
    expect(view.frame.fill()).toBe(true);
    expect(view.fixture.nativeElement).toHaveClass('cal--wide');
    view.fixture.destroy();
    expect(view.frame.fill()).toBe(false);
  });

  it('moves today on at midnight', async () => {
    jest.useFakeTimers();
    try {
      const clock = { now: new Date(2026, 10, 11, 23, 59, 30) };
      const view = await setup({ now: () => clock.now });
      expect(view.cmp.todayIso()).toBe('2026-11-11');
      clock.now = new Date(2026, 10, 12, 0, 0, 1);
      jest.advanceTimersByTime(30_000);
      expect(view.cmp.todayIso()).toBe('2026-11-12');
      clock.now = new Date(2026, 10, 13, 0, 0, 1);
      jest.advanceTimersByTime(24 * 3600_000);
      expect(view.cmp.todayIso()).toBe('2026-11-13');
      view.fixture.destroy();
      expect(jest.getTimerCount()).toBe(0);
    } finally {
      jest.useRealTimers();
    }
  });
});

describe('CalendarComponent (search)', () => {
  const OTHER = calendarEntry('m-40', {
    kind: 'meeting',
    title: '40. Sitzung',
    startsOn: '2027-02-03',
    endsOn: '2027-02-03',
    startTime: '18:00:00',
    source: 'Studierendenparlament',
  });
  const HITS = [MEETING, OTHER, SPAN];

  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  function type(view: View, text: string): void {
    fireEvent.input(screen.getByRole('searchbox'), { target: { value: text } });
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    view.fixture.detectChanges();
  }

  function answer(view: View, items: readonly CalendarEntry[]): TestRequest {
    const req = view.http.expectOne((r) => r.url === '/api/calendar/search');
    req.flush({ items });
    view.fixture.detectChanges();
    return req;
  }

  /** § 000727: the search asks the server, and a hit shows its month and picks its day. */
  it('lists the hits of every month and jumps to the month and the day of a hit', async () => {
    const view = await setup();
    load(view);
    type(view, 's');
    view.http.expectNone((r) => r.url === '/api/calendar/search');
    expect(screen.queryByRole('listbox')).toBeNull();
    type(view, 'sitzung');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(answer(view, HITS).request.params.get('q')).toBe('sitzung');
    const options = within(screen.getByRole('listbox', { name: 'Treffer' })).getAllByRole('option');
    expect(options.map((o) => o.querySelector('.cal__hitTitle')?.textContent)).toEqual(['35. Sitzung', '40. Sitzung', 'Klausurtagung']);
    expect(options[0]).toHaveTextContent('Do, 12.11.2026 · 18:00 – 20:00 · Sitzung · Studierendenparlament');
    expect(options[2].querySelector('.cal__hitSub')?.textContent?.replace(/\s+/g, ' ').trim()).toBe('Di, 17.11.2026 · Termin');
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
    expect(view.container.querySelectorAll('.cal__entry').length).toBeGreaterThan(0);

    const box = view.container.querySelector('.cal__searchBox') as HTMLElement;
    fireEvent.keyDown(box, { key: 'ArrowUp' });
    expect(view.cmp.activeHit()).toBe(2);
    fireEvent.keyDown(box, { key: 'ArrowDown' });
    fireEvent.keyDown(box, { key: 'ArrowDown' });
    fireEvent.keyDown(box, { key: 'x' });
    expect(view.cmp.activeHit()).toBe(1);
    fireEvent.keyDown(box, { key: 'Enter' });
    view.fixture.detectChanges();
    expect(screen.getByRole('heading', { name: 'Februar 2027' })).toBeInTheDocument();
    expect(view.cmp.selectedDay()).toBe('2027-02-03');
    expect(view.cmp.query()).toBe('');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(reload(view, [OTHER]).request.params.get('from')).toBe('2027-02-01');
    expect(cards()).toEqual(['40. Sitzung']);
  });

  it('takes a hit on a press, says when nothing matches and ends on Escape', async () => {
    const view = await setup();
    load(view);
    type(view, 'klausur');
    answer(view, [SPAN]);
    fireEvent.click(screen.getByRole('option', { name: /Klausurtagung/ }));
    expect(view.cmp.selectedDay()).toBe('2026-11-17');
    type(view, 'nichts');
    answer(view, []);
    expect(within(screen.getByRole('listbox')).getByText('Keine Treffer')).toBeInTheDocument();
    const box = view.container.querySelector('.cal__searchBox') as HTMLElement;
    fireEvent.keyDown(box, { key: 'ArrowDown' });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(view.cmp.query()).toBe('nichts');
    fireEvent.keyDown(box, { key: 'Escape' });
    view.fixture.detectChanges();
    expect(view.cmp.query()).toBe('');
    expect(screen.queryByRole('listbox')).toBeNull();
    fireEvent.keyDown(box, { key: 'Escape' });
    type(view, 'fehler');
    view.http.expectOne((r) => r.url === '/api/calendar/search').flush(null, { status: 500, statusText: 'Error' });
    view.fixture.detectChanges();
    expect(view.cmp.hits()).toEqual([]);
    expect(screen.queryByRole('listbox')).toBeNull();
    type(view, '');
    expect(view.cmp.searching()).toBe(false);
  });

  it('shows the hits in place of the days on a phone and opens the entry of a hit', async () => {
    const view = await setup({ media: [MEDIA.phone] });
    load(view);
    type(view, 'sitzung');
    expect(screen.queryByText('Angebot einholen')).toBeNull();
    answer(view, [MEETING, SPAN]);
    const rows = within(screen.getByRole('region', { name: 'Treffer' })).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('35. Sitzung');
    expect(rows[0]).toHaveTextContent('Do, 12.11.2026 · 18:00 – 20:00');
    expect(rows[1]).toHaveTextContent('Di, 17.11.2026');
    view.cmp.jump(MEETING);
    jest.useRealTimers();
    await view.fixture.whenStable();
    expect(view.router.url).toBe('/meetings/m-35');
    expect(view.cmp.query()).toBe('');
    jest.useFakeTimers();
    type(view, 'nichts');
    answer(view, []);
    expect(screen.getByText('Keine Treffer')).toBeInTheDocument();
  });
});

describe('CalendarComponent (phone)', () => {
  /** § 000726: the days with entries from today on, an entry over days at each of its days. */
  it('lists the days with entries from today on, a three-day Termin at each of its days', async () => {
    const view = await setup({ media: [MEDIA.phone], view: 'week' });
    expect(view.container.querySelector('app-skeleton')).not.toBeNull();
    const req = load(view);
    expect(req.request.params.get('from')).toBe('2026-11-11');
    expect(req.request.params.get('to')).toBe('2027-01-09');
    expect(screen.queryByRole('radiogroup')).toBeNull();
    expect(screen.queryByRole('grid')).toBeNull();
    expect(view.frame.fill()).toBe(false);
    const groups = view.cmp.days();
    expect(groups.map((d) => d.label)).toEqual([
      'Mi, 11.11.2026 · Heute',
      'Do, 12.11.2026',
      'Fr, 13.11.2026',
      'Di, 17.11.2026',
      'Mi, 18.11.2026',
      'Do, 19.11.2026',
    ]);
    expect(screen.getAllByText('Klausurtagung')).toHaveLength(3);
    const row = screen.getByText('Jour fixe').closest('[role="listitem"]') as HTMLElement;
    expect(row.querySelector('.cal__sub')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      'Termin·14:00 – 15:30·Haushaltsausschuss·Zusage',
    );
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('loads earlier and later days at the ends of the list', async () => {
    const view = await setup({ media: [MEDIA.phone] });
    load(view);
    await userEvent.click(screen.getByRole('button', { name: 'Spätere Tage laden' }));
    const later = entriesReqs(view);
    expect(later.map((r) => [r.request.params.get('from'), r.request.params.get('to')])).toEqual([
      ['2026-11-11', '2027-01-09'],
      ['2027-01-10', '2027-03-10'],
    ]);
    later[0].flush({ items: MONTH });
    later[1].flush({ items: [calendarEntry('x', { title: 'Später', startsOn: '2027-02-01', endsOn: '2027-02-01' })] });
    view.fixture.detectChanges();
    expect(screen.getByText('Später')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Frühere Tage laden' }));
    const earlier = entriesReqs(view);
    expect(earlier.map((r) => r.request.params.get('from'))).toEqual(['2026-09-12', '2026-11-11', '2027-01-10']);
    expect(earlier[0].request.params.get('to')).toBe('2026-11-10');
    earlier.forEach((r) => r.flush({ items: [] }));
    view.fixture.detectChanges();
    expect(screen.getByText('Keine Einträge in diesem Zeitraum.')).toBeInTheDocument();
  });

  it('opens an entry on a press and a new Termin from the FAB', async () => {
    const view = await setup({ media: [MEDIA.phone] });
    load(view);
    await userEvent.click(screen.getByText('Jour fixe'));
    view.http.expectOne('/api/calendar/appointments/a-1').flush(appointment());
    view.fixture.detectChanges();
    expect(await screen.findByRole('dialog', { name: 'Jour fixe' })).toBeInTheDocument();
    view.cmp.closeDetail();
    view.cmp.createAppointment();
    view.cmp.onSaved(appointment({ id: 'a-9', title: 'Neu', startsOn: '2026-12-24', endsOn: '2026-12-24' }));
    expect(view.cmp.selectedDay()).toBe('2026-11-11');
    expect(view.cmp.items().some((e) => e.id === 'a-9')).toBe(true);
    reload(view);
  });

  it('has the calendar subscription and the reload in the menu', async () => {
    const view = await setup({ media: [MEDIA.phone] });
    load(view);
    await userEvent.click(screen.getByRole('button', { name: 'Weitere Aktionen' }));
    await userEvent.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: 'Kalender-Abo' }));
    view.http.expectOne('/api/calendar/me').flush({ url: null });
    await view.fixture.whenStable();
    view.fixture.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Kalender-Abo' })).toBeInTheDocument();
    const abo = { open: jest.fn() } as unknown as Parameters<typeof view.cmp.onPhoneMenu>[1];
    view.cmp.onPhoneMenu({ id: 'x', label: 'x' }, abo);
    expect(entriesReqs(view).length).toBe(0);
    view.cmp.onPhoneMenu({ id: 'refresh', label: 'Aktualisieren' }, abo);
    await view.fixture.whenStable();
    reload(view);
  });

  it('shows a failed read as an error', async () => {
    const view = await setup({ media: [MEDIA.phone] });
    view.http.match('/api/meetings/committees').forEach((r) => r.flush([]));
    entriesReqs(view)[0].flush(null, { status: 500, statusText: 'Error' });
    view.fixture.detectChanges();
    expect(loadErrorToast()).toBe('Der Kalender konnte nicht geladen werden.');
    expect(screen.queryByText('Keine Einträge in diesem Zeitraum.')).toBeNull();
  });
});

/** § 000730-000734: the public calendar reads the public routes only and shows no person. */
describe('CalendarComponent (public)', () => {
  const PUBLIC_MEETING = { ...MEETING, gremiumIds: [], mine: false };
  const PUBLIC_TERMIN = calendarEntry('a-7', { title: 'Vollversammlung', startTime: '14:00:00', endTime: '16:00:00', place: 'Aula' });
  const ITEMS = [PUBLIC_TERMIN, PUBLIC_MEETING];

  function loadPublic(view: View, items: readonly CalendarEntry[] = ITEMS): TestRequest {
    view.http.expectOne('/api/public/calendar/committees').flush(GREMIEN);
    const req = view.http.expectOne((r) => r.url === '/api/public/calendar/entries');
    req.flush({ items });
    view.fixture.detectChanges();
    return req;
  }

  it('reads the public routes and offers no Termin, no kind filter and no "Nur meine"', async () => {
    const view = await setup({ public: true, url: '/public-calendar' });
    const req = loadPublic(view);
    expect(req.request.params.keys().sort()).toEqual(['from', 'to']);
    expect(screen.getByRole('heading', { level: 1, name: 'Kalender' })).toBeInTheDocument();
    expect(cards()).toEqual(['Vollversammlung']);
    expect(screen.queryByRole('button', { name: 'Termin anlegen' })).toBeNull();
    expect(screen.queryByText('Nur meine')).toBeNull();
    expect(screen.queryByRole('button', { name: /^Art/ })).toBeNull();
    expect(view.fixture.debugElement.injector.get(Meta).getTag('name="robots"')?.content).toBe('noindex');
    expect(await runAxe(view.container)).toHaveNoViolations();
    view.http.verify();
    view.fixture.destroy();
    expect(document.querySelector('meta[name="robots"]')).toBeNull();
  });

  it('shows the public fields of a Termin in a dialog', async () => {
    const view = await setup({ public: true });
    loadPublic(view);
    await userEvent.click(within(panel()).getByRole('button', { name: /Vollversammlung/ }));
    view.http.expectOne('/api/public/calendar/appointments/a-7').flush({
      id: 'a-7',
      title: 'Vollversammlung',
      startsOn: '2026-11-11',
      endsOn: '2026-11-11',
      startTime: '14:00:00',
      endTime: '16:00:00',
      place: 'Aula',
      description: 'Alle Studierenden sind eingeladen.',
    });
    view.fixture.detectChanges();
    const dialog = await screen.findByRole('dialog', { name: 'Vollversammlung' });
    expect(within(dialog).getByText('Mi, 11.11.2026 · 14:00 – 16:00')).toBeInTheDocument();
    expect(within(dialog).getByText('Aula')).toBeInTheDocument();
    expect(within(dialog).getByText('Alle Studierenden sind eingeladen.')).toBeInTheDocument();
    expect(within(dialog).queryByRole('radio')).toBeNull();
    expect(within(dialog).queryByRole('button', { name: 'Bearbeiten' })).toBeNull();
    view.http.verify();
  });

  it('shows the TOPs of a meeting and stays on the page', async () => {
    const view = await setup({ public: true });
    loadPublic(view);
    view.cmp.openEntry(PUBLIC_MEETING);
    view.http.expectOne('/api/public/calendar/meetings/m-35').flush({
      id: 'm-35',
      title: '35. Sitzung',
      day: '2026-11-12',
      startTime: '18:00:00',
      endTime: '20:00:00',
      gremium: 'Studierendenparlament',
      tops: ['Begrüßung', 'Haushalt 2027'],
      protocolId: null,
    });
    view.fixture.detectChanges();
    const dialog = await screen.findByRole('dialog', { name: '35. Sitzung' });
    expect(within(dialog).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Begrüßung', 'Haushalt 2027']);
    expect(view.router.url).not.toContain('/meetings/');
    view.cmp.publicOpen.set(false);
  });

  it('reports an entry that is not public any more', async () => {
    const view = await setup({ public: true });
    loadPublic(view);
    view.cmp.openEntry(PUBLIC_TERMIN);
    view.http
      .expectOne('/api/public/calendar/appointments/a-7')
      .flush(null, { status: 404, statusText: 'Not Found' });
    expect(errorToasts()).toEqual(['Der Eintrag ließ sich nicht laden.']);
    expect(view.cmp.publicOpen()).toBe(false);
  });

  it('shows the address of the public feed without a read', async () => {
    const view = await setup({ public: true });
    loadPublic(view);
    await userEvent.click(screen.getByRole('button', { name: 'Kalender abonnieren' }));
    await view.fixture.whenStable();
    view.fixture.detectChanges();
    const dialog = screen.getByRole('dialog', { name: 'Kalender-Abo' });
    expect(dialog).toHaveTextContent('http://localhost/api/public/calendar.ics');
    expect(within(dialog).getByRole('button', { name: 'Kopieren' })).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Neue URL erzeugen' })).toBeNull();
    view.http.verify();
  });

  it('searches the public entries', async () => {
    jest.useFakeTimers();
    try {
      const view = await setup({ public: true });
      loadPublic(view);
      fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'Voll' } });
      jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
      const req = view.http.expectOne((r) => r.url === '/api/public/calendar/search');
      expect(req.request.params.get('q')).toBe('Voll');
      req.flush({ items: [PUBLIC_TERMIN] });
    } finally {
      jest.useRealTimers();
    }
  });

  it('names the subscription in the menu of a phone and has no FAB', async () => {
    const view = await setup({ public: true, media: [MEDIA.phone] });
    loadPublic(view);
    expect(view.cmp.phoneMenu()[0].items[0].label).toBe('Kalender abonnieren');
    expect(screen.queryByRole('button', { name: 'Termin anlegen' })).toBeNull();
  });

  it('shows no Gremium filter when the Gremien cannot be read', async () => {
    const view = await setup({ public: true });
    view.http.expectOne('/api/public/calendar/committees').flush(null, { status: 500, statusText: 'Error' });
    view.http.expectOne((r) => r.url === '/api/public/calendar/entries').flush({ items: ITEMS });
    view.fixture.detectChanges();
    expect(cards()).toEqual(['Vollversammlung']);
    expect(screen.queryByRole('button', { name: /Alle Gremien/ })).toBeNull();
  });
});
