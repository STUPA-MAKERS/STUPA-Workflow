import { Injectable, type OnDestroy, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { Meeting, Uuid } from '@core/api/models';
import type { SelectOption } from '@stupa-makers/ui-kit';

/** Page size per lazy-load step (both directions). */
const PAGE = 15;

/**
 * Overview timeline state with server-side keyset paging in both directions.
 * Past meetings sit above a "now" marker, upcoming ones below it. The search mode
 * collapses both into one relevance-sorted list with offset paging.
 * Provided by MeetingsComponent.
 */
@Injectable()
export class MeetingsTimelineService implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);

  readonly loadingList = signal(false);

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
  /** One-shot flag for the initial scroll to the "now" marker (parent effect). */
  didInitialScroll = false;

  /** Gremium filter of the overview ('' = all). */
  readonly gremiumFilter = signal<string>('');
  /** Gremien with at least one readable meeting. The backend provides the list. */
  readonly filterGremien = signal<{ id: string; name: string }[]>([]);
  readonly filterGremiumOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('meetings.list.allCommittees') },
    ...this.filterGremien().map((g) => ({ value: g.id, label: g.name })),
  ]);

  /** Active search query (empty = normal past/upcoming timeline). */
  readonly searchQuery = signal('');
  readonly searchActive = computed(() => this.searchQuery().trim().length > 0);
  readonly searchItems = signal<Meeting[]>([]);
  private searchCursor: string | null = null;
  readonly searchHasMore = signal(false);
  readonly loadingSearch = signal(false);
  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  /** Sequence counter that lets the service discard late responses of stale queries. */
  private searchSeq = 0;

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
        next: (gs) => this.filterGremien.set(gs),
        error: () => this.filterGremien.set([]),
      });
  }

  ngOnDestroy(): void {
    if (this.searchTimer !== null) clearTimeout(this.searchTimer);
  }

  /**
   * Scroll-driven lazy loading. Near the top edge it loads older past meetings.
   * Near the bottom edge it loads more upcoming meetings. In search mode the
   * bottom edge loads the next offset page instead.
   */
  onScroll(el: HTMLElement): void {
    if (this.searchActive()) {
      if (el.scrollHeight - el.scrollTop - el.clientHeight <= 80) this.loadMoreSearch();
      return;
    }
    if (el.scrollTop <= 80) this.loadMorePast(el);
    if (el.scrollHeight - el.scrollTop - el.clientHeight <= 80) this.loadMoreUpcoming();
  }

  /** Debounced (~400 ms) header search. An empty query returns to the timeline. */
  onSearch(value: string): void {
    this.searchQuery.set(value);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.runSearch(), 400);
  }

  private runSearch(): void {
    const q = this.searchQuery().trim();
    this.searchCursor = null;
    this.searchItems.set([]);
    this.searchHasMore.set(false);
    if (!q) {
      this.loadList();
      return;
    }
    this.loadingSearch.set(true);
    this.fetchSearch(true);
  }

  loadMoreSearch(): void {
    if (this.loadingSearch() || !this.searchHasMore() || this.searchCursor === null) return;
    this.loadingSearch.set(true);
    this.fetchSearch(false);
  }

  private fetchSearch(initial: boolean): void {
    const seq = ++this.searchSeq;
    this.api
      .listMeetingsTimeline({
        direction: 'upcoming', // no effect in search mode: the backend collapses both
        cursor: this.searchCursor,
        limit: PAGE,
        gremiumId: this.gremiumFilter() || undefined,
        q: this.searchQuery().trim(),
      })
      .subscribe({
        next: (page) => {
          if (seq !== this.searchSeq) return;
          this.searchItems.update((cur) => (initial ? page.items : [...cur, ...page.items]));
          this.searchCursor = page.nextCursor;
          this.searchHasMore.set(page.nextCursor !== null);
          this.loadingSearch.set(false);
        },
        error: () => {
          if (seq !== this.searchSeq) return;
          this.loadingSearch.set(false);
        },
      });
  }

  /** Switch the Gremium filter and reload the timeline or the search. */
  selectGremiumFilter(id: string): void {
    this.gremiumFilter.set(id);
    if (this.searchActive()) {
      this.runSearch();
      return;
    }
    this.loadList();
  }

  /** Load the next past page and keep the scroll position across the new height. */
  loadMorePast(el: HTMLElement): void {
    if (this.loadingPast() || !this.pastHasMore() || this.pastCursor === null) return;
    this.loadingPast.set(true);
    const prevHeight = el.scrollHeight;
    this.api
      .listMeetingsTimeline({
        direction: 'past',
        cursor: this.pastCursor,
        limit: PAGE,
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
          requestAnimationFrame(() => {
            el.scrollTop += el.scrollHeight - prevHeight;
          });
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
        limit: PAGE,
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

  /** Replace an updated meeting in both directions after a settings save. */
  replaceInTimeline(updated: Meeting): void {
    const repl = (list: Meeting[]): Meeting[] =>
      list.map((x) => (x.id === updated.id ? updated : x));
    this.upcomingItems.update(repl);
    this.pastItems.update(repl);
  }

  /** Remove a deleted meeting from both directions. */
  removeFromTimeline(id: Uuid): void {
    const rm = (list: Meeting[]): Meeting[] => list.filter((x) => x.id !== id);
    this.upcomingItems.update(rm);
    this.pastItems.update(rm);
  }

  /** Initial load: first upcoming AND past page in parallel. */
  loadList(): void {
    // Plain Gremium members also see their timeline, filtered on the server.
    if (
      !this.auth.can('meeting.manage') &&
      !this.auth.can('protocol.write') &&
      !(this.auth.gremien().length > 0)
    )
      return;
    this.didInitialScroll = false;
    this.upcomingItems.set([]);
    this.pastItems.set([]);
    this.upcomingCursor = null;
    this.pastCursor = null;
    this.upcomingHasMore.set(false);
    this.pastHasMore.set(false);
    this.loadingList.set(true);
    forkJoin({
      upcoming: this.api.listMeetingsTimeline({
        direction: 'upcoming',
        limit: PAGE,
        gremiumId: this.gremiumFilter() || undefined,
      }),
      past: this.api.listMeetingsTimeline({
        direction: 'past',
        limit: PAGE,
        gremiumId: this.gremiumFilter() || undefined,
      }),
    }).subscribe({
      next: ({ upcoming, past }) => {
        this.loadingList.set(false);
        this.upcomingItems.set(upcoming.items);
        this.upcomingCursor = upcoming.nextCursor;
        this.upcomingHasMore.set(upcoming.nextCursor !== null);
        // "past" arrives newest-first. Reverse it: oldest on top, newest at "now".
        this.pastItems.set([...past.items].reverse());
        this.pastCursor = past.nextCursor;
        this.pastHasMore.set(past.nextCursor !== null);
      },
      error: () => {
        this.loadingList.set(false);
        this.upcomingItems.set([]);
        this.pastItems.set([]);
      },
    });
  }
}
