import { DOCUMENT } from '@angular/common';
import { DestroyRef, Injectable, inject, signal } from '@angular/core';

/**
 * The visual viewport must lose more than this many CSS pixels before the service calls
 * it a keyboard. A phone keyboard takes at least about 200 px; the address bar of a
 * mobile browser that slides in or out takes about 60 px and is no keyboard.
 */
export const KEYBOARD_MIN_HEIGHT = 120;

/**
 * The on-screen keyboard is open: the visual viewport is clearly shorter than the
 * tallest it was at the same width.
 *
 * The focus of a text field does not say this. On Android the back gesture or the
 * hide key of the keyboard closes the keyboard and the field keeps the focus, so a
 * rule on `:focus` alone keeps the bottom bar away until the next tap elsewhere.
 *
 * The height is `visualViewport.height * scale`, so a pinch zoom does not count. A new
 * width (a turn of the phone, a split screen) starts a new reference height. Without a
 * `visualViewport`, `open` stays false: the bottom bar then stays while the person
 * types, which is the safe side.
 */
@Injectable({ providedIn: 'root' })
export class KeyboardService {
  private readonly view = inject(DOCUMENT).defaultView;

  /** The on-screen keyboard covers part of the viewport. */
  readonly open = signal(false);

  private width = 0;
  private tallest = 0;

  constructor() {
    const vv = this.view?.visualViewport;
    if (!vv) return;
    const update = (): void => this.measure(vv);
    vv.addEventListener('resize', update);
    inject(DestroyRef).onDestroy(() => vv.removeEventListener('resize', update));
    update();
  }

  private measure(vv: VisualViewport): void {
    const width = Math.round(vv.width * vv.scale);
    const height = vv.height * vv.scale;
    if (width !== this.width) {
      this.width = width;
      this.tallest = height;
    }
    this.tallest = Math.max(this.tallest, height);
    this.open.set(this.tallest - height > KEYBOARD_MIN_HEIGHT);
  }
}
