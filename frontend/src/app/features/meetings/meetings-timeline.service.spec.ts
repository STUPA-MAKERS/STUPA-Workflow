import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { MeetingsTimelineService, PAST_PREVIEW, TIMELINE_PAGE } from './meetings-timeline.service';

type Page = { items: Meeting[]; nextCursor: string | null };
type Params = { direction: string; cursor?: string | null; limit: number; gremiumId?: string; q?: string };

const m = (id: string): Meeting => ({ id, title: id }) as Meeting;

function setup(
  opts: { reader?: boolean; many?: boolean; gremien?: () => ReturnType<ApiClient['listMeetingFilterGremien']> } = {},
) {
  const calls: Params[] = [];
  const answers: Subject<Page>[] = [];
  const api = {
    listMeetingFilterGremien: jest.fn(opts.gremien ?? (() => of([{ id: 'g1', name: 'StuPa' }]))),
    listMeetingsTimeline: jest.fn((p: Params) => {
      calls.push(p);
      const s = new Subject<Page>();
      answers.push(s);
      return s;
    }),
  };
  const reader = opts.reader ?? true;
  const auth = {
    isAdmin: () => false,
    can: () => false,
    gremien: () => (reader ? (opts.many ? [{ id: 'g1' }, { id: 'g2' }] : [{ id: 'g1' }]) : []),
    inSubstitutePool: () => false,
  };
  TestBed.configureTestingModule({
    providers: [
      MeetingsTimelineService,
      { provide: ApiClient, useValue: api },
      { provide: AuthService, useValue: auth },
    ],
  });
  const svc = TestBed.inject(MeetingsTimelineService);
  const answer = (i: number, page: Page) => {
    answers[i].next(page);
    answers[i].complete();
  };
  const fail = (i: number) => answers[i].error(new Error('down'));
  return { svc, api, calls, answer, fail };
}

describe('MeetingsTimelineService', () => {
  afterEach(() => jest.useRealTimers());

  it('offers the Gremien of the filter, and none when they cannot be read', () => {
    expect(setup().svc.filterGremiumOptions().map((o) => o.value)).toEqual(['', 'g1']);
    TestBed.resetTestingModule();
    const { svc } = setup({ gremien: () => throwError(() => new Error('x')) });
    expect(svc.filterGremien()).toEqual([]);
  });

  /** A Gremium that left the list reads as "Alle Gremien". */
  it('shows the Gremium chip only for more than one Gremium and names the chosen one', () => {
    const one = setup().svc;
    expect(one.showGremiumFilter()).toBe(false);
    TestBed.resetTestingModule();
    const { svc } = setup({
      gremien: () =>
        of([
          { id: 'g1', name: 'StuPa' },
          { id: 'g2', name: 'AStA' },
        ]),
    });
    expect(svc.showGremiumFilter()).toBe(true);
    expect(svc.gremiumFilterLabel()).toBe('Alle Gremien');
    svc.gremiumFilter.set('g2');
    expect(svc.gremiumFilterLabel()).toBe('AStA');
    svc.gremiumFilter.set('gone');
    expect(svc.gremiumFilterLabel()).toBe('Alle Gremien');
  });

  it('holds the place of the filter chip while the filter Gremien load, for a member of several', () => {
    const pending = new Subject<{ id: string; name: string }[]>();
    const { svc } = setup({ many: true, gremien: () => pending });
    expect(svc.filterPending()).toBe(true);
    pending.next([{ id: 'g1', name: 'StuPa' }]);
    expect(svc.filterPending()).toBe(false);
    TestBed.resetTestingModule();
    const failed = new Subject<{ id: string; name: string }[]>();
    const second = setup({ many: true, gremien: () => failed }).svc;
    failed.error(new Error('x'));
    expect(second.filterPending()).toBe(false);
    TestBed.resetTestingModule();
    expect(setup({ gremien: () => new Subject() }).svc.filterPending()).toBe(false);
  });

  it('does not load the timeline for a user who may not read it', () => {
    const { svc, api } = setup({ reader: false });
    svc.loadList();
    expect(api.listMeetingsTimeline).not.toHaveBeenCalled();
  });

  /** A second press while one load runs does nothing. */
  it('loads both directions, then more of each, and keeps the order', () => {
    const { svc, calls, answer, fail } = setup();
    svc.loadList();
    expect(calls.map((c) => [c.direction, c.limit])).toEqual([
      ['upcoming', TIMELINE_PAGE],
      ['past', PAST_PREVIEW],
    ]);
    answer(0, { items: [m('u1')], nextCursor: 'cu' });
    answer(1, { items: [m('p2'), m('p1')], nextCursor: 'cp' });
    expect(svc.loadingList()).toBe(false);
    expect(svc.pastItems().map((x) => x.id)).toEqual(['p1', 'p2']);
    expect(svc.hasMorePast()).toBe(true);
    expect(svc.timelineEmpty()).toBe(false);

    svc.loadMorePast();
    svc.loadMorePast();
    expect(calls[2]).toMatchObject({ direction: 'past', cursor: 'cp' });
    answer(2, { items: [m('p0'), m('p-1')], nextCursor: null });
    expect(svc.pastItems().map((x) => x.id)).toEqual(['p-1', 'p0', 'p1', 'p2']);
    svc.loadMorePast();
    expect(calls).toHaveLength(3);

    svc.loadMoreUpcoming();
    svc.loadMoreUpcoming();
    expect(calls[3]).toMatchObject({ direction: 'upcoming', cursor: 'cu' });
    answer(3, { items: [m('u2')], nextCursor: 'cu2' });
    expect(svc.upcomingItems().map((x) => x.id)).toEqual(['u1', 'u2']);
    svc.loadMoreUpcoming();
    fail(4);
    expect(svc.loadingUpcoming()).toBe(false);
    expect(svc.upcomingHasMore()).toBe(true);
  });

  /** The answer of the g1 load comes late, so it changes nothing. */
  it('keeps the shown meetings while a filter reloads, and drops a late older answer', () => {
    const { svc, answer } = setup();
    svc.loadList();
    expect(svc.loadingList()).toBe(true);
    expect(svc.reloadingList()).toBe(false);
    answer(0, { items: [m('u1')], nextCursor: null });
    answer(1, { items: [], nextCursor: null });

    svc.selectGremiumFilter('g1');
    expect(svc.loadingList()).toBe(false);
    expect(svc.reloadingList()).toBe(true);
    expect(svc.upcomingItems().map((x) => x.id)).toEqual(['u1']);
    svc.selectGremiumFilter('g2');
    answer(2, { items: [m('late')], nextCursor: null });
    answer(3, { items: [], nextCursor: null });
    expect(svc.upcomingItems().map((x) => x.id)).toEqual(['u1']);
    expect(svc.reloadingList()).toBe(true);
    answer(4, { items: [m('u2')], nextCursor: null });
    answer(5, { items: [], nextCursor: null });
    expect(svc.upcomingItems().map((x) => x.id)).toEqual(['u2']);
    expect(svc.reloadingList()).toBe(false);
  });

  /** With nothing loaded there is no upcoming page to add to. */
  it('stops loading on errors of the first load and of an older page', () => {
    const { svc, answer, fail } = setup();
    svc.loadList();
    answer(0, { items: [], nextCursor: null });
    answer(1, { items: [m('p1')], nextCursor: 'cp' });
    svc.loadMorePast();
    fail(2);
    expect(svc.loadingPast()).toBe(false);
    svc.loadList();
    fail(3);
    expect(svc.loadingList()).toBe(false);
    expect(svc.timelineEmpty()).toBe(true);
    svc.loadMoreUpcoming();
  });

  it('refreshes the timeline, or the search while one is active, and says when it loads', () => {
    jest.useFakeTimers();
    const { svc, calls, answer } = setup();
    expect(svc.listBusy()).toBe(false);
    svc.refreshList();
    expect(svc.listBusy()).toBe(true);
    expect(calls.map((c) => c.direction)).toEqual(['upcoming', 'past']);
    answer(0, { items: [], nextCursor: null });
    answer(1, { items: [], nextCursor: null });
    expect(svc.listBusy()).toBe(false);
    svc.onSearch('fin');
    jest.advanceTimersByTime(400);
    expect(calls).toHaveLength(3);
    answer(2, { items: [], nextCursor: null });
    svc.refreshList();
    jest.advanceTimersByTime(400);
    expect(calls[3]).toMatchObject({ q: 'fin' });
  });

  /**
   * A new search that starts before the first answers drops the first answer. A failed search ends
   * the loading; a late failure of an older search is dropped. An empty query returns to the
   * timeline. The destroy stops the pending search.
   */
  it('searches after a pause, pages the hits and drops a late answer', () => {
    jest.useFakeTimers();
    const { svc, calls, answer, fail } = setup();
    svc.selectGremiumFilter('g1');
    expect(calls[0]).toMatchObject({ gremiumId: 'g1' });
    svc.onSearch('fin');
    svc.onSearch('finanz ');
    expect(svc.searchActive()).toBe(true);
    jest.advanceTimersByTime(400);
    expect(calls[2]).toMatchObject({ q: 'finanz', gremiumId: 'g1', cursor: null });
    expect(svc.loadingSearch()).toBe(true);
    svc.selectGremiumFilter('');
    expect(calls[3]).toMatchObject({ q: 'finanz', gremiumId: undefined });
    answer(2, { items: [m('old')], nextCursor: null });
    expect(svc.searchItems()).toEqual([]);
    answer(3, { items: [m('s1')], nextCursor: 'cs' });
    expect(svc.searchItems().map((x) => x.id)).toEqual(['s1']);
    svc.loadMoreSearch();
    svc.loadMoreSearch();
    expect(calls[4]).toMatchObject({ cursor: 'cs' });
    answer(4, { items: [m('s2')], nextCursor: null });
    expect(svc.searchItems().map((x) => x.id)).toEqual(['s1', 's2']);
    expect(svc.searchEmpty()).toBe(false);
    svc.loadMoreSearch();
    expect(calls).toHaveLength(5);

    svc.onSearch('x');
    jest.advanceTimersByTime(400);
    svc.onSearch('y');
    jest.advanceTimersByTime(400);
    fail(5);
    expect(svc.loadingSearch()).toBe(true);
    fail(6);
    expect(svc.loadingSearch()).toBe(false);
    expect(svc.searchEmpty()).toBe(true);

    svc.onSearch('  ');
    jest.advanceTimersByTime(400);
    expect(calls[7].direction).toBe('upcoming');
    expect(calls[7].q).toBeUndefined();
    svc.onSearch('z');
    TestBed.resetTestingModule();
    jest.advanceTimersByTime(400);
    expect(calls).toHaveLength(9);
  });

  it('replaces and removes a meeting everywhere and reports the change', () => {
    const { svc, answer } = setup();
    svc.loadList();
    answer(0, { items: [m('a'), m('b')], nextCursor: null });
    answer(1, { items: [m('a')], nextCursor: null });
    svc.replaceInTimeline({ ...m('a'), title: 'neu' });
    expect(svc.upcomingItems()[0].title).toBe('neu');
    expect(svc.pastItems()[0].title).toBe('neu');
    expect(svc.lastChange()).toMatchObject({ kind: 'updated' });
    svc.removeFromTimeline('a');
    expect(svc.upcomingItems().map((x) => x.id)).toEqual(['b']);
    expect(svc.lastChange()).toEqual({ kind: 'removed', id: 'a' });
  });
});
