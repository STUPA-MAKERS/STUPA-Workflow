import { Injectable, effect, inject, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import {
  EMPTY,
  Observable,
  Subject,
  catchError,
  debounceTime,
  expand,
  filter,
  forkJoin,
  interval,
  map,
  merge,
  of,
  reduce,
  switchMap,
} from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { WsService } from '@core/ws/ws.service';
import { NavService } from './nav.service';

/** Navigations and live events in this window give one request, not one each. */
export const RAIL_STATUS_DEBOUNCE_MS = 400;

/**
 * The slowest the marks can go stale without a navigation. A faster poll would put load
 * on the server for every open tab; the navigation and the meeting events already
 * cover the moments that matter.
 */
export const RAIL_STATUS_POLL_MS = 60_000;

/**
 * The upcoming timeline sorts by the planned date, not by the status. A live meeting
 * normally comes first (its date is before now), but a meeting that started before its
 * planned time, or one without a date, sorts after the planned meetings in front of it.
 * The service therefore reads page after page until it sees a live meeting or the end.
 * The upcoming list is short in practice, so one page is almost always enough.
 */
export const LIVE_PAGE_LIMIT = 50;

/** The most pages one refresh reads; a guard against an endless cursor chain. */
export const LIVE_MAX_PAGES = 4;

/**
 * The marks of the navigation: the number of open tasks and whether a meeting runs now.
 *
 * Sources:
 * - tasks: `GET /applications/tasks` (the length of the list);
 * - live: `GET /meetings/timeline?direction=upcoming`, where every live meeting is
 *   upcoming (backend `listing.py`), only if the principal sees the meetings entry. The
 *   service follows `nextCursor` until a live meeting shows up (see
 *   {@link LIVE_PAGE_LIMIT}).
 *
 * Both requests skip the global loading overlay (`skipLoading` in `ApiClient`): a mark in
 * the rail must never cover the page.
 *
 * Refresh: at sign-in, after a navigation, after a `meeting_state` frame of an open
 * meeting channel, and every {@link RAIL_STATUS_POLL_MS} while the tab is visible. A
 * debounce folds a burst into one request.
 */
@Injectable({ providedIn: 'root' })
export class RailStatusService {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly nav = inject(NavService);

  private readonly _taskCount = signal<number | null>(null);
  private readonly _live = signal(false);

  /** Open tasks, or `null` before the first answer and after a failed one. */
  readonly taskCount = this._taskCount.asReadonly();
  /** A meeting the principal can see runs now. */
  readonly live = this._live.asReadonly();

  private readonly manual = new Subject<void>();

  constructor() {
    const router = inject(Router);
    const ws = inject(WsService);

    merge(
      this.manual,
      router.events.pipe(filter((e) => e instanceof NavigationEnd)),
      ws.meetingStates$,
      interval(RAIL_STATUS_POLL_MS).pipe(filter(() => this.pageVisible())),
    )
      .pipe(
        debounceTime(RAIL_STATUS_DEBOUNCE_MS),
        filter(() => this.auth.isAuthenticated()),
        switchMap(() => this.load()),
        takeUntilDestroyed(),
      )
      .subscribe(({ tasks, live }) => {
        this._taskCount.set(tasks);
        this._live.set(live);
      });

    // Load at sign-in; forget everything at sign-out.
    effect(() => {
      const signedIn = this.auth.isAuthenticated();
      untracked(() => {
        if (signedIn) {
          this.manual.next();
        } else {
          this._taskCount.set(null);
          this._live.set(false);
        }
      });
    });
  }

  /**
   * Ask again after an action that changes the task list without a navigation: a
   * transition or a ballot on the application page.
   */
  refresh(): void {
    this.manual.next();
  }

  private load(): Observable<{ tasks: number | null; live: boolean }> {
    const tasks = this.api.listTasks().pipe(
      map((items) => items.length),
      catchError(() => of(null)),
    );
    const live = this.nav.meetingsVisible() ? this.anyLive() : of(false);
    return forkJoin({ tasks, live });
  }

  /** `true` as soon as one page of the upcoming timeline holds a live meeting. */
  private anyLive(): Observable<boolean> {
    const page = (cursor: string | null) =>
      this.api.listMeetingsTimeline({ direction: 'upcoming', limit: LIVE_PAGE_LIMIT, cursor });
    return page(null).pipe(
      expand((p, i) =>
        p.nextCursor && i + 1 < LIVE_MAX_PAGES && !p.items.some((m) => m.status === 'live')
          ? page(p.nextCursor)
          : EMPTY,
      ),
      map((p) => p.items.some((m) => m.status === 'live')),
      reduce((seen, hit) => seen || hit, false),
      catchError(() => of(false)),
    );
  }

  private pageVisible(): boolean {
    return typeof document === 'undefined' || document.visibilityState !== 'hidden';
  }
}
