import { Injectable, signal } from '@angular/core';

/** Verzögerung, bevor der Overlay erscheint — entflackert schnelle Requests. */
const SHOW_DELAY_MS = 150;
/** Mindest-Anzeigedauer, sobald sichtbar — verhindert Aufblitzen. */
const MIN_VISIBLE_MS = 400;

/**
 * Globaler Lade-Zustand (#loading). Zählt laufende HTTP-Requests (über den
 * {@link loadingInterceptor}); `visible` wird **nach** {@link SHOW_DELAY_MS} aktiv,
 * solange mindestens ein Request läuft, und bleibt mindestens {@link MIN_VISIBLE_MS}
 * sichtbar. So flackert der Ladebildschirm nicht bei schnellen Antworten.
 */
@Injectable({ providedIn: 'root' })
export class LoadingService {
  private count = 0;
  private shownAt = 0;
  private showTimer: ReturnType<typeof setTimeout> | null = null;
  private hideTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly _visible = signal(false);
  /** True, wenn der Ladebildschirm angezeigt werden soll. */
  readonly visible = this._visible.asReadonly();

  // Timer/Uhr als überschreibbare Hooks → deterministisch testbar (ohne jest-Fake-
  // Timer/zone.js-Wechselwirkung).
  protected now(): number {
    return Date.now();
  }
  protected setTimer(fn: () => void, ms: number): ReturnType<typeof setTimeout> {
    return setTimeout(fn, ms);
  }
  protected clearTimer(id: ReturnType<typeof setTimeout>): void {
    clearTimeout(id);
  }

  /** Einen laufenden Request registrieren. */
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

  /** Einen abgeschlossenen Request abmelden (Erfolg **oder** Fehler). */
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
