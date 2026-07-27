import { Directive, input, output } from '@angular/core';

/**
 * Press and hold select mode for a mobile card list.
 *
 * A touch device has a coarse pointer and hides the checkbox column. On such a device a
 * long press of about 450 ms on a card emits `appPressSelectToggle` and starts the select
 * mode. While `appPressSelectActive` is true, a plain tap toggles the card too. A click on
 * an interactive child, such as a button, a link or an input, always passes through. On a
 * fine-pointer device the directive stays inert. The desktop keeps the checkbox column.
 *
 * The host shows the selected state with the card color, not with a checkbox.
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
  /** Feature gate, for example the permission of the user to act on the rows. */
  readonly enabled = input(true, { alias: 'appPressSelectEnabled' });
  /** The select mode is active because a selection exists. A plain tap then toggles too. */
  readonly active = input(false, { alias: 'appPressSelectActive' });
  /** A long press or a tap in select mode happened. The host toggles the row. */
  readonly toggled = output<void>({ alias: 'appPressSelectToggle' });

  private timer: ReturnType<typeof setTimeout> | null = null;
  private origin: { x: number; y: number } | null = null;
  /** Swallow the click after a completed long press. That click would toggle again. */
  private suppressNextClick = false;

  /** Report a touch-first device. A separate method lets a test stub the result. */
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
    // A drift of the finger shows a scroll intent. That is not a long press.
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

  /** In select mode a plain tap on the card toggles. An interactive child passes through. */
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

  /** A long press must not open the browser context menu or a text selection on touch. */
  protected onContextMenu(ev: Event): void {
    if (this.coarsePointer() && this.enabled()) ev.preventDefault();
  }
}
