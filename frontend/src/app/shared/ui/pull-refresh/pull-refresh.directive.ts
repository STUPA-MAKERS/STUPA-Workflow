import {
  type ComponentRef,
  DestroyRef,
  Directive,
  ElementRef,
  NgZone,
  ViewContainerRef,
  inject,
  input,
  output,
} from '@angular/core';
import { freshly } from '@core/cache/cache.interceptor';
import { visibly } from '@core/loading/loading.interceptor';
import { LoadingService } from '@core/loading/loading.service';
import {
  GESTURE_SLOP,
  haptic,
  modalOpen,
  motionMs,
  motionReduced,
  touchGesturesOn,
} from '@stupa-makers/ui-kit';
import { PullRefreshRingComponent } from './pull-refresh-ring.component';

/** A release at this pull (px) or more reloads the list. */
export const PULL_THRESHOLD = 64;
/** While the list loads, the rows stay this far down (px), with the ring in the gap. */
export const PULL_HOLD = 52;
/** The ring turns at least this long, so a fast answer does not only flash it (ms). */
export const PULL_MIN_MS = 600;
/** The ring gives up after this time, even when a request still runs (ms). */
const PULL_MAX_MS = 15_000;
/** How often the directive asks whether the reload is done (ms). */
const POLL_MS = 100;

/**
 * The rubber band of the pull: the finger moves `dy` px, the rows move less and less, up
 * to 1.76 × the threshold. At the threshold the rows follow the finger at about 2/3.
 */
export function rubberBand(dy: number, threshold = PULL_THRESHOLD): number {
  if (dy <= 0) return 0;
  return 1.76 * threshold * (1 - Math.exp(-dy / (1.6 * threshold)));
}

type Phase = 'idle' | 'pull' | 'load' | 'settle';

/**
 * Pull to refresh on the rows of a list pane (phone, touch screen), as on iOS: the rows
 * move down with a rubber band and a ring fills in the gap above them; the header, the
 * search and the chips above the host stay still.
 *
 * Put it on the scroll area of the rows (the element below the filter bar). The pull
 * starts only while the list is at its top (the window and the host do not scroll),
 * and only for a move that is mostly downwards after {@link GESTURE_SLOP} px; every other
 * move stays a scroll. A release at {@link PULL_THRESHOLD} px or more holds the rows at
 * {@link PULL_HOLD} px with the ring turning, and emits `appPullRefresh`; the page calls
 * the reload of its list. The emit runs inside `visibly` and `freshly`, so the GETs that
 * the reload starts skip the stored answer of the HTTP cache and run the bar of the app.
 * The rows spring back when those requests are done and `pullRefreshBusy` is false, but
 * not before {@link PULL_MIN_MS}. A shorter release springs back at once. The threshold
 * gives one `haptic('tick')` per crossing.
 *
 * Nothing happens on a desktop or with a fine pointer, while `pullRefreshBusy` is true
 * (the list loads already), during a reload and while a modal layer is open. The listener
 * of the move is not passive: it calls `preventDefault()` for the pull only, so the
 * browser does not run its own pull to refresh or the rubber band of the page.
 */
@Directive({
  selector: '[appPullRefresh]',
  standalone: true,
})
export class PullRefreshDirective {
  private readonly el = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
  private readonly zone = inject(NgZone);
  private readonly vcr = inject(ViewContainerRef);
  private readonly loading = inject(LoadingService);

  /** The list loads already: no pull, and the rows wait for it after a pull. */
  readonly busy = input(false, { alias: 'pullRefreshBusy' });
  /** The person pulled far enough: reload the list. */
  readonly refresh = output<void>({ alias: 'appPullRefresh' });

  private phase: Phase = 'idle';
  private track: { y: number; x: number; lock: 'y' | null; pull: number; armed: boolean } | null = null;
  private ring: ComponentRef<PullRefreshRingComponent> | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    const start = (e: TouchEvent): void => this.onStart(e);
    const move = (e: TouchEvent): void => this.onMove(e);
    const end = (): void => this.onEnd(false);
    const cancel = (): void => this.onEnd(true);
    this.zone.runOutsideAngular(() => {
      this.el.addEventListener('touchstart', start, { passive: true });
      this.el.addEventListener('touchmove', move, { passive: false });
      this.el.addEventListener('touchend', end, { passive: true });
      this.el.addEventListener('touchcancel', cancel, { passive: true });
    });
    inject(DestroyRef).onDestroy(() => {
      this.el.removeEventListener('touchstart', start);
      this.el.removeEventListener('touchmove', move);
      this.el.removeEventListener('touchend', end);
      this.el.removeEventListener('touchcancel', cancel);
      this.clearTimer();
      this.ring?.destroy();
    });
  }

  private atTop(): boolean {
    const page = document.scrollingElement?.scrollTop ?? 0;
    return window.scrollY <= 0 && page <= 0 && this.el.scrollTop <= 0;
  }

  private onStart(e: TouchEvent): void {
    if (this.phase !== 'idle' || e.touches.length !== 1 || this.busy()) return;
    if (!touchGesturesOn() || modalOpen(document, this.el) || !this.atTop()) return;
    const t = e.touches[0];
    this.track = { x: t.clientX, y: t.clientY, lock: null, pull: 0, armed: false };
  }

  /** An undecided move down must not start the pull-to-refresh of the browser before the lock. */
  private onMove(e: TouchEvent): void {
    const track = this.track;
    if (!track) return;
    if (e.touches.length !== 1) {
      this.onEnd(true);
      return;
    }
    const t = e.touches[0];
    const dx = t.clientX - track.x;
    const dy = t.clientY - track.y;
    if (track.lock === null) {
      if (Math.abs(dx) <= GESTURE_SLOP && Math.abs(dy) <= GESTURE_SLOP) {
        if (dy > 0 && dy >= Math.abs(dx) && e.cancelable) e.preventDefault();
        return;
      }
      if (!(dy > 0 && Math.abs(dy) > Math.abs(dx))) {
        this.track = null;
        return;
      }
      track.lock = 'y';
      this.phase = 'pull';
    }
    if (e.cancelable) e.preventDefault();
    track.pull = rubberBand(dy);
    this.place(track.pull, 0);
    const armed = track.pull >= PULL_THRESHOLD;
    if (armed !== track.armed) {
      track.armed = armed;
      if (armed) haptic('tick');
    }
  }

  private onEnd(cancelled: boolean): void {
    const track = this.track;
    this.track = null;
    if (!track || track.lock === null) return;
    if (!cancelled && track.pull >= PULL_THRESHOLD) this.load();
    else this.springBack();
  }

  private ms(): number {
    return motionReduced() ? 0 : motionMs(this.el, '--motion-slow', 280);
  }

  /** The rows `pull` px down, the ring in the gap above them. */
  private place(pull: number, ms: number): void {
    const s = this.el.style;
    s.transition = ms > 0 ? `transform ${ms}ms var(--ease-enter)` : 'none';
    s.transform = pull > 0 ? `translateY(${pull}px)` : '';
    const ring = this.ensureRing();
    ring.paint(this.el.offsetTop, pull, pull / PULL_THRESHOLD, ms);
  }

  /** The ring is a sibling after the host, so it does not move with the rows. */
  private ensureRing(): PullRefreshRingComponent {
    if (!this.ring) {
      this.ring = this.vcr.createComponent(PullRefreshRingComponent);
      this.ring.changeDetectorRef.detectChanges();
    }
    return this.ring.instance;
  }

  /** Hold the rows, turn the ring, reload; spring back when the reload is done. */
  private load(): void {
    this.phase = 'load';
    this.place(PULL_HOLD, this.ms());
    this.ensureRing().spin(true);
    const started = Date.now();
    this.zone.run(() => visibly(() => freshly(() => this.refresh.emit())));
    const check = (): void => {
      const elapsed = Date.now() - started;
      const done = !this.loading.active() && !this.busy();
      if ((done && elapsed >= PULL_MIN_MS) || elapsed >= PULL_MAX_MS) {
        this.ensureRing().spin(false);
        this.springBack();
        return;
      }
      this.after(check, POLL_MS);
    };
    this.after(check, PULL_MIN_MS);
  }

  private springBack(): void {
    this.phase = 'settle';
    const ms = this.ms();
    this.place(0, ms);
    this.after(() => this.reset(), ms);
  }

  private reset(): void {
    this.phase = 'idle';
    this.el.style.removeProperty('transition');
    this.el.style.removeProperty('transform');
  }

  private after(run: () => void, ms: number): void {
    this.clearTimer();
    if (ms <= 0) {
      run();
      return;
    }
    this.timer = setTimeout(() => {
      this.timer = null;
      run();
    }, ms);
  }

  private clearTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }
}
