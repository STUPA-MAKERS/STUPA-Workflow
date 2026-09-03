import { TestBed } from '@angular/core/testing';
import { render } from '@testing-library/angular';
import { HScrollSyncDirective } from './h-scroll-sync.directive';

/** Capture the ResizeObserver callback so the test can drive an update. */
class ResizeObserverStub {
  static last: ResizeObserverStub | null = null;
  readonly cb: () => void;
  constructor(cb: () => void) {
    this.cb = cb;
    ResizeObserverStub.last = this;
  }
  observe(): void {
    /* jsdom does no layout, so there is nothing to observe. */
  }
  disconnect(): void {
    /* Intentionally empty. */
  }
  unobserve(): void {
    /* Intentionally empty. */
  }
}

/**
 * Let the queued frame run.
 *
 * The observer schedules its write instead of doing it inline, so a test that drives the
 * callback has to wait one frame before reading the result.
 */
function frame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

describe('HScrollSyncDirective', () => {
  const realRO = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;

  beforeEach(() => {
    ResizeObserverStub.last = null;
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
  });
  afterEach(() => {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = realRO;
  });

  async function setup() {
    const view = await render(
      `<div class="wrap" appHScrollSync><table><tbody><tr><td>cell</td></tr></tbody></table></div>`,
      { imports: [HScrollSyncDirective] },
    );
    // afterNextRender builds the DOM only after the view renders.
    TestBed.tick();
    const wrap = view.container.querySelector('.wrap') as HTMLElement;
    return { view, wrap };
  }

  it('inserts a synced proxy scrollbar as the wrapper sibling and observes it', async () => {
    const { wrap } = await setup();
    const bar = wrap.previousElementSibling as HTMLElement;
    expect(bar).not.toBeNull();
    expect(bar.getAttribute('aria-hidden')).toBe('true');
    // An inner spacer sets the width of the horizontal scroll area.
    expect(bar.firstElementChild).not.toBeNull();
    expect(ResizeObserverStub.last).not.toBeNull();
    // jsdom has no layout. The content does not overflow, so the bar hides itself.
    expect(bar.style.display).toBe('none');
    // Simulate an overflowing wrapper. The observer callback runs the update again and
    // shows the bar.
    Object.defineProperty(wrap, 'scrollWidth', { value: 500, configurable: true });
    Object.defineProperty(wrap, 'clientWidth', { value: 100, configurable: true });
    ResizeObserverStub.last?.cb();
    await frame();
    expect(bar.style.display).toBe('block');
  });

  it('skips observing a missing inner table (empty wrapper)', async () => {
    const view = await render(`<div class="empty" appHScrollSync></div>`, {
      imports: [HScrollSyncDirective],
    });
    TestBed.tick();
    const wrap = view.container.querySelector('.empty') as HTMLElement;
    // The directive still inserts the proxy when the wrapper has no table child.
    expect(wrap.previousElementSibling?.getAttribute('aria-hidden')).toBe('true');
    expect(ResizeObserverStub.last).not.toBeNull();
  });

  it('mirrors scrollLeft from the wrapper to the proxy and back', async () => {
    const { wrap } = await setup();
    const bar = wrap.previousElementSibling as HTMLElement;

    wrap.scrollLeft = 40;
    wrap.dispatchEvent(new Event('scroll'));
    expect(bar.scrollLeft).toBe(40);

    bar.scrollLeft = 90;
    bar.dispatchEvent(new Event('scroll'));
    expect(wrap.scrollLeft).toBe(90);

    // Two equal values stop the guard, so no ping-pong starts.
    wrap.dispatchEvent(new Event('scroll'));
    expect(bar.scrollLeft).toBe(90);
  });

  it('removes the proxy and disconnects the observer on destroy', async () => {
    const { view, wrap } = await setup();
    const bar = wrap.previousElementSibling as HTMLElement;
    expect(bar).not.toBeNull();
    const disconnect = jest.spyOn(ResizeObserverStub.last!, 'disconnect');
    view.fixture.destroy();
    expect(disconnect).toHaveBeenCalled();
    expect(bar.isConnected).toBe(false);
  });

  it('gives the proxy the same scroll RANGE as the element it mirrors', async () => {
    // The two live in different boxes: a boxed table draws a border, so its scroller is a
    // couple of pixels narrower than the bar above it. Sizing the proxy to `scrollWidth`
    // gives the two different distances to travel, so their thumbs have different lengths
    // and drift apart as either one is dragged.
    const { wrap } = await setup();
    const bar = wrap.previousElementSibling as HTMLElement;
    const inner = bar.firstElementChild as HTMLElement;

    Object.defineProperty(wrap, 'scrollWidth', { value: 500, configurable: true });
    Object.defineProperty(wrap, 'clientWidth', { value: 98, configurable: true });
    Object.defineProperty(bar, 'clientWidth', { value: 100, configurable: true });
    ResizeObserverStub.last?.cb();
    await frame();

    // range = 500 - 98 = 402, so the proxy must be 100 + 402 wide to travel as far.
    expect(inner.style.width).toBe('502px');
  });

  it('writes nothing during the observer callback itself', async () => {
    // The observer watches `bar`, and the update writes to `bar` and to its child. A write
    // that lands inside the delivery starts another round, and the browser reports that as
    // "ResizeObserver loop completed with undelivered notifications" — a console error on
    // every page with a table. The write is deferred to the next frame instead.
    const { wrap } = await setup();
    const bar = wrap.previousElementSibling as HTMLElement;
    Object.defineProperty(wrap, 'scrollWidth', { value: 500, configurable: true });
    Object.defineProperty(wrap, 'clientWidth', { value: 100, configurable: true });

    ResizeObserverStub.last?.cb();
    expect(bar.style.display).toBe('none'); // untouched inside the callback

    await frame();
    expect(bar.style.display).toBe('block');
  });

  it('coalesces a burst of notifications into one frame', async () => {
    // Three observed elements report a change on one layout pass, which is the normal
    // case. One write, not three.
    const { wrap } = await setup();
    const bar = wrap.previousElementSibling as HTMLElement;
    const inner = bar.firstElementChild as HTMLElement;
    Object.defineProperty(wrap, 'scrollWidth', { value: 500, configurable: true });
    Object.defineProperty(wrap, 'clientWidth', { value: 100, configurable: true });
    const setWidth = jest.spyOn(inner.style, 'width', 'set');

    ResizeObserverStub.last?.cb();
    ResizeObserverStub.last?.cb();
    ResizeObserverStub.last?.cb();
    await frame();

    expect(setWidth).toHaveBeenCalledTimes(1);
  });

  it('writes nothing when the measurement has not changed', async () => {
    // A steady state must not keep assigning the same value: each assignment is a write to
    // an observed element and re-arms the observer.
    const { wrap } = await setup();
    const bar = wrap.previousElementSibling as HTMLElement;
    const inner = bar.firstElementChild as HTMLElement;
    Object.defineProperty(wrap, 'scrollWidth', { value: 500, configurable: true });
    Object.defineProperty(wrap, 'clientWidth', { value: 100, configurable: true });
    ResizeObserverStub.last?.cb();
    await frame();

    const setWidth = jest.spyOn(inner.style, 'width', 'set');
    const setDisplay = jest.spyOn(bar.style, 'display', 'set');
    ResizeObserverStub.last?.cb();
    await frame();

    expect(setWidth).not.toHaveBeenCalled();
    expect(setDisplay).not.toHaveBeenCalled();
  });

  it('cancels a pending frame when the host goes away', async () => {
    // A queued write would run against a proxy that has already been removed.
    const { view, wrap } = await setup();
    Object.defineProperty(wrap, 'scrollWidth', { value: 500, configurable: true });
    Object.defineProperty(wrap, 'clientWidth', { value: 100, configurable: true });
    const cancel = jest.spyOn(globalThis, 'cancelAnimationFrame');

    ResizeObserverStub.last?.cb(); // queued, not yet run
    view.fixture.destroy();

    expect(cancel).toHaveBeenCalled();
    cancel.mockRestore();
  });

  it('mirrors nothing when the inner selector matches no element', async () => {
    // Falling back to the host would mirror something with no scroll range at all, and
    // the two bars would disagree about how far there is to go.
    const view = await render(`<div class="wrap" appHScrollSync=".missing"></div>`, {
      imports: [HScrollSyncDirective],
    });
    TestBed.tick();
    const wrap = view.container.querySelector('.wrap') as HTMLElement;
    expect(wrap.previousElementSibling).toBeNull();
  });
});
