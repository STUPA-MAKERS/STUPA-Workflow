import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import type { TestRequest } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { MeetingOutWire } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { WsService } from '@core/ws/ws.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { runAxe } from '../../../../testing/a11y';
import { MeetingAgendaService } from '../meeting-agenda.service';
import { MeetingDialogsService } from '../meeting-dialogs.service';
import { MeetingSessionService } from '../meeting-session.service';
import { MeetingsTimelineService, PAST_PREVIEW, TIMELINE_PAGE } from '../meetings-timeline.service';
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
  agendaItemCount: 9,
});
const LIVE = wire('m-34', '34. Sitzung', 'live', {
  date: '2026-09-29',
  startedAt: local('2026-09-29', 18, 4),
  protokollantName: 'Mara Keller',
  agendaItemCount: 8,
});
const PLANNED = wire('m-35', '35. Sitzung', 'planned', {
  startTime: '17:30:00',
  endTime: '19:00:00',
  agendaItemCount: 1,
});
const NOVEMBER = wire('m-36', '36. Sitzung', 'planned', { date: '2026-11-03' });

function fakeAuth(opts: { admin?: boolean; managed?: string[] } = {}): Partial<AuthService> {
  return {
    can: () => false,
    isAdmin: (() => opts.admin ?? false) as unknown as AuthService['isAdmin'],
    gremien: (() => [{ id: 'g-1', name: 'StuPa' }]) as unknown as AuthService['gremien'],
    sessionManageGremien: (() => opts.managed ?? ['g-1']) as unknown as AuthService['sessionManageGremien'],
    inSubstitutePool: (() => false) as unknown as AuthService['inSubstitutePool'],
  };
}

let restoreMedia: (() => void) | null = null;
afterEach(() => {
  restoreMedia?.();
  restoreMedia = null;
});

async function setup(
  opts: { admin?: boolean; managed?: string[]; media?: string[]; url?: string; canCreate?: boolean } = {},
) {
  if (opts.media) restoreMedia = matchMediaQueries(...opts.media);
  const on = { viewChange: jest.fn(), create: jest.fn() };
  const view = await render(MeetingsListComponent, {
    inputs: { canCreate: opts.canCreate ?? true },
    on,
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([
        { path: 'meetings/:id', children: [] },
        { path: 'account/calendar', children: [] },
        { path: '**', children: [] },
      ]),
      MeetingsTimelineService,
      MeetingDialogsService,
      MeetingSessionService,
      MeetingAgendaService,
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(opts) },
      { provide: WsService, useValue: {} },
    ],
  });
  const injector = view.fixture.debugElement.injector;
  const router = injector.get(Router);
  if (opts.url) {
    await router.navigateByUrl(opts.url);
    view.fixture.detectChanges();
  }
  const http = injector.get(HttpTestingController);
  const timeline = injector.get(MeetingsTimelineService);
  const dialogs = injector.get(MeetingDialogsService);
  return { ...view, http, timeline, dialogs, router, on };
}

type View = Awaited<ReturnType<typeof setup>>;
type Page = { items: MeetingOutWire[]; nextCursor: string | null };

function timelineReq(http: HttpTestingController, direction: 'past' | 'upcoming'): TestRequest {
  return http.expectOne(
    (r) => r.url === '/api/meetings/timeline' && r.params.get('direction') === direction && !r.params.has('q'),
  );
}

/** Load the list: filter Gremien, then the first upcoming page and the past preview. */
function load(
  view: View,
  pages: { upcoming?: Page; past?: Page; gremien?: { id: string; name: string }[] } = {},
): { past: TestRequest; upcoming: TestRequest } {
  view.http.expectOne('/api/meetings/gremien').flush(pages.gremien ?? []);
  view.timeline.loadList();
  const upcoming = timelineReq(view.http, 'upcoming');
  const past = timelineReq(view.http, 'past');
  upcoming.flush(pages.upcoming ?? { items: [LIVE, PLANNED, NOVEMBER], nextCursor: null });
  past.flush(pages.past ?? { items: [CLOSED], nextCursor: null });
  view.fixture.detectChanges();
  return { past, upcoming };
}

/** Answer the reads of the detail sheet. */
function flushSheet(http: HttpTestingController, id: string): void {
  http.expectOne(`/api/meetings/${id}/agenda`).flush([]);
  http.expectOne(`/api/meetings/${id}/attendance`).flush([]);
  http.expectOne((r) => r.url === '/api/delegations' && r.params.get('meetingId') === id).flush([]);
  http.match(`/api/meetings/${id}/protocol`).forEach((r) => r.flush({ id: 'p', meetingId: id, markdown: '', status: 'draft' }));
}

const titles = (el: HTMLElement): (string | undefined)[] =>
  Array.from(el.querySelectorAll('.li__title')).map((b) => b.textContent?.trim());

// The tests click through whole views; a busy runner needs more than the default 5 s.
jest.setTimeout(15_000);

describe('MeetingsListComponent', () => {
  it('groups the meetings: "Jetzt", the coming months, then the past months', async () => {
    const view = await setup();
    load(view);
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent?.trim());
    expect(headings).toEqual([
      'Jetzt',
      'Anstehend · Oktober 2026',
      'Anstehend · November 2026',
      'Vergangen · September 2026',
    ]);
    const now = screen.getByRole('region', { name: 'Jetzt' });
    expect(titles(now)).toEqual(['34. Sitzung']);
    expect(titles(screen.getByRole('region', { name: 'Vergangen · September 2026' }))).toEqual(['33. Sitzung']);
  });

  it('shows the status, the Gremium, the time and the number of agenda items', async () => {
    const view = await setup();
    load(view);
    const [liveRow, plannedRow, novRow, closedRow] = screen.getAllByRole('listitem');
    expect(within(liveRow).getByText('Live')).toHaveClass('st--accent');
    expect(within(liveRow).getByText('seit 18:04')).toBeInTheDocument();
    expect(within(liveRow).getByText('8 TOPs')).toBeInTheDocument();
    expect(liveRow.querySelector('app-date-block')).toHaveClass('db--live');
    expect(within(plannedRow).getByText('Geplant')).toHaveClass('st--neutral');
    expect(within(plannedRow).getByText('Di, 17:30')).toBeInTheDocument();
    expect(within(plannedRow).getByText('1 TOP')).toBeInTheDocument();
    expect(within(plannedRow).getByText('Studierendenparlament')).toBeInTheDocument();
    expect(within(novRow).getByText('keine TOPs')).toBeInTheDocument();
    expect(within(closedRow).getByText('Geschlossen')).toHaveClass('st--muted');
    expect(within(closedRow).getByText('Di, 18:04')).toBeInTheDocument();
    expect(closedRow.querySelector('app-date-block')).toHaveClass('db--muted');
    // One pane at a time a chevron says that the row opens a step.
    expect(liveRow.querySelector('.mtl__chev')).not.toBeNull();
  });

  it('names a meeting without a date or a time and a group without a date', async () => {
    const view = await setup();
    load(view, {
      upcoming: { items: [wire('m-x', 'Ohne Datum', 'planned', { date: null, startTime: null, gremiumName: null })], nextCursor: null },
      past: { items: [wire('m-y', 'Ohne Zeit', 'closed', { date: '2026-09-01', startTime: null })], nextCursor: null },
    });
    expect(screen.getByRole('heading', { name: 'Anstehend · ohne Datum' })).toBeInTheDocument();
    const [undated, untimed] = screen.getAllByRole('listitem');
    expect(undated.querySelector('.mtl__time')?.textContent?.trim()).toBe('');
    expect(untimed.querySelector('.mtl__time')?.textContent?.trim()).toBe('Di');
  });

  it('loads earlier meetings at the end and later meetings after the coming ones', async () => {
    const view = await setup();
    const { past } = load(view, {
      upcoming: { items: [LIVE, PLANNED], nextCursor: 'u-1' },
      past: { items: [CLOSED], nextCursor: 'c-1' },
    });
    expect(past.request.params.get('limit')).toBe(String(PAST_PREVIEW));
    await userEvent.click(screen.getByRole('button', { name: 'Frühere Sitzungen laden' }));
    const more = view.http.expectOne((r) => r.url === '/api/meetings/timeline' && r.params.get('cursor') === 'c-1');
    expect(more.request.params.get('limit')).toBe(String(TIMELINE_PAGE));
    more.flush({ items: [wire('m-32', '32. Sitzung', 'closed', { date: '2026-08-01' })], nextCursor: null });
    view.fixture.detectChanges();
    expect(screen.getByRole('heading', { name: 'Vergangen · August 2026' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Frühere Sitzungen laden' })).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: 'Weitere Sitzungen laden' }));
    view.http
      .expectOne((r) => r.url === '/api/meetings/timeline' && r.params.get('cursor') === 'u-1')
      .flush({ items: [NOVEMBER], nextCursor: null });
    view.fixture.detectChanges();
    expect(screen.getByRole('heading', { name: 'Anstehend · November 2026' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Weitere Sitzungen laden' })).toBeNull();
  });

  it('puts "Weitere Sitzungen laden" at the end when no past meeting follows', async () => {
    const view = await setup();
    load(view, { upcoming: { items: [PLANNED], nextCursor: 'u-1' }, past: { items: [], nextCursor: null } });
    const scroll = view.container.querySelector('.mtl__scroll') as HTMLElement;
    expect(scroll.lastElementChild).toHaveClass('mtl__more');
  });

  it('says when nothing is coming, and shows the empty state without any meeting', async () => {
    const view = await setup();
    load(view, { upcoming: { items: [], nextCursor: null }, past: { items: [CLOSED], nextCursor: null } });
    expect(screen.getByText('Keine anstehenden Sitzungen.')).toBeInTheDocument();
    view.timeline.pastItems.set([]);
    view.fixture.detectChanges();
    expect(screen.getByText('Noch keine Sitzungen')).toBeInTheDocument();
    expect(screen.getByText('Lege mit „Neue Sitzung“ die erste Sitzung an.')).toBeInTheDocument();
    view.fixture.componentRef.setInput('canCreate', false);
    view.timeline.pastHasMore.set(true);
    view.fixture.detectChanges();
    expect(screen.getByText('Sobald dein Gremium eine Sitzung plant, steht sie hier.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Frühere Sitzungen laden' })).toBeInTheDocument();
  });

  it('shows the placeholder rows while the list loads', async () => {
    const view = await setup();
    view.http.expectOne('/api/meetings/gremien').flush([]);
    view.timeline.loadList();
    view.fixture.detectChanges();
    expect(screen.getByRole('status')).toHaveTextContent('Sitzungen werden geladen');
    view.http.match((r) => r.url === '/api/meetings/timeline');
  });

  it('offers the Gremium chip for more than one Gremium and reloads with it', async () => {
    const view = await setup();
    load(view, { gremien: [{ id: 'g-1', name: 'StuPa' }, { id: 'g-2', name: 'Finanzausschuss' }] });
    expect(view.container.querySelector('select')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Gremium: Alle Gremien' }));
    const list = screen.getByRole('listbox', { name: 'Gremium' });
    await userEvent.click(within(list).getByRole('option', { name: 'Finanzausschuss' }));
    view.fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Gremium: Finanzausschuss' })).toBeInTheDocument();
    const up = timelineReq(view.http, 'upcoming');
    expect(up.request.params.get('gremiumId')).toBe('g-2');
    up.flush({ items: [], nextCursor: null });
    timelineReq(view.http, 'past').flush({ items: [], nextCursor: null });
  });

  it('reads an unknown Gremium of the filter as "Alle Gremien"', async () => {
    const view = await setup();
    load(view, { gremien: [{ id: 'g-1', name: 'StuPa' }, { id: 'g-2', name: 'FA' }] });
    view.timeline.gremiumFilter.set('g-gone');
    view.fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Gremium: Alle Gremien' })).toBeInTheDocument();
  });

  it('hides the chip for one Gremium', async () => {
    const view = await setup();
    load(view, { gremien: [{ id: 'g-1', name: 'StuPa' }] });
    expect(screen.queryByRole('button', { name: /^Gremium/ })).toBeNull();
  });

  it('shows the hits of a search in one list, says when none matches, and loads more', async () => {
    const view = await setup();
    load(view);
    view.timeline.searchQuery.set('35');
    // A meeting of an older server comes without the agenda count.
    view.timeline.searchItems.set([
      { ...view.timeline.upcomingItems()[1], agendaItemCount: undefined },
      view.timeline.pastItems()[0],
    ]);
    view.timeline.searchHasMore.set(true);
    view.fixture.detectChanges();
    const hits = screen.getByRole('region', { name: 'Suchergebnisse' });
    expect(titles(hits)).toEqual(['35. Sitzung', '33. Sitzung']);
    expect(hits.querySelectorAll('.db--muted')).toHaveLength(1);
    expect(within(hits).getByText('keine TOPs')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Jetzt' })).toBeNull();
    const loadMore = jest.spyOn(view.timeline, 'loadMoreSearch').mockImplementation(() => undefined);
    await userEvent.click(screen.getByRole('button', { name: 'Weitere Sitzungen laden' }));
    expect(loadMore).toHaveBeenCalled();
    view.timeline.searchItems.set([]);
    view.timeline.searchHasMore.set(false);
    view.fixture.detectChanges();
    expect(screen.getByText('Keine Sitzungen gefunden.')).toBeInTheDocument();
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('searches while typing', async () => {
    const view = await setup();
    load(view);
    const onSearch = jest.spyOn(view.timeline, 'onSearch');
    await userEvent.type(screen.getByRole('searchbox'), 'a');
    expect(onSearch).toHaveBeenCalledWith('a');
  });

  describe('one pane at a time', () => {
    it('opens the detail step of a row through `?sel` and goes back to the list', async () => {
      const view = await setup();
      load(view);
      await userEvent.click(screen.getByRole('button', { name: '35. Sitzung' }));
      await view.fixture.whenStable();
      view.fixture.detectChanges();
      expect(view.router.url).toBe('/?sel=m-35');
      flushSheet(view.http, 'm-35');
      view.fixture.detectChanges();
      expect(screen.getByRole('heading', { level: 2, name: '35. Sitzung' })).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Zur Liste' }));
      await view.fixture.whenStable();
      expect(view.router.url).toBe('/');
    });

    it('opens the meeting page on a double click', async () => {
      const view = await setup();
      load(view);
      await userEvent.dblClick(screen.getByRole('button', { name: '35. Sitzung' }));
      await view.fixture.whenStable();
      expect(view.router.url).toBe('/meetings/m-35');
      view.http.match(() => true);
    });

    it('reads a deep-linked meeting that is not in the first pages, and drops a failed one', async () => {
      const view = await setup({ url: '/?sel=m-99' });
      load(view);
      view.http.expectOne('/api/meetings/m-99').flush(wire('m-99', 'Alte Sitzung', 'closed', { date: '2025-01-01' }));
      view.fixture.detectChanges();
      flushSheet(view.http, 'm-99');
      view.fixture.detectChanges();
      expect(screen.getByRole('heading', { level: 2, name: 'Alte Sitzung' })).toBeInTheDocument();
      // A save of that meeting reaches the sheet; a save of another one does not change it.
      const updated = { ...view.timeline.pastItems()[0], id: 'm-99', title: 'Alte Sitzung (neu)' };
      view.timeline.replaceInTimeline(updated);
      view.fixture.detectChanges();
      view.timeline.replaceInTimeline({ ...updated, id: 'm-other' });
      view.fixture.detectChanges();
      expect(screen.getByRole('heading', { level: 2, name: 'Alte Sitzung (neu)' })).toBeInTheDocument();
      // A delete of it clears the selection.
      view.timeline.removeFromTimeline('m-99');
      view.fixture.detectChanges();
      await view.fixture.whenStable();
      expect(view.router.url).toBe('/');

      await view.router.navigateByUrl('/?sel=m-404');
      view.fixture.detectChanges();
      view.http.expectOne('/api/meetings/m-404').flush(null, { status: 404, statusText: 'nf' });
      await view.fixture.whenStable();
      expect(view.router.url).toBe('/');
    });

    it('keeps a deep link that fails with 403 and says why', async () => {
      const view = await setup({ url: '/?sel=m-403' });
      load(view);
      view.http.expectOne('/api/meetings/m-403').flush(null, { status: 403, statusText: 'no' });
      await view.fixture.whenStable();
      view.fixture.detectChanges();
      expect(view.router.url).toBe('/?sel=m-403');
      expect(screen.getByRole('alert')).toHaveTextContent('Kein Zugriff auf diese Sitzung');
      expect(screen.queryByRole('button', { name: 'Erneut laden' })).not.toBeInTheDocument();
    });

    it('keeps a deep link after a server or network error and reads it again on request', async () => {
      const view = await setup({ url: '/?sel=m-500' });
      load(view);
      view.http.expectOne('/api/meetings/m-500').flush(null, { status: 503, statusText: 'down' });
      await view.fixture.whenStable();
      view.fixture.detectChanges();
      expect(view.router.url).toBe('/?sel=m-500');
      expect(screen.getByRole('alert')).toHaveTextContent('Sitzung nicht geladen');
      await userEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
      view.http.expectOne('/api/meetings/m-500').error(new ProgressEvent('error'));
      view.fixture.detectChanges();
      expect(screen.getByRole('alert')).toHaveTextContent('Sitzung nicht geladen');
      await userEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
      view.http
        .expectOne('/api/meetings/m-500')
        .flush(wire('m-500', 'Wieder da', 'closed', { date: '2025-01-01' }));
      view.fixture.detectChanges();
      flushSheet(view.http, 'm-500');
      view.fixture.detectChanges();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 2, name: 'Wieder da' })).toBeInTheDocument();
      // No selection: nothing to read again.
      await view.router.navigateByUrl('/');
      view.fixture.componentInstance.retrySelected();
      view.http.expectNone('/api/meetings/m-500');
    });

    it('keeps the selection when another meeting is deleted', async () => {
      const view = await setup({ url: '/?sel=m-35' });
      load(view);
      flushSheet(view.http, 'm-35');
      view.timeline.removeFromTimeline('m-36');
      view.fixture.detectChanges();
      await view.fixture.whenStable();
      expect(view.router.url).toBe('/?sel=m-35');
    });

    it('edits, deletes and projects the selected meeting from the sheet', async () => {
      const view = await setup({ url: '/?sel=m-35' });
      load(view);
      flushSheet(view.http, 'm-35');
      view.fixture.detectChanges();
      await userEvent.click(screen.getByRole('button', { name: 'Sitzung bearbeiten: 35. Sitzung' }));
      expect(view.dialogs.settingsMeeting()?.id).toBe('m-35');
      await userEvent.click(screen.getByRole('button', { name: 'Weitere Aktionen: 35. Sitzung' }));
      await userEvent.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: 'Sitzung löschen' }));
      expect(view.dialogs.deleteMeeting()?.id).toBe('m-35');
      const open = jest.spyOn(window, 'open').mockImplementation(() => null);
      await userEvent.click(screen.getByRole('button', { name: /Beamer-Ansicht/ }));
      expect(open).toHaveBeenCalledWith(
        expect.stringMatching(/^\/voting\/beamer\/m-35\?from=/),
        '_blank',
        'noopener',
      );
      open.mockRestore();
    });

    it('offers the switch, the calendar subscription and the FAB', async () => {
      const view = await setup();
      load(view);
      await userEvent.click(screen.getByRole('radio', { name: 'Kalender' }));
      expect(view.on.viewChange).toHaveBeenCalledWith('calendar');
      expect(screen.getByRole('link', { name: 'Kalender-Abo' })).toHaveAttribute('href', '/account/calendar');
      await userEvent.click(screen.getByRole('button', { name: 'Neue Sitzung' }));
      expect(view.on.create).toHaveBeenCalled();
      view.fixture.componentRef.setInput('showSwitch', false);
      view.fixture.componentRef.setInput('canCreate', false);
      view.fixture.detectChanges();
      expect(screen.queryByRole('radiogroup')).toBeNull();
      expect(screen.queryByRole('button', { name: 'Neue Sitzung' })).toBeNull();
    });
  });

  describe('side by side', () => {
    it('shows the live meeting while nothing is selected, and marks the selected row', async () => {
      const view = await setup({ media: [MEDIA.wide] });
      load(view);
      flushSheet(view.http, 'm-34');
      view.fixture.detectChanges();
      expect(view.container.querySelector('.mtl')).toHaveClass('mtl--split');
      expect(screen.getByRole('heading', { level: 2, name: '34. Sitzung' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '34. Sitzung' })).toHaveAttribute('aria-current', 'true');
      expect(view.container.querySelector('.mtl__chev')).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: '35. Sitzung' }));
      await view.fixture.whenStable();
      view.fixture.detectChanges();
      flushSheet(view.http, 'm-35');
      view.fixture.detectChanges();
      expect(screen.getByRole('heading', { level: 2, name: '35. Sitzung' })).toBeInTheDocument();
      expect(await runAxe(view.container)).toHaveNoViolations();
    });

    it('shows the next meeting without a live one, and an empty sheet without any', async () => {
      const view = await setup({ media: [MEDIA.wide] });
      load(view, { upcoming: { items: [PLANNED], nextCursor: null } });
      flushSheet(view.http, 'm-35');
      view.fixture.detectChanges();
      expect(screen.getByRole('heading', { level: 2, name: '35. Sitzung' })).toBeInTheDocument();
      view.timeline.upcomingItems.set([]);
      view.fixture.detectChanges();
      expect(screen.getByText('Keine Sitzung gewählt')).toBeInTheDocument();
    });
  });

  describe('phone', () => {
    it('has the title, "+ Sitzung" and a menu with the calendar subscription', async () => {
      const view = await setup({ media: [MEDIA.phone] });
      load(view);
      expect(screen.queryByRole('radiogroup')).toBeNull();
      expect(view.container.querySelector('.mtl__fab')).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Sitzung' }));
      expect(view.on.create).toHaveBeenCalled();
      await userEvent.click(screen.getByRole('button', { name: 'Weitere Aktionen' }));
      await userEvent.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: 'Kalender-Abo' }));
      await view.fixture.whenStable();
      expect(view.router.url).toBe('/account/calendar');
    });

    it('puts the time and the agenda count into the sub line and wraps the title', async () => {
      const view = await setup({ media: [MEDIA.phone], canCreate: false });
      load(view);
      const [liveRow] = screen.getAllByRole('listitem');
      expect(liveRow.querySelector('.mtl__sub')?.textContent?.replace(/\s*·\s*/g, ' · ').trim()).toBe(
        'Live · seit 18:04 · 8 TOPs',
      );
      expect(liveRow.querySelector('.li')).toHaveClass('li--wrap');
      expect(screen.queryByRole('button', { name: 'Sitzung' })).toBeNull();
      expect(screen.getByRole('searchbox')).toHaveAttribute('placeholder', 'Sitzungen suchen …');
      // A menu item that the page does not know does nothing.
      view.fixture.componentInstance.onPhoneMenu({ id: 'x', label: 'x' });
      expect(view.router.url).toBe('/');
    });
  });
});
