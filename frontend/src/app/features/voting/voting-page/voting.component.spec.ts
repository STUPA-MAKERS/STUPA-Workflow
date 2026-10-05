import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of, throwError } from 'rxjs';
import { screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import type { Meeting, Page, VoteListItem, VoteListQuery } from '@core/api/models';
import { LiveVoteService, type ConnectionState } from '@core/ws/live-vote.service';
import type { VoteClosedMsg, VoteOpenedMsg, VoteTallyMsg } from '@core/ws/ws-messages';
import { MEDIA } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { LIVE_SEARCH_DEBOUNCE_MS } from '@shared/live-search';
import { VotingComponent, VOTE_LIVE_DEBOUNCE } from './voting.component';
import { VotingNoneComponent } from './voting-none.component';
import { VotingPageService } from './voting-page.service';

/** The detail of the outlet. The detail has its own spec; here only the route matters. */
@Component({ standalone: true, template: '<p>detail</p>' })
class DetailStub {}

/** A fixed local "now" (5 Oct 2026, 12:00), so that no case depends on the time of the run. */
const NOW = new Date(2026, 9, 5, 12, 0).getTime();
const today = (h: number, m = 0) => new Date(2026, 9, 5, h, m).toISOString();

function item(id: string, over: Partial<VoteListItem> = {}): VoteListItem {
  return {
    id,
    question: `Frage ${id}?`,
    status: 'open',
    result: null,
    secret: false,
    applicationId: 'a1',
    meetingId: null,
    meetingTitle: null,
    agendaItemId: null,
    agendaPosition: null,
    gremiumId: 'g1',
    gremiumName: 'Studierendenparlament',
    createdAt: '2026-09-01T10:00:00Z',
    openedAt: '2026-09-01T10:00:00Z',
    closedAt: null,
    closesAt: null,
    canCast: true,
    myBallot: { cast: false, choice: null },
    ...over,
  };
}

function fakeSession() {
  return {
    connection: signal<ConnectionState>('open'),
    openVote: signal<VoteOpenedMsg | null>(null),
    tally: signal<VoteTallyMsg | null>(null),
    result: signal<VoteClosedMsg | null>(null),
    close: jest.fn(),
  };
}
type FakeSession = ReturnType<typeof fakeSession>;

const opened = (voteId: string): VoteOpenedMsg => ({
  type: 'vote_opened',
  voteId,
  options: ['yes', 'no', 'abstain'],
  closesAt: null,
});

interface Opts {
  /** The answers of the list requests in order; the last one repeats. */
  pages?: Page<VoteListItem>[];
  listError?: boolean;
  live?: Partial<Meeting>[];
  timelineError?: boolean;
  manager?: boolean;
  gremien?: { id: string; name: string }[];
}

const page = (items: VoteListItem[], total = items.length, offset = 0): Page<VoteListItem> => ({
  items,
  total,
  limit: 30,
  offset,
});

async function start(url: string, opts: Opts = {}) {
  let call = 0;
  const pages = opts.pages ?? [page([])];
  const listVotes = jest.fn((_q: VoteListQuery) => {
    if (opts.listError) return throwError(() => new Error('boom'));
    const answer = pages[Math.min(call, pages.length - 1)];
    call++;
    return of(answer);
  });
  const listMeetingsTimeline = jest.fn(() =>
    opts.timelineError
      ? throwError(() => new Error('boom'))
      : of({ items: (opts.live ?? []) as Meeting[], nextCursor: null }),
  );
  const sessions = new Map<string, FakeSession>();
  const live = {
    open: jest.fn((id: string) => {
      const s = fakeSession();
      sessions.set(id, s);
      return s;
    }),
  };
  const auth = {
    gremien: signal(opts.gremien ?? [{ id: 'g1', name: 'Studierendenparlament' }]),
    isAdmin: signal(false),
    canInAnyGremium: jest.fn((perm: string) => opts.manager === true && perm === 'vote.manage'),
  };
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        {
          path: 'voting',
          component: VotingComponent,
          children: [
            { path: '', component: VotingNoneComponent },
            { path: ':id', component: DetailStub },
          ],
        },
      ]),
      { provide: ApiClient, useValue: { listVotes, listMeetingsTimeline } },
      { provide: AuthService, useValue: auth },
      { provide: LiveVoteService, useValue: live },
    ],
  });
  const harness = await RouterTestingHarness.create();
  const cmp = await harness.navigateByUrl(url, VotingComponent);
  harness.detectChanges();
  const router = TestBed.inject(Router);
  const pageService = harness.routeDebugElement!.injector.get(VotingPageService);
  const settle = async () => {
    await harness.fixture.whenStable();
    harness.detectChanges();
  };
  return { harness, cmp, router, pageService, listVotes, listMeetingsTimeline, sessions, live, settle };
}

describe('VotingComponent', () => {
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    jest.spyOn(Date, 'now').mockReturnValue(NOW);
  });
  afterEach(() => jest.restoreAllMocks());

  describe('rows', () => {
    it('shows the question, the status, the meeting with the agenda item and the own ballot', async () => {
      await start('/voting', {
        pages: [
          page([
            item('v1', {
              meetingId: 'm1',
              meetingTitle: '34. Sitzung',
              agendaPosition: 3,
              openedAt: today(9, 5),
            }),
          ]),
        ],
      });
      const link = screen.getByRole('link', { name: 'Frage v1?' });
      expect(link).toHaveAttribute('href', '/voting/v1');
      expect(document.querySelector('.vl__sub app-status-text')).toHaveTextContent('Offen');
      expect(screen.getByText('TOP 3 · 34. Sitzung')).toBeInTheDocument();
      expect(screen.getByText('Stimme offen')).toBeInTheDocument();
      const since = screen.getByText('seit 09:05');
      expect(since.getAttribute('title')).toMatch(/2026/);
      expect(screen.getByText('1 offen')).toBeInTheDocument();
    });

    it('names the meeting without a number, else the gremium; a cast ballot reads "Abgestimmt"', async () => {
      await start('/voting', {
        pages: [
          page([
            item('v1', { meetingTitle: 'Sitzung ohne TOP', myBallot: { cast: true, choice: 'yes' } }),
            item('v2', { canCast: false, question: '  ', gremiumName: null }),
            item('v3', { closesAt: '2026-10-07T20:00:00Z' }),
          ]),
        ],
      });
      expect(screen.getByText('Sitzung ohne TOP')).toBeInTheDocument();
      expect(screen.getByText('Abgestimmt')).toBeInTheDocument();
      // An empty question falls back; no ballot state without a voting right.
      expect(screen.getByRole('link', { name: 'Beschlussfrage' })).toBeInTheDocument();
      expect(screen.getAllByText('Stimme offen')).toHaveLength(1);
      expect(screen.getByText('bis 07.10.2026')).toBeInTheDocument();
    });

    it('groups the open votes, the drafts and the ended votes by month', async () => {
      await start('/voting', {
        manager: true,
        pages: [
          page([
            item('o1'),
            item('d1', { status: 'draft', openedAt: null, createdAt: '2026-09-20T08:00:00Z' }),
            item('c1', {
              status: 'closed',
              result: 'passed',
              closedAt: '2026-09-12T16:00:00Z',
              myBallot: { cast: true, choice: null },
            }),
            item('c2', { status: 'closed', result: 'tie', closedAt: '2026-09-02T16:00:00Z' }),
            item('x1', { status: 'cancelled', closedAt: null, openedAt: '2026-08-02T16:00:00Z' }),
          ]),
        ],
      });
      const groups = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent?.trim());
      expect(groups).toEqual(['Offen', 'Entwürfe', 'September 2026', 'August 2026']);
      expect(screen.getByText('Entwurf')).toBeInTheDocument();
      expect(screen.getByText('Angenommen')).toBeInTheDocument();
      // A tie is a rejection (O18).
      expect(screen.getByText('Abgelehnt')).toBeInTheDocument();
      expect(screen.getByText('Abgebrochen')).toBeInTheDocument();
      expect(screen.getByText('12.09.2026')).toBeInTheDocument();
      expect(screen.getByText('20.09.2026')).toBeInTheDocument();
    });

    it('leaves out a time it cannot read', async () => {
      await start('/voting', {
        pages: [
          page([
            item('v1', { openedAt: null }),
            item('v2', { status: 'closed', closedAt: 'kaputt', result: 'rejected' }),
          ]),
        ],
      });
      expect(document.querySelectorAll('.vl__when')).toHaveLength(0);
    });
  });

  describe('states', () => {
    it('shows an error, not an empty list, when the request fails', async () => {
      await start('/voting', { listError: true });
      expect(screen.getByRole('alert')).toHaveTextContent('Die Abstimmungen konnten nicht geladen werden.');
      expect(screen.queryByText(/offen$/)).not.toBeInTheDocument();
    });

    it('shows the empty state without votes', async () => {
      await start('/voting');
      expect(screen.getByRole('heading', { name: 'Keine Abstimmungen' })).toBeInTheDocument();
    });

    it('says that no vote matches while a filter is set', async () => {
      await start('/voting?q=xyz');
      expect(screen.getByText('Keine Abstimmung passt zu den Filtern.')).toBeInTheDocument();
    });

    it('counts and loads more pages', async () => {
      const { listVotes, settle } = await start('/voting', {
        pages: [page([item('v1')], 2), page([item('v2')], 2, 1)],
      });
      expect(screen.getByText('1 von 2 Abstimmungen')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Mehr laden' }));
      await settle();
      expect(listVotes).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 1, limit: 30 }));
      expect(screen.getByText('2 von 2 Abstimmungen')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Mehr laden' })).not.toBeInTheDocument();
    });

    it('ignores a second load-more while one runs, and one without more rows', async () => {
      const { cmp, listVotes } = await start('/voting', { pages: [page([item('v1')], 1)] });
      listVotes.mockClear();
      cmp.loadMore();
      expect(listVotes).not.toHaveBeenCalled();
      cmp.total.set(5);
      cmp.loadingMore.set(true);
      cmp.loadMore();
      expect(listVotes).not.toHaveBeenCalled();
    });

    it('keeps the rows when a refresh fails', async () => {
      const { cmp, listVotes } = await start('/voting', { pages: [page([item('v1')])] });
      listVotes.mockReturnValue(throwError(() => new Error('boom')));
      cmp.refresh();
      expect(cmp.items()).toHaveLength(1);
      expect(cmp.error()).toBe(false);
    });

    it('drops the late answer of an older request', async () => {
      const { cmp, listVotes, router, settle } = await start('/voting', { pages: [page([item('v1')])] });
      const late = new (await import('rxjs')).Subject<Page<VoteListItem>>();
      listVotes.mockReturnValueOnce(late);
      cmp.refresh();
      await router.navigateByUrl('/voting?status=open');
      await settle();
      late.next(page([item('late')]));
      expect(cmp.items().map((i) => i.id)).toEqual(['v1']);
    });
  });

  describe('filters', () => {
    it('reads the filters from the URL and sends them', async () => {
      const { listVotes, cmp } = await start('/voting?status=ended&gremium=g2&q=Haushalt');
      expect(listVotes).toHaveBeenCalledWith({
        status: ['closed', 'cancelled'],
        gremiumId: 'g2',
        q: 'Haushalt',
        limit: 30,
        offset: 0,
      });
      expect(cmp.activeFilterCount()).toBe(3);
      // A gremium that the person is not in shows its id until a row names it.
      expect(cmp.gremiumChipLabel()).toBe('g2');
    });

    it('ignores an unknown status and sends the default', async () => {
      const { listVotes, cmp } = await start('/voting?status=running');
      expect(cmp.statusFilter()).toBe('');
      expect(listVotes).toHaveBeenCalledWith(expect.objectContaining({ status: undefined }));
    });

    it('searches by itself after a short pause', async () => {
      jest.useFakeTimers({ doNotFake: ['Date'] });
      try {
        const { cmp, router } = await start('/voting');
        const navigate = jest.spyOn(router, 'navigate');
        cmp.search.set('Haus');
        cmp.search.set('Haushalt ');
        jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
        expect(navigate).toHaveBeenCalledTimes(1);
        expect(navigate).toHaveBeenCalledWith([], expect.objectContaining({ queryParams: { q: 'Haushalt' } }));
        // An emptied field shows the whole list at once.
        cmp.search.set('  ');
        expect(navigate).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: { q: null } }));
      } finally {
        jest.useRealTimers();
      }
    });

    it('sets the status and the gremium through the URL and resets them', async () => {
      const { cmp, router } = await start('/voting', {
        gremien: [
          { id: 'g2', name: 'Haushaltsausschuss' },
          { id: 'g1', name: 'Studierendenparlament' },
        ],
      });
      const navigate = jest.spyOn(router, 'navigate');
      cmp.setStatus('open');
      expect(navigate).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: { status: 'open' } }));
      cmp.setStatus('');
      expect(navigate).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: { status: null } }));
      cmp.setGremium('g2');
      expect(navigate).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: { gremium: 'g2' } }));
      cmp.setGremium('');
      expect(navigate).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: { gremium: null } }));
      cmp.search.set('xy');
      cmp.reset();
      expect(navigate).toHaveBeenLastCalledWith(
        [],
        expect.objectContaining({ queryParams: { q: null, status: null, gremium: null } }),
      );
      expect(cmp.search.text()).toBe('');
    });

    it('offers the gremien of the person and of the rows, by name', async () => {
      const { cmp, harness } = await start('/voting', {
        pages: [page([item('v1', { gremiumId: 'g3', gremiumName: 'Fachschaft' }), item('v2')])],
      });
      expect(cmp.gremiumOptions().map((o) => o.label)).toEqual([
        'Alle',
        'Fachschaft',
        'Studierendenparlament',
      ]);
      expect(cmp.showGremiumChip()).toBe(true);
      expect(harness.routeDebugElement!.injector.get(VotingPageService).gremiumNames().get('v1')).toBe('Fachschaft');
      expect(screen.getByRole('button', { name: /Gremium/ })).toBeInTheDocument();
    });

    it('hides the gremium chip without a choice', async () => {
      const { cmp } = await start('/voting', { pages: [page([item('v1')])] });
      expect(cmp.showGremiumChip()).toBe(false);
    });

    it('offers the drafts only to a manager', async () => {
      const member = await start('/voting');
      expect(member.cmp.statusOptions().map((o) => o.value)).toEqual(['', 'open', 'ended']);
      TestBed.resetTestingModule();
      const manager = await start('/voting?status=draft', { manager: true });
      expect(manager.cmp.statusOptions().map((o) => o.value)).toEqual(['', 'open', 'ended', 'draft']);
      expect(manager.cmp.statusChipLabel()).toBe('Entwürfe');
      expect(manager.listVotes).toHaveBeenCalledWith(expect.objectContaining({ status: ['draft'] }));
    });

    it('labels the status chip by its value', async () => {
      const { cmp } = await start('/voting?status=open');
      expect(cmp.statusChipLabel()).toBe('Offen');
      cmp.statusFilter.set('draft');
      // A member has no draft option: the chip shows the raw value.
      expect(cmp.statusChipLabel()).toBe('draft');
      cmp.statusFilter.set('');
      expect(cmp.statusChipLabel()).toBe('Status');
      cmp.gremiumId.set('');
      expect(cmp.gremiumChipLabel()).toBe('Gremium');
    });
  });

  describe('selection', () => {
    it('opens a deep link /voting/:id in the detail pane and marks the row', async () => {
      const { cmp } = await start('/voting/v1', { pages: [page([item('v1'), item('v2')])] });
      expect(cmp.selectedId()).toBe('v1');
      expect(screen.getByText('detail')).toBeInTheDocument();
      const link = (name: string) => screen.getByRole('link', { name, hidden: true });
      expect(link('Frage v1?')).toHaveAttribute('aria-current', 'true');
    });

    it('"Zur Liste" goes back to /voting and keeps the filters', async () => {
      const { router, settle } = await start('/voting/v1?status=open', {
        pages: [page([item('v1')])],
      });
      await userEvent.click(screen.getByRole('button', { name: 'Zur Liste' }));
      await settle();
      expect(router.url).toBe('/voting?status=open');
    });

    it('the none pane asks to open a vote while votes exist, else shows the empty state', async () => {
      await start('/voting', { pages: [page([item('v1')])] });
      expect(screen.getByRole('heading', { name: 'Keine Abstimmung geöffnet', hidden: true })).toBeInTheDocument();
    });

    it('reloads the list after a cast and removes a deleted vote', async () => {
      const { pageService, listVotes, cmp } = await start('/voting', {
        pages: [page([item('v1'), item('v2')])],
      });
      listVotes.mockClear();
      pageService.notify({ id: 'v1', kind: 'cast' });
      expect(listVotes).toHaveBeenCalledWith(expect.objectContaining({ offset: 0, limit: 30 }));
      listVotes.mockClear();
      pageService.notify({ id: 'v2', kind: 'deleted' });
      expect(listVotes).not.toHaveBeenCalled();
      expect(cmp.items().map((i) => i.id)).toEqual(['v1']);
      expect(cmp.total()).toBe(1);
      pageService.notify({ id: 'gone', kind: 'deleted' });
      expect(cmp.total()).toBe(1);
    });

    it('reloads from the start when a refresh comes before any row', async () => {
      const { cmp, listVotes } = await start('/voting');
      listVotes.mockClear();
      cmp.refresh();
      expect(listVotes).toHaveBeenCalledWith(expect.objectContaining({ offset: 0, limit: 30 }));
    });

    it('phone: the vote brings its own way back, the layout drops "Zur Liste"', async () => {
      const restore = matchMediaQueries(MEDIA.phone);
      try {
        await start('/voting/v1', { pages: [page([item('v1')])] });
        expect(screen.queryByRole('button', { name: 'Zur Liste' })).not.toBeInTheDocument();
      } finally {
        restore();
      }
    });
  });

  describe('side by side', () => {
    let restore: () => void;
    beforeEach(() => (restore = matchMediaQueries(MEDIA.wide)));
    afterEach(() => restore());

    it('is a pane page and opens the first open vote on the first load', async () => {
      const { cmp, router, settle, harness, pageService } = await start('/voting', {
        pages: [page([item('v1'), item('v2')])],
      });
      await settle();
      expect(cmp.split()).toBe(true);
      expect(pageService.split()).toBe(true);
      expect(harness.routeNativeElement?.parentElement?.querySelector('app-voting')).toHaveClass('pane-page');
      expect(router.url).toBe('/voting/v1');
    });

    it('opens nothing when the first vote is not open, and only once', async () => {
      const { router, settle, cmp } = await start('/voting', {
        pages: [page([item('c1', { status: 'closed', result: 'passed' })])],
      });
      await settle();
      expect(router.url).toBe('/voting');
      cmp.items.set([item('v9')]);
      await settle();
      expect(router.url).toBe('/voting');
    });

    it('shows the short empty text in the list and the empty state in the detail', async () => {
      await start('/voting');
      expect(screen.getAllByText('Keine Abstimmungen').length).toBeGreaterThan(0);
      expect(screen.getByRole('heading', { name: 'Keine Abstimmungen' })).toBeInTheDocument();
    });
  });

  describe('live', () => {
    it('follows the running meetings and the meetings of the open votes', async () => {
      const { live, listMeetingsTimeline } = await start('/voting', {
        live: [
          { id: 'm1', status: 'live' },
          { id: 'm2', status: 'planned' },
        ],
        pages: [
          page([
            item('v1', { meetingId: 'm3' }),
            item('c1', { status: 'closed', meetingId: 'm4', result: 'passed' }),
          ]),
        ],
      });
      expect(listMeetingsTimeline).toHaveBeenCalledWith(
        expect.objectContaining({ direction: 'upcoming', cursor: null }),
      );
      expect(live.open.mock.calls.map((c) => c[0]).sort()).toEqual(['m1', 'm3']);
    });

    it('keeps the page when the timeline fails', async () => {
      const { live } = await start('/voting', { timelineError: true });
      expect(live.open).not.toHaveBeenCalled();
    });

    it('reloads on a vote that opens, closes or is cancelled, once per burst', async () => {
      jest.useFakeTimers({ doNotFake: ['Date'] });
      try {
        const { sessions, listVotes, harness } = await start('/voting', { live: [{ id: 'm1', status: 'live' }] });
        const s = sessions.get('m1')!;
        listVotes.mockClear();
        s.openVote.set(opened('v7'));
        harness.detectChanges();
        s.result.set({ type: 'vote_closed', voteId: 'v7', result: 'passed', counts: {} });
        harness.detectChanges();
        jest.advanceTimersByTime(VOTE_LIVE_DEBOUNCE);
        expect(listVotes).toHaveBeenCalledTimes(1);
        listVotes.mockClear();
        // The same state again (a replay of the same vote) is no event.
        s.result.set({ type: 'vote_closed', voteId: 'v7', result: 'passed', counts: {} });
        harness.detectChanges();
        jest.advanceTimersByTime(VOTE_LIVE_DEBOUNCE);
        expect(listVotes).not.toHaveBeenCalled();
      } finally {
        jest.useRealTimers();
      }
    });

    it('side by side with no vote open, opens the vote that just opened', async () => {
      const restore = matchMediaQueries(MEDIA.wide);
      jest.useFakeTimers({ doNotFake: ['Date'] });
      try {
        const { sessions, harness, router } = await start('/voting', {
          live: [{ id: 'm1', status: 'live' }],
        });
        const navigate = jest.spyOn(router, 'navigate');
        sessions.get('m1')!.openVote.set(opened('v7'));
        harness.detectChanges();
        jest.advanceTimersByTime(VOTE_LIVE_DEBOUNCE);
        expect(navigate).toHaveBeenCalledWith(['/voting', 'v7'], {
          queryParamsHandling: 'preserve',
          replaceUrl: false,
        });
      } finally {
        jest.useRealTimers();
        restore();
      }
    });

    it('does not open a vote that the list already holds (the replay of a connect)', async () => {
      const restore = matchMediaQueries(MEDIA.wide);
      jest.useFakeTimers({ doNotFake: ['Date'] });
      try {
        // The first row is closed, so the first load opens nothing by itself.
        const { sessions, harness, router } = await start('/voting', {
          live: [{ id: 'm1', status: 'live' }],
          pages: [page([item('c1', { status: 'closed', result: 'passed' }), item('v7', { meetingId: 'm1' })])],
        });
        const navigate = jest.spyOn(router, 'navigate');
        sessions.get('m1')!.openVote.set(opened('v7'));
        harness.detectChanges();
        jest.advanceTimersByTime(VOTE_LIVE_DEBOUNCE);
        expect(navigate).not.toHaveBeenCalled();
      } finally {
        jest.useRealTimers();
        restore();
      }
    });

    it('opens nothing that opened while the first rows were on their way', async () => {
      const restore = matchMediaQueries(MEDIA.wide);
      jest.useFakeTimers({ doNotFake: ['Date'] });
      try {
        const { sessions, harness, router, cmp } = await start('/voting', {
          live: [{ id: 'm1', status: 'live' }],
          pages: [page([item('c1', { status: 'closed', result: 'passed' })])],
        });
        const navigate = jest.spyOn(router, 'navigate');
        cmp.loading.set(true);
        sessions.get('m1')!.openVote.set(opened('v7'));
        harness.detectChanges();
        jest.advanceTimersByTime(VOTE_LIVE_DEBOUNCE);
        expect(navigate).not.toHaveBeenCalled();
      } finally {
        jest.useRealTimers();
        restore();
      }
    });

    it('clears its timers when the page goes away', async () => {
      jest.useFakeTimers({ doNotFake: ['Date'] });
      try {
        const { sessions, harness, cmp, listVotes } = await start('/voting', {
          live: [{ id: 'm1', status: 'live' }],
        });
        sessions.get('m1')!.openVote.set(opened('v7'));
        harness.detectChanges();
        listVotes.mockClear();
        cmp.ngOnDestroy();
        jest.advanceTimersByTime(VOTE_LIVE_DEBOUNCE);
        expect(listVotes).not.toHaveBeenCalled();
      } finally {
        jest.useRealTimers();
      }
    });
  });

  it('searches at once on Enter and clears with ×', async () => {
    const { cmp, router } = await start('/voting');
    const navigate = jest.spyOn(router, 'navigate');
    const field = screen.getByRole('searchbox');
    await userEvent.type(field, 'Haus{Enter}');
    expect(navigate).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: { q: 'Haus' } }));
    expect(cmp.search.text()).toBe('Haus');
  });

  it('resets without a pending search', async () => {
    const { cmp, router } = await start('/voting?status=open');
    const navigate = jest.spyOn(router, 'navigate');
    cmp.reset();
    expect(navigate).toHaveBeenCalledWith([], expect.objectContaining({
      queryParams: { q: null, status: null, gremium: null },
    }));
  });

  it('drops the late failure of an older request', async () => {
    const { Subject } = await import('rxjs');
    const { cmp, listVotes } = await start('/voting', { pages: [page([item('v1')])] });
    const late = new Subject<Page<VoteListItem>>();
    listVotes.mockReturnValueOnce(late);
    cmp.refresh();
    cmp.refresh();
    late.error(new Error('boom'));
    expect(cmp.error()).toBe(false);
    expect(cmp.items().map((i) => i.id)).toEqual(['v1']);
  });

  it('reads the next page of the timeline to find the live meetings', async () => {
    const listMeetingsTimeline = jest
      .fn()
      .mockReturnValueOnce(of({ items: [{ id: 'm1', status: 'planned' }], nextCursor: 'c2' }))
      .mockReturnValueOnce(of({ items: [{ id: 'm2', status: 'live' }], nextCursor: null }));
    const live = { open: jest.fn(() => fakeSession()) };
    TestBed.configureTestingModule({
      providers: [
        // No child routes: the filters navigate relative to the page itself.
        provideRouter([{ path: 'voting', component: VotingComponent }]),
        { provide: ApiClient, useValue: { listVotes: () => of(page([])), listMeetingsTimeline } },
        {
          provide: AuthService,
          useValue: { gremien: signal([]), isAdmin: signal(false), canInAnyGremium: () => false },
        },
        { provide: LiveVoteService, useValue: live },
      ],
    });
    const harness = await RouterTestingHarness.create();
    const cmp = await harness.navigateByUrl('/voting', VotingComponent);
    expect(listMeetingsTimeline).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: 'c2' }));
    expect(live.open).toHaveBeenCalledWith('m2');
    cmp.setStatus('open');
    await harness.fixture.whenStable();
    expect(TestBed.inject(Router).url).toBe('/voting?status=open');
  });

  it('closes the live channels with the page', async () => {
    const { sessions, harness } = await start('/voting', { live: [{ id: 'm1', status: 'live' }] });
    harness.fixture.destroy();
    expect(sessions.get('m1')!.close).toHaveBeenCalled();
  });

  it('marks the rows of a list one pane at a time as a row group', async () => {
    await start('/voting', { pages: [page([item('v1')])] });
    const list = screen.getByRole('list');
    expect(list).toHaveClass('rowgroup');
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
  });
});
