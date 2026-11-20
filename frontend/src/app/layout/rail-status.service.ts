import { DOCUMENT } from '@angular/common';
import { Injectable, effect, inject, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  EMPTY,
  Subject,
  catchError,
  debounceTime,
  distinctUntilChanged,
  filter,
  fromEvent,
  interval,
  merge,
  switchMap,
} from 'rxjs';
import { ActivityApiService } from '@core/api/activity.service';
import { AuthService } from '@core/auth/auth.service';
import { HttpCacheService } from '@core/cache/http-cache.service';
import { WsService } from '@core/ws/ws.service';

/** Live events and returns to the app in this window give one request, not one each. */
export const RAIL_STATUS_DEBOUNCE_MS = 400;

/**
 * Writes in this window give one request. A protocol autosaves about once a second while
 * someone types, so a short window would read the marks at that rate.
 */
export const RAIL_STATUS_WRITE_DEBOUNCE_MS = 2_000;

/**
 * The slowest the marks can go stale without a change of this tab. A faster poll would put
 * load on the server for every open tab; the writes, the meeting events and the return to
 * the app already cover the moments that matter.
 */
export const RAIL_STATUS_POLL_MS = 60_000;

/** The reads of this service, which change no mark, so a write there starts no refresh. */
const OWN_WRITES = ['/api/activity/seen'];

/**
 * The marks of the navigation: the number of open tasks and of new tickets, and the dots
 * for a running meeting and for a waiting event (spec 002001).
 *
 * One read, `GET /navigation/status`, gives all four. The server applies the gate of each
 * module: the tasks are the applications to act on plus my open To-Dos (the two groups of
 * the "Aufgaben" page), the tickets need `ticket.manage`, the live dot needs a meeting
 * that the meetings timeline shows, and a feature that is off gives an empty mark. A
 * failed read clears the counts and the dots. The read skips the loading bar: a mark in
 * the rail must never cover the page.
 *
 * Refresh: at sign-in, after each write that the server answered (debounced
 * {@link RAIL_STATUS_WRITE_DEBOUNCE_MS}), after a `meeting_state` frame that changes the
 * status, when the app becomes visible again, and every {@link RAIL_STATUS_POLL_MS} while
 * the tab is visible. A navigation alone does not refresh: it changes no mark, and its
 * reads would stand beside the reads of the new page (spec 002001). A `meeting_state` with
 * the same status (a TOP switch, a handover, a prepared vote) does not refresh: the live
 * mark follows the status only, and every viewer of a meeting gets the frame at the same
 * moment.
 */
@Injectable({ providedIn: 'root' })
export class RailStatusService {
  private readonly auth = inject(AuthService);
  private readonly activity = inject(ActivityApiService);
  private readonly document = inject(DOCUMENT);

  private readonly _taskCount = signal<number | null>(null);
  private readonly _ticketCount = signal<number | null>(null);
  private readonly _live = signal(false);
  private readonly _activityNew = signal(false);

  /** Open tasks, or `null` before the first answer and after a failed one. */
  readonly taskCount = this._taskCount.asReadonly();
  /** New tickets, or `null` without `ticket.manage`, before the first answer and after a failed one. */
  readonly ticketCount = this._ticketCount.asReadonly();
  /** A meeting the principal can see runs now. */
  readonly live = this._live.asReadonly();
  /** An event of another person waits on the activity page (a dot, never a number). */
  readonly activityNew = this._activityNew.asReadonly();

  private readonly manual = new Subject<void>();

  constructor() {
    const ws = inject(WsService);
    const writes = inject(HttpCacheService).written.pipe(
      filter((path) => !OWN_WRITES.includes(path)),
      debounceTime(RAIL_STATUS_WRITE_DEBOUNCE_MS),
    );
    const back = fromEvent(this.document, 'visibilitychange').pipe(filter(() => this.pageVisible()));

    merge(
      this.manual,
      writes,
      back,
      ws.meetingStates$.pipe(distinctUntilChanged((a, b) => a.status === b.status)),
      interval(RAIL_STATUS_POLL_MS).pipe(filter(() => this.pageVisible())),
    )
      .pipe(
        debounceTime(RAIL_STATUS_DEBOUNCE_MS),
        filter(() => this.auth.isAuthenticated()),
        switchMap(() =>
          this.activity.navigationStatus().pipe(
            catchError(() => {
              this.clear();
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe(({ tasks, tickets, live, activity }) => {
        this._taskCount.set(tasks);
        this._ticketCount.set(tickets);
        this._live.set(live);
        this._activityNew.set(activity);
      });

    effect(() => {
      const signedIn = this.auth.isAuthenticated();
      untracked(() => {
        if (signedIn) {
          this.manual.next();
        } else {
          this.clear();
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

  /** The activity page was seen: the dot goes at once, before the next refresh. */
  activitySeen(): void {
    this._activityNew.set(false);
  }

  private clear(): void {
    this._taskCount.set(null);
    this._ticketCount.set(null);
    this._live.set(false);
    this._activityNew.set(false);
  }

  private pageVisible(): boolean {
    return this.document.visibilityState !== 'hidden';
  }
}
