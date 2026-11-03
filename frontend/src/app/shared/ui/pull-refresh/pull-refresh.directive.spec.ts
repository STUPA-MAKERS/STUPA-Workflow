import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, inject, signal } from '@angular/core';
import { render } from '@testing-library/angular';
import { cacheInterceptor, listContext } from '@core/cache/cache.interceptor';
import { HttpCacheService } from '@core/cache/http-cache.service';
import { loadingInterceptor, MEDIA } from '@stupa-makers/ui-kit';
import { drag, mediaMatching, touch } from '../../../../testing/touch';
import { PULL_HOLD, PULL_THRESHOLD, PullRefreshDirective, rubberBand } from './pull-refresh.directive';
import { RING_LENGTH } from './pull-refresh-ring.component';

@Component({
  standalone: true,
  imports: [PullRefreshDirective],
  template: `
    <section class="pane">
      <header>Anträge</header>
      <div class="rows" appPullRefresh [pullRefreshBusy]="busy()" (appPullRefresh)="reload()">rows</div>
    </section>
  `,
})
class HostComponent {
  private readonly http = inject(HttpClient);
  readonly busy = signal(false);
  reloads = 0;
  answer: unknown = null;
  reload(): void {
    this.reloads++;
    this.http.get('/api/applications', { context: listContext(0) }).subscribe((a) => (this.answer = a));
  }
}

const PHONE = [MEDIA.phone, MEDIA.coarse];

async function setup(media: readonly string[] = PHONE) {
  mediaMatching(media);
  const view = await render(HostComponent, {
    providers: [
      provideHttpClient(withInterceptors([loadingInterceptor, cacheInterceptor])),
      provideHttpClientTesting(),
    ],
  });
  const rows = view.container.querySelector('.rows') as HTMLElement;
  const ring = () => view.container.querySelector('app-pull-refresh-ring') as HTMLElement | null;
  const arc = () => ring()?.querySelector('.ptr__arc') as SVGCircleElement;
  return {
    view,
    rows,
    ring,
    arc,
    host: view.fixture.componentInstance,
    http: view.fixture.debugElement.injector.get(HttpTestingController),
    cache: view.fixture.debugElement.injector.get(HttpCacheService),
  };
}

/** The finger distance that pulls the rows `pull` px (the inverse of the rubber band). */
const fingerFor = (pull: number) => -1.6 * PULL_THRESHOLD * Math.log(1 - pull / (1.76 * PULL_THRESHOLD));

describe('rubberBand', () => {
  it('gives nothing for no move, resists more and more, and caps at 1.76 × the threshold', () => {
    expect(rubberBand(0)).toBe(0);
    expect(rubberBand(-20)).toBe(0);
    expect(rubberBand(64)).toBeCloseTo(1.76 * 64 * (1 - Math.exp(-1 / 1.6)), 6);
    expect(rubberBand(10_000)).toBeCloseTo(1.76 * 64, 3);
    expect(rubberBand(fingerFor(PULL_THRESHOLD))).toBeCloseTo(PULL_THRESHOLD, 6);
  });
});

describe('PullRefreshDirective', () => {
  let vibrate: jest.Mock;
  beforeEach(() => {
    jest.useFakeTimers();
    vibrate = jest.fn();
    Object.defineProperty(navigator, 'vibrate', { value: vibrate, configurable: true });
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
  });
  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
    delete (navigator as { vibrate?: unknown }).vibrate;
  });

  it('pulls the rows down with the rubber band and fills the ring with the pull', async () => {
    const { rows, ring, arc } = await setup();
    const moves = drag(rows, { x: 100, y: 200 }, [{ x: 101, y: 205 }, { x: 102, y: 260 }], { release: false });
    expect(moves.every((m) => m.defaultPrevented)).toBe(true);
    const pull = rubberBand(60);
    expect(rows.style.transform).toBe(`translateY(${pull}px)`);
    expect(rows.style.transition).toBe('none');
    expect(ring()?.style.transform).toBe(`translateY(${pull / 2 - 14}px)`);
    expect(ring()?.style.opacity).toBe('1');
    expect(Number(arc().style.strokeDashoffset)).toBeCloseTo(RING_LENGTH * (1 - (pull / PULL_THRESHOLD) * 0.8), 3);
  });

  /** The cached page is not served, so the answer waits for the network. */
  it('reloads past the threshold: holds the rows, turns the ring, skips the cache, then springs back', async () => {
    const { rows, ring, host, http, cache } = await setup();
    cache.set('/api/applications', { items: ['old'] });
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 100 + fingerFor(70) }]);
    expect(vibrate).toHaveBeenCalledTimes(1);
    expect(host.reloads).toBe(1);
    expect(rows.style.transform).toBe(`translateY(${PULL_HOLD}px)`);
    expect(rows.style.transition).toContain('280ms');
    expect(ring()).toHaveClass('ptr--spin');
    expect(host.answer).toBeNull();
    jest.advanceTimersByTime(1000);
    expect(rows.style.transform).toBe(`translateY(${PULL_HOLD}px)`);
    http.expectOne('/api/applications').flush({ items: ['new'] });
    expect(host.answer).toEqual({ items: ['new'] });
    jest.advanceTimersByTime(100);
    expect(ring()).not.toHaveClass('ptr--spin');
    expect(rows.style.transform).toBe('');
    jest.advanceTimersByTime(280);
    expect(rows.style.transition).toBe('');
  });

  it('keeps the ring for at least 600 ms and waits for the busy flag of the page', async () => {
    const { rows, host, http, view } = await setup();
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 300 }]);
    http.expectOne('/api/applications').flush({ items: [] });
    host.busy.set(true);
    view.fixture.detectChanges();
    jest.advanceTimersByTime(600);
    expect(rows.style.transform).toBe(`translateY(${PULL_HOLD}px)`);
    host.busy.set(false);
    view.fixture.detectChanges();
    jest.advanceTimersByTime(100);
    expect(rows.style.transform).toBe('');
  });

  it('gives up after 15 s', async () => {
    const { rows, http } = await setup();
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 300 }]);
    jest.advanceTimersByTime(15_000);
    expect(rows.style.transform).toBe('');
    http.expectOne('/api/applications').flush({});
  });

  it('springs back without a reload below the threshold, and on a cancel', async () => {
    const { rows, host } = await setup();
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 150 }]);
    expect(rows.style.transform).toBe('');
    jest.advanceTimersByTime(280);
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 300 }], { release: false });
    touch(rows, 'touchcancel', []);
    jest.advanceTimersByTime(280);
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 300 }], { release: false });
    touch(rows, 'touchmove', [{ x: 1, y: 300 }, { x: 2, y: 300 }]);
    jest.advanceTimersByTime(280);
    expect(host.reloads).toBe(0);
    expect(vibrate).toHaveBeenCalledTimes(2);
  });

  it('leaves a scroll up and a sideways move alone', async () => {
    const { rows, host } = await setup();
    const up = drag(rows, { x: 100, y: 300 }, [{ x: 100, y: 296 }, { x: 100, y: 200 }]);
    expect(up.some((m) => m.defaultPrevented)).toBe(false);
    drag(rows, { x: 100, y: 300 }, [{ x: 130, y: 302 }, { x: 200, y: 400 }]);
    expect(rows.style.transform).toBe('');
    expect(host.reloads).toBe(0);
  });

  it('does nothing away from the top, while busy, during a reload or under a modal', async () => {
    const { rows, host, view, http } = await setup();
    Object.defineProperty(window, 'scrollY', { value: 40, configurable: true });
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 300 }]);
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
    host.busy.set(true);
    view.fixture.detectChanges();
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 300 }]);
    host.busy.set(false);
    view.fixture.detectChanges();
    const modal = document.createElement('div');
    modal.setAttribute('aria-modal', 'true');
    document.body.appendChild(modal);
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 300 }]);
    modal.remove();
    touch(rows, 'touchstart', [{ x: 1, y: 1 }, { x: 2, y: 2 }]);
    touch(rows, 'touchmove', [{ x: 1, y: 300 }]);
    expect(host.reloads).toBe(0);
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 300 }]);
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 300 }]);
    expect(host.reloads).toBe(1);
    http.expectOne('/api/applications').flush({});
  });

  it.each([
    ['a desktop', [] as string[]],
    ['a phone width with a mouse', [MEDIA.phone]],
  ])('does nothing on %s', async (_, media) => {
    const { rows, host, ring } = await setup(media);
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 300 }]);
    expect(host.reloads).toBe(0);
    expect(ring()).toBeNull();
  });

  it('settles at once with reduced motion and keeps the ring still', async () => {
    const { rows, http } = await setup([...PHONE, MEDIA.reducedMotion]);
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 300 }]);
    expect(rows.style.transition).toBe('none');
    http.expectOne('/api/applications').flush({});
    jest.advanceTimersByTime(600);
    expect(rows.style.transform).toBe('');
    expect(rows.style.transition).toBe('');
  });

  it('removes its listeners and the ring when it is destroyed', async () => {
    const { rows, view } = await setup();
    drag(rows, { x: 100, y: 100 }, [{ x: 100, y: 120 }, { x: 100, y: 150 }]);
    const spy = jest.spyOn(rows, 'removeEventListener');
    view.fixture.destroy();
    expect(spy.mock.calls.map(([t]) => t)).toEqual(
      expect.arrayContaining(['touchstart', 'touchmove', 'touchend', 'touchcancel']),
    );
  });
});
