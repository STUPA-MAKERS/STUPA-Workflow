import { Injectable, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin, type Observable } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { Meeting, MeetingPage, Uuid } from '@core/api/models';
import type { SelectOption } from '@stupa-makers/ui-kit';
import { liveSearch } from '@stupa-makers/ui-kit';

/** A change of one meeting, see `MeetingsTimelineService.lastChange`. */
export type MeetingChange =
  | { kind: 'updated'; meeting: Meeting }
  | { kind: 'removed'; id: Uuid };

/** Page size of a "load more" step (both directions and the search). */
export const TIMELINE_PAGE = 15;
/**
 * Past meetings that the first load shows above the "now" marker. The list opens on
 * the present: the most recent meetings give the context, "Frühere Sitzungen laden"
 * reaches the older ones.
 */
export const PAST_PREVIEW = 3;

/**
 * Overview timeline state with server-side keyset paging in both directions.
 * Past meetings sit above a "now" marker, upcoming ones below it. Each direction
 * loads more on a button, not on scroll. The search mode collapses both into one
 * relevance-sorted list with offset paging. Provided by MeetingsComponent.
 */
@Injectable()
export class MeetingsTimelineService {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);

  /**
   * The user may read the overview timeline. The server filters the result: admins and
   * `meeting.view_all` readers get every Gremium, members and substitute-pool entries get
   * their own. The page and `loadList()` use this one predicate, so a user who sees the
   * overview always gets its data.
   */
  readonly canReadTimeline = computed(
    () =>
      this.auth.isAdmin() ||
      this.auth.can('meeting.view_all') ||
      this.auth.gremien().length > 0 ||
      this.auth.inSubstitutePool(),
  );

  /** The first load runs and nothing shows yet: the list draws its skeleton. */
  readonly loadingList = signal(false);
  /**
   * The list loads again (the Gremium filter changed) while the old meetings show. They
   * stay, dimmed and inert, until the new ones arrive.
   */
  readonly reloadingList = signal(false);
  private listSeq = 0;

  /** Upcoming meetings, chronologically forward (earliest on top). */
  readonly upcomingItems = signal<Meeting[]>([]);
  /** Past meetings, chronological (oldest on top, newest next to "now"). */
  readonly pastItems = signal<Meeting[]>([]);
  private upcomingCursor: string | null = null;
  private pastCursor: string | null = null;
  readonly upcomingHasMore = signal(false);
  readonly pastHasMore = signal(false);
  readonly loadingUpcoming = signal(false);
  readonly loadingPast = signal(false);

  /** Gremium filter of the overview ('' = all). */
  readonly gremiumFilter = signal<string>('');
  /** Gremien with at least one readable meeting. The backend provides the list. */
  readonly filterGremien = signal<{ id: string; name: string }[]>([]);
  private readonly filterGremienLoaded = signal(false);
  /**
   * The filter Gremien have not arrived yet, and the person probably gets the chip (more
   * than one Gremium, or every meeting). The list then holds the place of the chip row, so
   * the rows do not move down when the answer comes.
   */
  readonly filterPending = computed(
    () =>
      !this.filterGremienLoaded() &&
      (this.auth.isAdmin() || this.auth.can('meeting.view_all') || this.auth.gremien().length > 1),
  );
  readonly filterGremiumOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('meetings.list.allCommittees') },
    ...this.filterGremien().map((g) => ({ value: g.id, label: g.name })),
  ]);
  /** The Gremium chip shows only when there is more than one Gremium to pick. */
  readonly showGremiumFilter = computed(() => this.filterGremien().length > 1);
  /** The text of the Gremium chip. An unknown value (a Gremium that left the list) reads as "Alle Gremien". */
  readonly gremiumFilterLabel = computed(() => {
    const options = this.filterGremiumOptions();
    const value = this.gremiumFilter();
    return options.find((o) => o.value === value)?.label ?? options[0].label;
  });

  /** Active search query (empty = normal past/upcoming timeline). */
  readonly searchQuery = signal('');
  readonly searchActive = computed(() => this.searchQuery().trim().length > 0);
  readonly searchItems = signal<Meeting[]>([]);
  private searchCursor: string | null = null;
  readonly searchHasMore = signal(false);
  readonly loadingSearch = signal(false);
  /** Sequence counter that lets the service discard late "load more" answers of stale queries. */
  private searchSeq = 0;
  /** Header search from the first character: debounce, and a new query cancels the old request. */
  private readonly search = liveSearch<MeetingPage>({
    minLength: 1,
    run: (q) => this.startSearch(q),
    result: (page) => this.applySearchPage(page, true),
    error: () => this.loadingSearch.set(false),
  });

  readonly hasMorePast = computed(() => this.pastHasMore());
  readonly timelineEmpty = computed(
    () => !this.upcomingItems().length && !this.pastItems().length,
  );
  readonly searchEmpty = computed(
    () => this.searchActive() && !this.loadingSearch() && !this.searchItems().length,
  );

  constructor() {
    // Filter options: Gremien with at least one READABLE meeting. Every reader
    // may filter, so this load has no permission gate.
    this.api
      .listMeetingFilterGremien()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (gs) => {
          this.filterGremien.set(gs);
          this.filterGremienLoaded.set(true);
        },
        error: () => {
          this.filterGremien.set([]);
          this.filterGremienLoaded.set(true);
        },
      });
  }

  /** Debounced (~250 ms) header search. An empty query returns to the timeline. */
  onSearch(value: string): void {
    this.searchQuery.set(value);
    this.search.set(value);
  }

  private startSearch(q: string): Observable<MeetingPage> | void {
    ++this.searchSeq;
    this.searchCursor = null;
    this.searchItems.set([]);
    this.searchHasMore.set(false);
    if (!q) {
      this.loadingSearch.set(false);
      this.loadList();
      return;
    }
    this.loadingSearch.set(true);
    return this.searchPage(q);
  }

  loadMoreSearch(): void {
    if (this.loadingSearch() || !this.searchHasMore() || this.searchCursor === null) return;
    this.loadingSearch.set(true);
    const seq = ++this.searchSeq;
    this.searchPage(this.searchQuery().trim()).subscribe({
      next: (page) => {
        if (seq === this.searchSeq) this.applySearchPage(page, false);
      },
      error: () => {
        if (seq === this.searchSeq) this.loadingSearch.set(false);
      },
    });
  }

  private searchPage(q: string): Observable<MeetingPage> {
    return this.api.listMeetingsTimeline({
      direction: 'upcoming', // no effect in search mode: the backend collapses both
      cursor: this.searchCursor,
      limit: TIMELINE_PAGE,
      gremiumId: this.gremiumFilter() || undefined,
      q,
    });
  }

  private applySearchPage(page: MeetingPage, initial: boolean): void {
    this.searchItems.update((cur) => (initial ? page.items : [...cur, ...page.items]));
    this.searchCursor = page.nextCursor;
    this.searchHasMore.set(page.nextCursor !== null);
    this.loadingSearch.set(false);
  }

  /** The list or the search loads: a pull to refresh waits for it. */
  readonly listBusy = computed(() => this.loadingList() || this.reloadingList() || this.loadingSearch());

  /** Pull to refresh: the timeline loads again, or the search while one is active. */
  refreshList(): void {
    if (this.searchActive()) {
      this.search.refresh();
      return;
    }
    this.loadList();
  }

  /** Switch the Gremium filter and reload the timeline or the search. */
  selectGremiumFilter(id: string): void {
    this.gremiumFilter.set(id);
    if (this.searchActive()) {
      this.search.refresh();
      return;
    }
    this.loadList();
  }

  /**
   * Load the next past page. The older meetings go on top, right below the button
   * that asked for them.
   */
  loadMorePast(): void {
    if (this.loadingPast() || !this.pastHasMore() || this.pastCursor === null) return;
    this.loadingPast.set(true);
    this.api
      .listMeetingsTimeline({
        direction: 'past',
        cursor: this.pastCursor,
        limit: TIMELINE_PAGE,
        gremiumId: this.gremiumFilter() || undefined,
      })
      .subscribe({
        next: (page) => {
          this.loadingPast.set(false);
          // The page arrives newest-first. Reverse and prepend it, so the oldest
          // meeting stays on top.
          this.pastItems.update((cur) => [...[...page.items].reverse(), ...cur]);
          this.pastCursor = page.nextCursor;
          this.pastHasMore.set(page.nextCursor !== null);
        },
        error: () => this.loadingPast.set(false),
      });
  }

  loadMoreUpcoming(): void {
    if (this.loadingUpcoming() || !this.upcomingHasMore() || this.upcomingCursor === null)
      return;
    this.loadingUpcoming.set(true);
    this.api
      .listMeetingsTimeline({
        direction: 'upcoming',
        cursor: this.upcomingCursor,
        limit: TIMELINE_PAGE,
        gremiumId: this.gremiumFilter() || undefined,
      })
      .subscribe({
        next: (page) => {
          this.loadingUpcoming.set(false);
          this.upcomingItems.update((cur) => [...cur, ...page.items]);
          this.upcomingCursor = page.nextCursor;
          this.upcomingHasMore.set(page.nextCursor !== null);
        },
        error: () => this.loadingUpcoming.set(false),
      });
  }

  /**
   * The last change that a dialog made to a meeting. The calendar view keeps its own
   * month of meetings and applies the change to it; the list view drops the selection
   * of a deleted meeting.
   */
  readonly lastChange = signal<MeetingChange | null>(null);

  /** Replace an updated meeting in both directions and in the search hits. */
  replaceInTimeline(updated: Meeting): void {
    const repl = (list: Meeting[]): Meeting[] =>
      list.map((x) => (x.id === updated.id ? updated : x));
    this.upcomingItems.update(repl);
    this.pastItems.update(repl);
    this.searchItems.update(repl);
    this.lastChange.set({ kind: 'updated', meeting: updated });
  }

  /** Remove a deleted meeting from both directions and from the search hits. */
  removeFromTimeline(id: Uuid): void {
    const rm = (list: Meeting[]): Meeting[] => list.filter((x) => x.id !== id);
    this.upcomingItems.update(rm);
    this.pastItems.update(rm);
    this.searchItems.update(rm);
    this.lastChange.set({ kind: 'removed', id });
  }

  /**
   * Initial load: the first upcoming page and the past preview in parallel. Loaded
   * meetings stay until the answer replaces them; only a late answer of an older load is
   * dropped.
   */
  loadList(): void {
    if (!this.canReadTimeline()) return;
    const seq = ++this.listSeq;
    const shown = this.upcomingItems().length + this.pastItems().length > 0;
    this.upcomingCursor = null;
    this.pastCursor = null;
    this.upcomingHasMore.set(false);
    this.pastHasMore.set(false);
    this.loadingList.set(!shown);
    this.reloadingList.set(shown);
    forkJoin({
      upcoming: this.api.listMeetingsTimeline({
        direction: 'upcoming',
        limit: TIMELINE_PAGE,
        gremiumId: this.gremiumFilter() || undefined,
      }),
      past: this.api.listMeetingsTimeline({
        direction: 'past',
        limit: PAST_PREVIEW,
        gremiumId: this.gremiumFilter() || undefined,
      }),
    }).subscribe({
      next: ({ upcoming, past }) => {
        if (seq !== this.listSeq) return;
        this.loadingList.set(false);
        this.reloadingList.set(false);
        this.upcomingItems.set(upcoming.items);
        this.upcomingCursor = upcoming.nextCursor;
        this.upcomingHasMore.set(upcoming.nextCursor !== null);
        // "past" arrives newest-first. Reverse it: oldest on top, newest at "now".
        this.pastItems.set([...past.items].reverse());
        this.pastCursor = past.nextCursor;
        this.pastHasMore.set(past.nextCursor !== null);
      },
      error: () => {
        if (seq !== this.listSeq) return;
        this.loadingList.set(false);
        this.reloadingList.set(false);
        this.upcomingItems.set([]);
        this.pastItems.set([]);
      },
    });
  }
}
