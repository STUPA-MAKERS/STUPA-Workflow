import { DestroyRef, inject } from '@angular/core';
import { LIVE_SEARCH_DEBOUNCE_MS } from '@stupa-makers/ui-kit';

/** A function that runs only after a pause. Make it with {@link debounced}. */
export interface Debounced<A extends unknown[]> {
  /** Run after `ms` without a further call. A new call starts the wait again. */
  (...args: A): void;
  /** Drop the call that waits. */
  cancel(): void;
}

/**
 * The debounce of a field that is not a search field (a filter typed into a number
 * field, an e-mail lookup), or of a search that writes the URL. A search field with a
 * request uses {@link liveSearch}, which also cancels a request that is still out.
 *
 * The last call wins: its arguments run once the pause is over. Call it in an injection
 * context (a field initializer or the constructor): a waiting call is dropped when the
 * injector is destroyed.
 */
export function debounced<A extends unknown[]>(
  fn: (...args: A) => void,
  ms: number = LIVE_SEARCH_DEBOUNCE_MS,
): Debounced<A> {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const cancel = (): void => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  const call = (...args: A): void => {
    cancel();
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, ms);
  };
  inject(DestroyRef).onDestroy(cancel);
  return Object.assign(call, { cancel });
}
