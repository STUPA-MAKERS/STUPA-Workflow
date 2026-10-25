import { Injectable, computed, signal } from '@angular/core';

/**
 * Delay before the loading bar appears. The same 300ms as the skeletons (`.skel-in`), so a
 * fast answer shows neither, and a slow one shows both at the same moment.
 */
const SHOW_DELAY_MS = 300;
/** Minimum time the bar stays visible after it appears. This stops a flash. */
const MIN_VISIBLE_MS = 400;

/**
 * Global loading state of the loading bar. It counts the in-flight HTTP requests through the
 * {@link loadingInterceptor}. `visible` turns on after {@link SHOW_DELAY_MS} if at
 * least one request still runs. It then stays on for at least {@link MIN_VISIBLE_MS}.
 * This keeps the bar from a flicker on fast responses.
 */
@Injectable({ providedIn: 'root' })
export class LoadingService {
  private count = 0;
  /** The count as a signal, for {@link active}. */
  private readonly running = signal(0);
  /**
   * At least one counted request runs, without the delay of the bar. Pull to refresh
   * waits on it: its reload counts on the bar (`visibly`).
   */
  readonly active = computed(() => this.running() > 0);
  private shownAt = 0;
  private showTimer: ReturnType<typeof setTimeout> | null = null;
  private hideTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly _visible = signal(false);
  /** True when the app must show the loading bar. */
  readonly visible = this._visible.asReadonly();

  /**
   * The clock, an overridable hook like `setTimer` and `clearTimer`, so tests run
   * deterministically without jest fake timers or zone.js interaction.
   */
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
    this.running.set(this.count);
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
    this.running.set(this.count);
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
