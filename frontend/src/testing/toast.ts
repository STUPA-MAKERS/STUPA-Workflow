import { type ToastKind, type ToastOptions, ToastService } from '@stupa-makers/ui-kit';

/**
 * One jest function per toast kind; `show({ text, kind })` and `show(text, kind)` call the one of
 * its kind with the text.
 */
export type ToastKindSpies = { readonly [K in ToastKind]: jest.Mock };

const KINDS: readonly ToastKind[] = ['info', 'success', 'warning', 'error'];
const MARK = Symbol('toastKindSpies');

/**
 * Gives a toast service (the real one or a mock) a jest function per kind, so a spec checks
 * `expect(toast.error).toHaveBeenCalledWith('…')`. `show` still runs and returns its id.
 * A second call returns the same functions.
 */
export function kindSpies<T extends object>(target: T): T & ToastKindSpies & { show: jest.Mock } {
  const t = target as T & ToastKindSpies & { show: jest.Mock; [MARK]?: true };
  if (t[MARK]) return t;
  const spies = Object.fromEntries(KINDS.map((k) => [k, jest.fn()])) as ToastKindSpies;
  const inner = (target as { show?: (o: ToastOptions) => number }).show?.bind(target);
  const show = jest.fn((arg: ToastOptions | string, kind?: ToastKind) => {
    const o: ToastOptions = typeof arg === 'string' ? { text: arg, kind } : arg;
    spies[o.kind ?? 'info'](o.text);
    return inner ? inner(o) : 1;
  });
  return Object.assign(t, spies, { show, [MARK]: true as const });
}

/** A mock toast service: jest functions per kind, `show`, `dismiss` and `act`. */
export function toastMock(): ToastKindSpies & {
  show: jest.Mock;
  dismiss: jest.Mock;
  act: jest.Mock;
} {
  const base: { dismiss: jest.Mock; act: jest.Mock } = { dismiss: jest.fn(), act: jest.fn() };
  return kindSpies(base);
}

/** A real `ToastService` with a jest function per kind (see {@link kindSpies}). */
export function realToastWithSpies(): ToastService & ToastKindSpies {
  return kindSpies(new ToastService());
}
