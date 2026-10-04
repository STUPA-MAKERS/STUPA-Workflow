import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import type { TestRequest } from '@angular/common/http/testing';
import { Router } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { EMPTY } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import type { MeetingOutWire } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { WsService } from '@core/ws/ws.service';
import { MeetingAgendaService } from '../meeting-agenda.service';
import { MeetingDialogsService } from '../meeting-dialogs.service';
import { MeetingSessionService } from '../meeting-session.service';
import { MeetingsTimelineService, PAST_PREVIEW, TIMELINE_PAGE } from '../meetings-timeline.service';
import { runAxe } from '../../../../testing/a11y';
import { MeetingsListComponent } from './meetings-list.component';

const local = (d: string, h: number, m: number) => {
  const [y, mo, day] = d.split('-').map(Number);
  return new Date(y, mo - 1, day, h, m).toISOString();
};

function wire(id: string, title: string, status: MeetingOutWire['status'], over: Partial<MeetingOutWire> = {}): MeetingOutWire {
  return {
    id,
    title,
    status,
    date: '2026-10-13',
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

const CLOSED = wire('m-33', '33. Sitzung', 'closed', {
  date: '2026-09-15',
  startedAt: local('2026-09-15', 18, 4),
  closedAt: local('2026-09-15', 21, 40),
  protokollantName: 'Mara Keller',
});
const LIVE = wire('m-34', '34. Sitzung', 'live', {
  date: '2026-09-29',
  startedAt: local('2026-09-29', 18, 4),
  protokollantName: 'Mara Keller',
});
const PLANNED = wire('m-35', '35. Sitzung', 'planned', { startTime: '17:30:00', endTime: '19:00:00' });
const FOREIGN = wire('m-12', '12. Sitzung des Finanzausschusses', 'planned', {
  gremiumName: 'Finanzausschuss',
  canManage: false,
});

function fakeAuth(opts: { admin?: boolean; managed?: string[] } = {}): Partial<AuthService> {
  return {
    can: () => false,
    isAdmin: (() => opts.admin ?? false) as unknown as AuthService['isAdmin'],
    gremien: (() => [{ id: 'g-1', name: 'StuPa' }]) as unknown as AuthService['gremien'],
    sessionManageGremien: (() => opts.managed ?? ['g-1']) as unknown as AuthService['sessionManageGremien'],
    inSubstitutePool: (() => false) as unknown as AuthService['inSubstitutePool'],
  };
}

async function setup(opts: { admin?: boolean; managed?: string[] } = {}) {
  const navigate = jest.fn(() => Promise.resolve(true));
  const view = await render(MeetingsListComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      MeetingsTimelineService,
      MeetingDialogsService,
      MeetingSessionService,
      MeetingAgendaService,
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(opts) },
      { provide: WsService, useValue: {} },
      {
        provide: Router,
        useValue: {
          navigate,
          events: EMPTY,
          config: [],
          routerState: { snapshot: { root: { url: [], data: {}, firstChild: null } } },
        },
      },
    ],
  });
  const injector = view.fixture.debugElement.injector;
  const http = injector.get(HttpTestingController);
  const timeline = injector.get(MeetingsTimelineService);
  const dialogs = injector.get(MeetingDialogsService);
  return { ...view, http, timeline, dialogs, navigate };
}

type Page = { items: MeetingOutWire[]; nextCursor: string | null };

function timelineReq(http: HttpTestingController, direction: 'past' | 'upcoming'): TestRequest {
  return http.expectOne(
    (r) => r.url === '/api/meetings/timeline' && r.params.get('direction') === direction && !r.params.has('q'),
  );
}

/** Load the list: filter Gremien, then the first upcoming page and the past preview. */
function load(
  view: Awaited<ReturnType<typeof setup>>,
  pages: { upcoming?: Page; past?: Page; gremien?: { id: string; name: string }[] } = {},
): { past: TestRequest; upcoming: TestRequest } {
  view.http.expectOne('/api/meetings/gremien').flush(pages.gremien ?? []);
  view.timeline.loadList();
  const upcoming = timelineReq(view.http, 'upcoming');
  const past = timelineReq(view.http, 'past');
  upcoming.flush(pages.upcoming ?? { items: [LIVE, PLANNED], nextCursor: null });
  past.flush(pages.past ?? { items: [CLOSED], nextCursor: null });
  view.fixture.detectChanges();
  return { past, upcoming };
}

describe('MeetingsListComponent', () => {
  it('puts the past above "Jetzt" and the live and coming meetings below it', async () => {
    const view = await setup();
    load(view);
    const past = screen.getByRole('list', { name: 'Frühere Sitzungen' });
    const upcoming = screen.getByRole('list', { name: 'Kommende Sitzungen' });
    const now = screen.getByRole('separator', { name: 'Jetzt' });
    expect(within(past).getByRole('button', { name: '33. Sitzung' })).toBeInTheDocument();
    const titles = within(upcoming)
      .getAllByRole('button')
      .filter((b) => b.classList.contains('li__title'))
      .map((b) => b.textContent?.trim());
    expect(titles).toEqual(['34. Sitzung', '35. Sitzung']);
    expect(past.compareDocumentPosition(now) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(now.compareDocumentPosition(upcoming) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows the status as text, the Gremium, the time and the minute-taker', async () => {
    const view = await setup();
    load(view);
    const rows = screen.getAllByRole('listitem');
    const [closedRow, liveRow, plannedRow] = rows;
    expect(within(closedRow).getByText('Geschlossen')).toHaveClass('st--muted');
    expect(within(closedRow).getByText('18:04–21:40')).toBeInTheDocument();
    expect(within(liveRow).getByText('Live')).toHaveClass('st--accent');
    expect(within(liveRow).getByText('seit 18:04')).toBeInTheDocument();
    expect(within(liveRow).getByText(/Mara Keller/)).toBeInTheDocument();
    expect(within(plannedRow).getByText('Geplant')).toHaveClass('st--neutral');
    expect(within(plannedRow).getByText('17:30–19:00')).toBeInTheDocument();
    expect(within(plannedRow).getByText('Studierendenparlament')).toBeInTheDocument();
    // The live meeting has the accent date block.
    expect(liveRow.querySelector('app-date-block')).toHaveClass('db--live');
    expect(closedRow).toHaveClass('mtl__row--past');
  });

  it('loads a short past preview first and earlier meetings on request, on top', async () => {
    const view = await setup();
    const { past } = load(view, { past: { items: [CLOSED], nextCursor: 'c-1' } });
    expect(past.request.params.get('limit')).toBe(String(PAST_PREVIEW));
    await userEvent.click(screen.getByRole('button', { name: 'Frühere Sitzungen laden' }));
    const more = view.http.expectOne((r) => r.url === '/api/meetings/timeline' && r.params.get('cursor') === 'c-1');
    expect(more.request.params.get('direction')).toBe('past');
    expect(more.request.params.get('limit')).toBe(String(TIMELINE_PAGE));
    const older = [wire('m-32', '32. Sitzung', 'closed', { date: '2026-09-01' }), wire('m-31', '31. Sitzung', 'closed', { date: '2026-08-01' })];
    more.flush({ items: older, nextCursor: null });
    view.fixture.detectChanges();
    const titles = within(screen.getByRole('list', { name: 'Frühere Sitzungen' }))
      .getAllByRole('button')
      .filter((b) => b.classList.contains('li__title'))
      .map((b) => b.textContent?.trim());
    expect(titles).toEqual(['31. Sitzung', '32. Sitzung', '33. Sitzung']);
    expect(screen.queryByRole('button', { name: 'Frühere Sitzungen laden' })).toBeNull();
  });

  it('loads later meetings at the end', async () => {
    const view = await setup();
    load(view, { upcoming: { items: [LIVE], nextCursor: 'u-1' } });
    await userEvent.click(screen.getByRole('button', { name: 'Weitere Sitzungen laden' }));
    view.http
      .expectOne((r) => r.url === '/api/meetings/timeline' && r.params.get('cursor') === 'u-1')
      .flush({ items: [PLANNED], nextCursor: null });
    view.fixture.detectChanges();
    expect(screen.getByRole('button', { name: '35. Sitzung' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Weitere Sitzungen laden' })).toBeNull();
  });

  it('keeps the lists when a later page fails, and loads nothing without a cursor', async () => {
    const view = await setup();
    load(view, { upcoming: { items: [LIVE], nextCursor: 'u-1' }, past: { items: [CLOSED], nextCursor: 'p-1' } });
    view.timeline.loadMoreUpcoming();
    view.timeline.loadMoreUpcoming(); // one request at a time
    view.timeline.loadMorePast();
    view.timeline.loadMorePast();
    view.http.expectOne((r) => r.params.get('cursor') === 'u-1').flush(null, { status: 500, statusText: 'e' });
    view.http.expectOne((r) => r.params.get('cursor') === 'p-1').flush(null, { status: 500, statusText: 'e' });
    expect(view.timeline.upcomingItems().length).toBe(1);
    expect(view.timeline.pastItems().length).toBe(1);
    expect(view.timeline.loadingPast()).toBe(false);
    expect(view.timeline.loadingUpcoming()).toBe(false);
  });

  it('says when nothing is coming, and clears the lists when the load fails', async () => {
    const view = await setup();
    load(view, { upcoming: { items: [], nextCursor: null }, past: { items: [], nextCursor: null } });
    expect(screen.getByText('Keine anstehenden Sitzungen.')).toBeInTheDocument();
    view.timeline.loadList();
    view.fixture.detectChanges();
    expect(screen.queryByRole('separator')).toBeNull(); // the skeleton shows while it loads
    expect(screen.getByRole('status')).toHaveTextContent('Sitzungen werden geladen');
    timelineReq(view.http, 'upcoming').flush(null, { status: 500, statusText: 'e' });
    view.http.match((r) => r.url === '/api/meetings/timeline');
    view.fixture.detectChanges();
    expect(view.timeline.loadingList()).toBe(false);
    expect(view.timeline.upcomingItems()).toEqual([]);
  });

  it('offers the Gremium filter for more than one Gremium and reloads with it', async () => {
    const view = await setup();
    load(view, { gremien: [{ id: 'g-1', name: 'StuPa' }, { id: 'g-2', name: 'Finanzausschuss' }] });
    const filter = screen.getByRole('combobox', { name: 'Gremium' });
    expect(within(filter).getAllByRole('option').map((o) => o.textContent?.trim())).toEqual([
      'Alle Gremien',
      'StuPa',
      'Finanzausschuss',
    ]);
    await userEvent.selectOptions(filter, 'g-2');
    const up = timelineReq(view.http, 'upcoming');
    expect(up.request.params.get('gremiumId')).toBe('g-2');
    up.flush({ items: [FOREIGN], nextCursor: null });
    timelineReq(view.http, 'past').flush({ items: [], nextCursor: null });
  });

  it('hides the filter for one Gremium and keeps an empty list when the Gremien fail', async () => {
    const view = await setup();
    view.http.expectOne('/api/meetings/gremien').flush(null, { status: 500, statusText: 'e' });
    view.fixture.detectChanges();
    expect(screen.queryByRole('combobox', { name: 'Gremium' })).toBeNull();
    expect(view.timeline.filterGremien()).toEqual([]);
  });

  it('has no axe violations, also in the search', async () => {
    const view = await setup();
    load(view, { gremien: [{ id: 'g-1', name: 'StuPa' }, { id: 'g-2', name: 'FA' }] });
    expect(await runAxe(view.container)).toHaveNoViolations();
    view.timeline.searchQuery.set('35');
    view.timeline.searchItems.set([view.timeline.upcomingItems()[1]]);
    view.fixture.detectChanges();
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('opens a meeting from its row', async () => {
    const view = await setup();
    load(view);
    await userEvent.click(screen.getByRole('button', { name: '35. Sitzung' }));
    expect(view.navigate).toHaveBeenCalledWith(['/meetings', 'm-35']);
  });

  it('gives a lead "Bearbeiten" and "Löschen" on the rows of the own Gremium only', async () => {
    const view = await setup();
    load(view, { upcoming: { items: [PLANNED, FOREIGN], nextCursor: null } });
    const [own, foreign] = within(screen.getByRole('list', { name: 'Kommende Sitzungen' })).getAllByRole('listitem');
    expect(within(foreign).queryByRole('button', { name: /Sitzung bearbeiten/ })).toBeNull();
    await userEvent.click(within(own).getByRole('button', { name: 'Sitzung bearbeiten: 35. Sitzung' }));
    expect(view.dialogs.settingsMeeting()?.id).toBe('m-35');
    await userEvent.click(within(own).getByRole('button', { name: 'Sitzung löschen: 35. Sitzung' }));
    expect(view.dialogs.deleteMeeting()?.id).toBe('m-35');
  });

  it('offers "Neue Sitzung" with session.manage and opens the create dialog', async () => {
    const view = await setup();
    load(view);
    await userEvent.click(screen.getByRole('button', { name: 'Neue Sitzung' }));
    expect(screen.getByRole('dialog', { name: 'Sitzung anlegen' })).toBeInTheDocument();
    view.http.expectOne('/api/gremien').flush([]);
    const [, footerCancel] = screen.getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(footerCancel);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('offers no "Neue Sitzung" without session.manage', async () => {
    const view = await setup({ managed: [] });
    load(view);
    expect(screen.queryByRole('button', { name: 'Neue Sitzung' })).toBeNull();
  });

  it('offers "Neue Sitzung" to an admin without a Gremium role', async () => {
    const view = await setup({ admin: true, managed: [] });
    load(view);
    expect(screen.getByRole('button', { name: 'Neue Sitzung' })).toBeInTheDocument();
  });

  describe('search', () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    it('collapses the list into hits by relevance after a short pause', async () => {
      const view = await setup();
      load(view);
      view.timeline.onSearch('Sitzung');
      view.timeline.onSearch('35'); // the second key resets the pause
      jest.advanceTimersByTime(400);
      const req = view.http.expectOne((r) => r.url === '/api/meetings/timeline' && r.params.get('q') === '35');
      req.flush({ items: [PLANNED], nextCursor: 's-1' });
      view.fixture.detectChanges();
      expect(screen.queryByRole('separator')).toBeNull();
      expect(screen.getByRole('button', { name: '35. Sitzung' })).toBeInTheDocument();
      // More hits on request.
      view.timeline.loadMoreSearch();
      view.timeline.loadMoreSearch(); // one request at a time
      view.http
        .expectOne((r) => r.params.get('q') === '35' && r.params.get('cursor') === 's-1')
        .flush({ items: [FOREIGN], nextCursor: null });
      expect(view.timeline.searchItems().map((m) => m.id)).toEqual(['m-35', 'm-12']);
      view.timeline.loadMoreSearch(); // no cursor left
      view.http.expectNone((r) => r.params.has('q'));
    });

    it('says when nothing matches, and drops a stale answer', async () => {
      const view = await setup();
      load(view);
      view.timeline.onSearch('alt');
      jest.advanceTimersByTime(400);
      const stale = view.http.expectOne((r) => r.params.get('q') === 'alt');
      view.timeline.onSearch('neu');
      jest.advanceTimersByTime(400);
      stale.flush({ items: [PLANNED], nextCursor: null });
      expect(view.timeline.searchItems()).toEqual([]);
      const fresh = view.http.expectOne((r) => r.params.get('q') === 'neu');
      fresh.flush({ items: [], nextCursor: null });
      view.fixture.detectChanges();
      expect(screen.getByText('Keine Sitzungen gefunden.')).toBeInTheDocument();
    });

    it('keeps the state after a failed search and drops a stale failure', async () => {
      const view = await setup();
      load(view);
      view.timeline.onSearch('a');
      jest.advanceTimersByTime(400);
      const stale = view.http.expectOne((r) => r.params.get('q') === 'a');
      view.timeline.onSearch('b');
      jest.advanceTimersByTime(400);
      stale.flush(null, { status: 500, statusText: 'e' });
      expect(view.timeline.loadingSearch()).toBe(true);
      view.http.expectOne((r) => r.params.get('q') === 'b').flush(null, { status: 500, statusText: 'e' });
      expect(view.timeline.loadingSearch()).toBe(false);
    });

    it('runs the search again for a new filter and returns to the list for an empty query', async () => {
      const view = await setup();
      load(view);
      view.timeline.onSearch('x');
      jest.advanceTimersByTime(400);
      view.http.expectOne((r) => r.params.get('q') === 'x').flush({ items: [], nextCursor: null });
      view.timeline.selectGremiumFilter('g-2');
      const again = view.http.expectOne((r) => r.params.get('q') === 'x');
      expect(again.request.params.get('gremiumId')).toBe('g-2');
      again.flush({ items: [], nextCursor: null });
      view.timeline.onSearch('');
      jest.advanceTimersByTime(400);
      timelineReq(view.http, 'upcoming').flush({ items: [LIVE], nextCursor: null });
      timelineReq(view.http, 'past').flush({ items: [], nextCursor: null });
      expect(view.timeline.searchActive()).toBe(false);
    });

    it('stops a pending search when the page goes', async () => {
      const view = await setup();
      load(view);
      view.timeline.onSearch('x');
      // The page provides the service, so its end ends the service.
      view.timeline.ngOnDestroy();
      jest.advanceTimersByTime(400);
      view.http.expectNone((r) => r.params.has('q'));
    });
  });

  it('puts a saved meeting into every list and removes a deleted one', async () => {
    const view = await setup();
    load(view);
    view.timeline.searchItems.set([view.timeline.upcomingItems()[1]]);
    const renamed = { ...view.timeline.upcomingItems()[1], title: '35. Sitzung (neu)' };
    view.timeline.replaceInTimeline(renamed);
    expect(view.timeline.upcomingItems()[1].title).toBe('35. Sitzung (neu)');
    expect(view.timeline.upcomingItems()[0].title).toBe('34. Sitzung');
    expect(view.timeline.searchItems()[0].title).toBe('35. Sitzung (neu)');
    view.timeline.removeFromTimeline('m-35');
    view.timeline.removeFromTimeline('m-33');
    expect(view.timeline.upcomingItems().map((m) => m.id)).toEqual(['m-34']);
    expect(view.timeline.pastItems()).toEqual([]);
    expect(view.timeline.searchItems()).toEqual([]);
  });
});
