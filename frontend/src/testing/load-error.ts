import { TestBed } from '@angular/core/testing';
import { type Toast, type ToastKind, type ToastOptions, ToastService } from '@stupa-makers/ui-kit';

/** The open load error toast of `app-load-error` (§ui-kit:000576): a danger toast with a retry. */
function findToast(): Toast | undefined {
  return TestBed.inject(ToastService)
    .toasts()
    .find((t) => t.variant === 'danger' && t.action === 'Erneut versuchen');
}

/** The messages of the open error toasts (§ui-kit:000633: a failed request shows as a toast). */
export function errorToasts(): string[] {
  return TestBed.inject(ToastService)
    .toasts()
    .filter((t) => t.variant === 'danger')
    .map((t) => t.message);
}

/** The message of the open load error toast, or null without one. */
export function loadErrorToast(): string | null {
  return findToast()?.message ?? null;
}

/** Presses "Erneut versuchen" on the open load error toast. */
export function retryLoadError(): void {
  const toast = findToast();
  if (!toast) throw new Error('no load error toast is open');
  TestBed.inject(ToastService).act(toast.id);
}

/**
 * A real `ToastService` with the jest functions of `mock`: `show({ text, kind })` also calls
 * `mock[kind](text)`, so a spec checks `success` and `error` with jest functions. The load
 * error toast still works: `show`, `dismiss` and `act` stay the real ones. Use it as
 * `{ provide: ToastService, useFactory: () => toastWith(toast) }`.
 */
export function toastWith(
  mock: Partial<Record<ToastKind | 'dismiss' | 'act', unknown>>,
): ToastService {
  const service = new ToastService();
  const real = service.show.bind(service);
  const m = mock as Partial<Record<ToastKind, (text: string) => void>>;
  // A plain toast of a mocked kind goes only to the jest function, as `success(text)` did:
  // a real one would hold a timer that `whenStable` waits for. A toast with an action or one
  // that stays (the load error toast) is real.
  const show = (o: ToastOptions): number => {
    const fn = m[o.kind ?? 'info'];
    if (fn && !o.action && !o.sticky) {
      fn(o.text);
      return -1;
    }
    fn?.(o.text);
    return real(o);
  };
  const kinds = Object.fromEntries(
    Object.entries(mock).filter(([k]) => ['info', 'success', 'warning', 'error'].includes(k)),
  );
  return Object.assign(service, kinds, { show });
}
