import { DestroyRef, Directive, ElementRef, inject, input, output } from '@angular/core';

/** A press this long opens the menu of the host. */
export const LONG_PRESS_MS = 450;
/** A finger that drifts more than this many pixels scrolls or swipes: no long press. */
export const LONG_PRESS_SLOP = 8;
/** The click that follows the release of a long press comes within this time. */
const CLICK_AFTER_MS = 600;

/**
 * Press and hold: a press of `LONG_PRESS_MS` on the host emits `appLongPress` and gives a
 * short vibration where the device has one. A drift of the pointer by more than
 * `LONG_PRESS_SLOP` pixels, a scroll anywhere on the page, the release and a cancel of the
 * pointer, a pointer that leaves the host stop the press, so a swipe or a scroll over the
 * host stays a swipe or a scroll. The pressed element captures the pointer, so a mouse
 * that leaves the tile still reports its moves and the drift stops the press. The capture
 * is on the pressed element, not on the host: the click of a tap goes to the common
 * ancestor of the targets of pointerdown and pointerup, so a capture on the host would
 * take the click from the button inside.
 *
 * The click of the release after a long press does not reach the host (a capture listener
 * stops it), so a tile that opens on a tap does not open after its menu. The context
 * menu of the host (the context menu key, Shift+F10, a right click) emits `appLongPress`
 * too, so the keyboard reaches the same menu.
 *
 * While `appLongPressOff` is true the directive does nothing. Without it the host has the
 * class `long-press`, which turns off the text callout of a touch device.
 */
@Directive({
  selector: '[appLongPress]',
  standalone: true,
  host: {
    '[class.long-press]': '!off()',
    '(pointerdown)': 'onDown($event)',
    '(pointermove)': 'onMove($event)',
    '(pointerup)': 'onUp()',
    '(pointercancel)': 'cancel()',
    '(pointerleave)': 'cancel()',
    '(keydown)': 'fired = false',
    '(contextmenu)': 'onContextMenu($event)',
  },
})
export class LongPressDirective {
  private readonly el = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;

  readonly off = input(false, { alias: 'appLongPressOff' });
  readonly pressed = output<void>({ alias: 'appLongPress' });

  private timer: ReturnType<typeof setTimeout> | null = null;
  private origin: { x: number; y: number } | null = null;
  /** The press of now opened the menu: the click of its release does not reach the host. */
  protected fired = false;
  private readonly onScroll = (): void => this.cancel();

  constructor() {
    const onClick = (event: Event): void => {
      if (!this.fired) return;
      this.fired = false;
      event.preventDefault();
      event.stopPropagation();
    };
    this.el.addEventListener('click', onClick, true);
    inject(DestroyRef).onDestroy(() => {
      this.el.removeEventListener('click', onClick, true);
      this.cancel();
    });
  }

  protected onDown(event: PointerEvent): void {
    this.fired = false;
    if (this.off() || event.button > 0 || event.isPrimary === false) return;
    this.cancel();
    this.origin = { x: event.clientX, y: event.clientY };
    // A pointer event on the host always has an element of the host as its target.
    const target = event.target as Element;
    try {
      target.setPointerCapture?.(event.pointerId);
    } catch {
      // No active pointer of that id (a synthetic event): the moves reach the host anyway.
    }
    // A scroll does not bubble: the capture phase of the document sees every scroll.
    document.addEventListener('scroll', this.onScroll, true);
    this.timer = setTimeout(() => this.fire(), LONG_PRESS_MS);
  }

  protected onMove(event: PointerEvent): void {
    if (!this.timer || !this.origin) return;
    if (Math.hypot(event.clientX - this.origin.x, event.clientY - this.origin.y) > LONG_PRESS_SLOP) this.cancel();
  }

  protected onUp(): void {
    this.cancel();
    // A release that sends no click (the browser took the press) leaves no stale flag.
    if (this.fired) setTimeout(() => (this.fired = false), CLICK_AFTER_MS);
  }

  protected onContextMenu(event: Event): void {
    if (this.off()) return;
    event.preventDefault();
    if (this.fired) return;
    if (this.timer) {
      // The browser of a touch device can open its menu before the timer: the press wins.
      this.fire();
      return;
    }
    this.pressed.emit();
  }

  /** Stop the press of now. */
  cancel(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.origin = null;
    document.removeEventListener('scroll', this.onScroll, true);
  }

  private fire(): void {
    this.cancel();
    this.fired = true;
    navigator.vibrate?.(10);
    this.pressed.emit();
  }
}
