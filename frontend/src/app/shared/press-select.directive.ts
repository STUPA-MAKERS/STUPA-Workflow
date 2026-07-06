import { Directive, input, output } from '@angular/core';

/**
 * Press & hold select mode for mobile card lists.
 *
 * On touch devices (coarse pointer) the checkbox column is hidden; instead a
 * long press (~450 ms) on a card emits `appPressSelectToggle` (entering
 * "select mode"), and while `appPressSelectActive` is true a plain tap toggles
 * too. Clicks on interactive children (buttons/links/inputs) always pass
 * through. On fine-pointer devices the directive is inert — desktop keeps the
 * checkbox column.
 *
 * The host communicates the selected state visually (card colour), not via
 * checkboxes.
 */
@Directive({
  selector: '[appPressSelect]',
  standalone: true,
  host: {
    '(pointerdown)': 'onPointerDown($event)',
    '(pointermove)': 'onPointerMove($event)',
    '(pointerup)': 'onPointerEnd()',
    '(pointercancel)': 'onPointerEnd()',
    '(click)': 'onClick($event)',
    '(contextmenu)': 'onContextMenu($event)',
  },
})
export class PressSelectDirective {
  /** Feature gate (e.g. the user's permission to act on the rows). */
  readonly enabled = input(true, { alias: 'appPressSelectEnabled' });
  /** Select mode active (a selection exists) → plain taps toggle as well. */
  readonly active = input(false, { alias: 'appPressSelectActive' });
  /** Long press / tap-in-select-mode happened — the host toggles the row. */
  readonly toggled = output<void>({ alias: 'appPressSelectToggle' });

  private timer: ReturnType<typeof setTimeout> | null = null;
  private origin: { x: number; y: number } | null = null;
  /** Swallow the click that follows a completed long press (would re-toggle). */
  private suppressNextClick = false;

  /** Touch-first device — own method → stubbable in tests. */
  protected coarsePointer(): boolean {
    return window.matchMedia('(pointer: coarse)').matches;
  }

  private static isInteractive(target: EventTarget | null): boolean {
    return target instanceof Element && target.closest('button, a, input, label') !== null;
  }

  protected onPointerDown(ev: PointerEvent): void {
    if (!this.coarsePointer() || !this.enabled()) return;
    if (PressSelectDirective.isInteractive(ev.target)) return;
    this.cancelPress();
    this.origin = { x: ev.clientX, y: ev.clientY };
    this.timer = setTimeout(() => {
      this.timer = null;
      this.suppressNextClick = true;
      this.toggled.emit();
      navigator.vibrate?.(10);
    }, 450);
  }

  protected onPointerMove(ev: PointerEvent): void {
    if (this.timer === null || !this.origin) return;
    // Finger drifts (scroll intent) → not a long press.
    const dx = ev.clientX - this.origin.x;
    const dy = ev.clientY - this.origin.y;
    if (Math.hypot(dx, dy) > 12) this.cancelPress();
  }

  protected onPointerEnd(): void {
    this.cancelPress();
  }

  private cancelPress(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.origin = null;
  }

  /** In select mode a plain tap on the card toggles; interactive children pass. */
  protected onClick(ev: MouseEvent): void {
    if (this.suppressNextClick) {
      this.suppressNextClick = false;
      ev.preventDefault();
      ev.stopPropagation();
      return;
    }
    if (!this.coarsePointer() || !this.enabled() || !this.active()) return;
    if (PressSelectDirective.isInteractive(ev.target)) return;
    this.toggled.emit();
  }

  /** Long press must not open the browser context menu / text selection on touch. */
  protected onContextMenu(ev: Event): void {
    if (this.coarsePointer() && this.enabled()) ev.preventDefault();
  }
}
