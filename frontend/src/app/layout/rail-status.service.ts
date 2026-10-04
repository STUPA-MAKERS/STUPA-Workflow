import { Injectable, effect, inject, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import {
  Observable,
  Subject,
  catchError,
  debounceTime,
  filter,
  forkJoin,
  interval,
  map,
  merge,
  of,
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

/** The upcoming page holds live meetings first, so a short page is enough. */
const LIVE_PAGE_LIMIT = 5;

/**
 * The marks of the navigation: the number of open tasks and whether a meeting runs now.
 *
 * Sources:
 * - tasks: `GET /applications/tasks` (the length of the list);
 * - live: `GET /meetings/timeline?direction=upcoming`, where every live meeting is
 *   upcoming (backend `listing.py`), only if the principal sees the meetings entry.
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

  /** Ask again, for example after an action that changes the task list. */
  refresh(): void {
    this.manual.next();
  }

  private load(): Observable<{ tasks: number | null; live: boolean }> {
    const tasks = this.api.listTasks().pipe(
      map((items) => items.length),
      catchError(() => of(null)),
    );
    const live = this.nav.meetingsVisible()
      ? this.api.listMeetingsTimeline({ direction: 'upcoming', limit: LIVE_PAGE_LIMIT }).pipe(
          map((page) => page.items.some((m) => m.status === 'live')),
          catchError(() => of(false)),
        )
      : of(false);
    return forkJoin({ tasks, live });
  }

  private pageVisible(): boolean {
    return typeof document === 'undefined' || document.visibilityState !== 'hidden';
  }
}
