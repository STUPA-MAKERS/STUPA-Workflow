import { DestroyRef, type Signal, effect, inject } from '@angular/core';
import { PageFrame } from '@stupa-makers/ui-kit';

/**
 * A page that fills the window while `on` is true and scrolls only inside its own
 * columns (the form editor and the flow editor in the pane, spec 003130). The page
 * also sets the class `pane-page` on its host. Clears the fill when the page goes.
 */
export function injectPanePage(on: Signal<boolean>): void {
  const fill = inject(PageFrame).fill;
  effect(() => fill.set(on()));
  inject(DestroyRef).onDestroy(() => fill.set(false));
}
