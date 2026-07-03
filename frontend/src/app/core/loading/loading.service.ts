import { Injectable, signal } from '@angular/core';

/** Delay before the overlay appears — de-flickers fast requests. */
const SHOW_DELAY_MS = 150;
/** Minimum visible duration once shown — prevents flashing. */
const MIN_VISIBLE_MS = 400;

/**
 * Global loading state. Counts in-flight HTTP requests (via the
 * {@link loadingInterceptor}); `visible` turns on after {@link SHOW_DELAY_MS} as
 * long as at least one request runs, and stays visible for at least
 * {@link MIN_VISIBLE_MS}. This keeps the overlay from flickering on fast responses.
 */
@Injectable({ providedIn: 'root' })
export class LoadingService {
  private count = 0;
  private shownAt = 0;
  private showTimer: ReturnType<typeof setTimeout> | null = null;
  private hideTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly _visible = signal(false);
  /** True when the loading overlay should be shown. */
  readonly visible = this._visible.asReadonly();

  // Timer/clock as overridable hooks → deterministically testable (without
  // jest fake-timer / zone.js interaction).
  protected now(): number {
    return Date.now();
  }
  protected setTimer(fn: () => void, ms: number): ReturnType<typeof setTimeout> {
    return setTimeout(fn, ms);
  }
  protected clearTimer(id: ReturnType<typeof setTimeout>): void {
    clearTimeout(id);
  }

  /** Register an in-flight request. */
  inc(): void {
    this.count++;
    if (this.count !== 1) return;
    this.clearHide();
    if (this._visible() || this.showTimer !== null) return;
    this.showTimer = this.setTimer(() => {
      this.showTimer = null;
      if (this.count > 0) {
        this._visible.set(true);
        this.shownAt = this.now();
      }
    }, SHOW_DELAY_MS);
  }

  /** Deregister a completed request (success or error). */
  dec(): void {
    if (this.count > 0) this.count--;
    if (this.count === 0) this.scheduleHide();
  }

  private scheduleHide(): void {
    if (this.showTimer !== null) {
      this.clearTimer(this.showTimer);
      this.showTimer = null;
    }
    if (!this._visible()) return;
    const remaining = MIN_VISIBLE_MS - (this.now() - this.shownAt);
    if (remaining <= 0) {
      this._visible.set(false);
      return;
    }
    this.hideTimer = this.setTimer(() => {
      this.hideTimer = null;
      if (this.count === 0) this._visible.set(false);
    }, remaining);
  }

  private clearHide(): void {
    if (this.hideTimer !== null) {
      this.clearTimer(this.hideTimer);
      this.hideTimer = null;
    }
  }
}
