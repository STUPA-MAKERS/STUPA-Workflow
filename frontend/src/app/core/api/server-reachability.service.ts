import { HttpBackend, HttpRequest, HttpResponse } from '@angular/common/http';
import { DestroyRef, Injectable, Injector, computed, effect, inject, signal } from '@angular/core';
import { OfflineService } from '@stupa-makers/ui-kit/pwa';
import { ToastService } from '@stupa-makers/ui-kit';
import { filter, take } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { API_BASE_URL } from './api.config';

/** The answers that mean "the server is not there": no answer, or the proxy in front of it. */
const UNREACHABLE = new Set([0, 502, 503, 504]);

/** How long the app waits between two health checks while the server is unreachable. */
export const HEALTH_POLL_MS = 5_000;

/** Tells whether a failed API answer means that the server is unreachable (§ 000578). */
export function isUnreachableStatus(status: number): boolean {
  return UNREACHABLE.has(status);
}

/**
 * Whether the API server answers (§ 000578, § 000579).
 *
 * `reachabilityInterceptor` reports each API answer. An answer with no status, 502, 503
 * or 504 starts a check of `GET /api/health`. Only a failed check makes the state `down`,
 * because a single route may answer 503 for its own reason (for example the backups page
 * without a recipient). While the state is `down`, the service shows the offline bar with
 * "Server nicht erreichbar" and checks again every {@link HEALTH_POLL_MS}. The first answer
 * 200 makes the state `up` and removes the bar.
 *
 * During a deploy the API container restarts and the reverse proxy answers 502 or 503, while
 * the browser still has network. `navigator.onLine` stays true, so the offline bar of the
 * kit (`OfflineService`) does not show. While the browser is offline, the kit bar shows and
 * this service shows no second bar.
 *
 * The check goes through `HttpBackend`, past the interceptors: it shows no load bar, sends
 * no credentials and does not report itself. The service reads `HttpBackend` only for a
 * check, so a page that shows a load error needs no HTTP providers.
 */
@Injectable({ providedIn: 'root' })
export class ServerReachabilityService {
  private readonly injector = inject(Injector);
  private readonly base = inject(API_BASE_URL);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  private readonly offline = inject(OfflineService);

  private readonly _state = signal<'up' | 'checking' | 'down'>('up');
  /** `checking` while a check after a failed answer runs, `down` after it failed. */
  readonly state = this._state.asReadonly();
  /**
   * The app cannot reach the server now, or it does not know yet: the browser is offline,
   * a check runs, or the server is unreachable. A failed load waits for the end of this
   * state, and then loads again (§ 000579).
   */
  readonly waiting = computed(() => !this.offline.online() || this._state() !== 'up');

  private timer: ReturnType<typeof setTimeout> | null = null;
  private noticeId: number | null = null;

  constructor() {
    effect(() => {
      const show = this._state() === 'down' && this.offline.online();
      if (show) this.showBar();
      else this.hideBar();
    });
    inject(DestroyRef).onDestroy(() => {
      this.clearTimer();
      this.hideBar();
    });
  }

  /** An API request failed with this status. */
  reportFailure(status: number): void {
    if (!isUnreachableStatus(status) || this._state() !== 'up') return;
    this._state.set('checking');
    this.check();
  }

  /** An API request got an answer, so the server is there. */
  reportSuccess(): void {
    if (this._state() === 'up') return;
    this.clearTimer();
    this._state.set('up');
  }

  private check(): void {
    const req = new HttpRequest('GET', `${this.base}/health`);
    this.injector
      .get(HttpBackend)
      .handle(req)
      .pipe(
        filter((e) => e instanceof HttpResponse),
        take(1),
      )
      .subscribe({
        next: () => this.reportSuccess(),
        error: () => this.retryLater(),
      });
  }

  private retryLater(): void {
    if (this._state() === 'up') return;
    this._state.set('down');
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      this.check();
    }, HEALTH_POLL_MS);
  }

  private clearTimer(): void {
    if (this.timer === null) return;
    clearTimeout(this.timer);
    this.timer = null;
  }

  private showBar(): void {
    if (this.noticeId !== null) return;
    this.noticeId = this.toast.showNotice({
      message: this.i18n.translate('pwa.serverUnreachable'),
      variant: 'danger',
      icon: 'cloud-off',
      iconPosition: 'end',
      phonePlacement: 'top',
    });
  }

  private hideBar(): void {
    if (this.noticeId === null) return;
    this.toast.dismiss(this.noticeId);
    this.noticeId = null;
  }
}
