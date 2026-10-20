import type { ActivatedRouteSnapshot, ViewTransitionInfo } from '@angular/router';
import { markGestureNavigation } from '@stupa-makers/ui-kit';
import { onRouteViewTransition, routeMotion, routePath, withViewTransition } from './motion';

function snap(...levels: string[][]): ActivatedRouteSnapshot {
  let child: ActivatedRouteSnapshot | null = null;
  for (const level of [...levels].reverse()) {
    child = {
      url: level.map((path) => ({ path })),
      firstChild: child,
    } as unknown as ActivatedRouteSnapshot;
  }
  return child as ActivatedRouteSnapshot;
}

function media(matches: Record<string, boolean>): void {
  (window.matchMedia as unknown) = jest.fn((q: string) => ({ matches: !!matches[q] }));
}

const PHONE = '(max-width: 768px)';
const REDUCED = '(prefers-reduced-motion: reduce)';

describe('routePath', () => {
  it('joins the segments from the root to the leaf', () => {
    expect(routePath(snap([], ['antraege'], ['42']))).toEqual(['antraege', '42']);
    expect(routePath(null)).toEqual([]);
  });
});

describe('routeMotion', () => {
  it('fades through between sections', () => {
    expect(routeMotion(['antraege'], ['sitzungen'], false)).toBe('section');
    expect(routeMotion([], ['antraege'], true)).toBe('section');
  });

  it('does nothing inside a section on a wide screen', () => {
    expect(routeMotion(['antraege'], ['antraege', '42'], false)).toBe('none');
    expect(routeMotion([], [], false)).toBe('none');
  });

  it('pushes and pops inside a section on a phone', () => {
    expect(routeMotion(['antraege'], ['antraege', '42'], true)).toBe('push');
    expect(routeMotion(['antraege', '42'], ['antraege'], true)).toBe('pop');
    expect(routeMotion(['antraege', '41'], ['antraege', '42'], true)).toBe('none');
  });
});

describe('onRouteViewTransition', () => {
  let finish: () => void;
  function info(from: string[], to: string[]) {
    const transition = {
      skipTransition: jest.fn(),
      finished: new Promise<void>((resolve) => (finish = resolve)),
    };
    return { transition, from: snap(from), to: snap(to) } as unknown as ViewTransitionInfo & {
      transition: { skipTransition: jest.Mock };
    };
  }

  afterEach(() => delete document.documentElement.dataset['motion']);

  it('names the kind on <html> until the transition ends', async () => {
    media({});
    const i = info(['antraege'], ['sitzungen']);
    onRouteViewTransition(i);
    expect(document.documentElement.dataset['motion']).toBe('section');
    finish();
    await Promise.resolve();
    await Promise.resolve();
    expect(document.documentElement.dataset['motion']).toBeUndefined();
  });

  it('keeps a newer kind that a later navigation set', async () => {
    media({ [PHONE]: true });
    onRouteViewTransition(info(['antraege'], ['antraege', '1']));
    const first = finish;
    onRouteViewTransition(info(['antraege', '1'], ['antraege']));
    first();
    await Promise.resolve();
    await Promise.resolve();
    expect(document.documentElement.dataset['motion']).toBe('pop');
  });

  it('treats a browser without matchMedia as a wide screen with full motion', () => {
    (window.matchMedia as unknown) = undefined;
    const i = info(['antraege'], ['antraege', '1']);
    onRouteViewTransition(i);
    expect(i.transition.skipTransition).toHaveBeenCalled();
  });

  it('skips a transition inside a section and with reduced motion', () => {
    media({});
    const same = info(['antraege'], ['antraege', '1']);
    onRouteViewTransition(same);
    expect(same.transition.skipTransition).toHaveBeenCalled();
    media({ [REDUCED]: true });
    const reduced = info(['antraege'], ['sitzungen']);
    onRouteViewTransition(reduced);
    expect(reduced.transition.skipTransition).toHaveBeenCalled();
    expect(document.documentElement.dataset['motion']).toBeUndefined();
  });

  it('skips the pop after a swipe back, once', () => {
    media({ [PHONE]: true });
    markGestureNavigation();
    const swiped = info(['antraege', '1'], ['antraege']);
    onRouteViewTransition(swiped);
    expect(swiped.transition.skipTransition).toHaveBeenCalled();
    const next = info(['antraege', '1'], ['antraege']);
    onRouteViewTransition(next);
    expect(next.transition.skipTransition).not.toHaveBeenCalled();
    expect(document.documentElement.dataset['motion']).toBe('pop');
  });
});

describe('withViewTransition', () => {
  const doc = document as Document & { startViewTransition?: unknown };
  afterEach(() => delete doc.startViewTransition);

  it('runs the change at once without the API or matchMedia', () => {
    (window.matchMedia as unknown) = undefined;
    const update = jest.fn();
    withViewTransition(update);
    expect(update).toHaveBeenCalled();
  });

  it('runs the change at once with reduced motion', () => {
    media({ [REDUCED]: true });
    doc.startViewTransition = jest.fn();
    const update = jest.fn();
    withViewTransition(update);
    expect(update).toHaveBeenCalled();
    expect(doc.startViewTransition).not.toHaveBeenCalled();
  });

  it('hands the change to the View Transitions API', () => {
    media({});
    const start = jest.fn();
    doc.startViewTransition = start;
    const update = jest.fn();
    withViewTransition(update);
    expect(start).toHaveBeenCalledWith(update);
    expect(update).not.toHaveBeenCalled();
  });
});
