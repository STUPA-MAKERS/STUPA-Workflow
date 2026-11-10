import { TestBed } from '@angular/core/testing';
import { type Toast, ToastService } from '@stupa-makers/ui-kit';

/** The open load error toast of `app-load-error` (§ 000576): a danger toast with a retry. */
function findToast(): Toast | undefined {
  return TestBed.inject(ToastService)
    .toasts()
    .find((t) => t.variant === 'danger' && t.action === 'Erneut versuchen');
}

/** The messages of the open error toasts (§ 000633: a failed request shows as a toast). */
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
 * A real `ToastService` whose methods in `mock` are replaced, for a spec that checks
 * `success` and `error` with jest functions. The load error toast still works. Use it as
 * `{ provide: ToastService, useFactory: () => toastWith(toast) }`.
 */
export function toastWith(mock: Partial<Record<keyof ToastService, unknown>>): ToastService {
  return Object.assign(new ToastService(), mock);
}
