import { DestroyRef, type Signal, inject, signal } from '@angular/core';

/**
 * A signal that follows a CSS media query, for example `MEDIA.phone` of the ui-kit.
 *
 * Call it in an injection context (a constructor or a field initializer). The listener
 * goes away with the injector.
 */
export function mediaQuerySignal(query: string): Signal<boolean> {
  const media = window.matchMedia(query);
  const state = signal(media.matches);
  const onChange = (event: MediaQueryListEvent): void => state.set(event.matches);
  media.addEventListener('change', onChange);
  inject(DestroyRef).onDestroy(() => media.removeEventListener('change', onChange));
  return state.asReadonly();
}
