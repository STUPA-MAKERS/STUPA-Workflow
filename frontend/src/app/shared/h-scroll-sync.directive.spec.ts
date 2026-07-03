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
    /* no layout in jsdom */
  }
  disconnect(): void {
    /* noop */
  }
  unobserve(): void {
    /* noop */
  }
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
    // afterNextRender runs the DOM wiring once the view is rendered.
    TestBed.tick();
    const wrap = view.container.querySelector('.wrap') as HTMLElement;
    return { view, wrap };
  }

  it('inserts a synced proxy scrollbar as the wrapper sibling and observes it', async () => {
    const { wrap } = await setup();
    const bar = wrap.previousElementSibling as HTMLElement;
    expect(bar).not.toBeNull();
    expect(bar.getAttribute('aria-hidden')).toBe('true');
    // an inner spacer sizes the horizontal scroll area
    expect(bar.firstElementChild).not.toBeNull();
    // ResizeObserver was created (wrap + table observed)
    expect(ResizeObserverStub.last).not.toBeNull();
    // jsdom has no layout → the content does not overflow → the bar hides itself.
    expect(bar.style.display).toBe('none');
    // Simulate an overflowing wrapper; the observer callback re-runs update() and
    // shows the bar.
    Object.defineProperty(wrap, 'scrollWidth', { value: 500, configurable: true });
    Object.defineProperty(wrap, 'clientWidth', { value: 100, configurable: true });
    ResizeObserverStub.last?.cb();
    expect(bar.style.display).toBe('block');
  });

  it('skips observing a missing inner table (empty wrapper)', async () => {
    const view = await render(`<div class="empty" appHScrollSync></div>`, {
      imports: [HScrollSyncDirective],
    });
    TestBed.tick();
    const wrap = view.container.querySelector('.empty') as HTMLElement;
    // The proxy is still inserted even without a table child.
    expect(wrap.previousElementSibling?.getAttribute('aria-hidden')).toBe('true');
    expect(ResizeObserverStub.last).not.toBeNull();
  });

  it('mirrors scrollLeft from the wrapper to the proxy and back', async () => {
    const { wrap } = await setup();
    const bar = wrap.previousElementSibling as HTMLElement;

    // wrapper scrolled → proxy follows
    wrap.scrollLeft = 40;
    wrap.dispatchEvent(new Event('scroll'));
    expect(bar.scrollLeft).toBe(40);

    // proxy scrolled → wrapper follows
    bar.scrollLeft = 90;
    bar.dispatchEvent(new Event('scroll'));
    expect(wrap.scrollLeft).toBe(90);

    // equal values → the guard short-circuits (no ping-pong)
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
});
