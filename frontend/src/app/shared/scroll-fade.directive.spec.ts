import { Component } from '@angular/core';
import { render } from '@testing-library/angular';
import { ScrollFadeDirective } from './scroll-fade.directive';

/** Capture the ResizeObserver callback so a test can drive a measure. */
class ResizeObserverStub {
  static last: ResizeObserverStub | null = null;
  readonly cb: () => void;
  disconnected = false;
  constructor(cb: () => void) {
    this.cb = cb;
    ResizeObserverStub.last = this;
  }
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {
    this.disconnected = true;
  }
}

@Component({
  standalone: true,
  imports: [ScrollFadeDirective],
  template: `<div appScrollFade class="strip">content</div>`,
})
class Host {}

/** jsdom lays nothing out, so the geometry is stated directly. */
function geometry(el: HTMLElement, scrollWidth: number, clientWidth: number, scrollLeft = 0) {
  Object.defineProperty(el, 'scrollWidth', { value: scrollWidth, configurable: true });
  Object.defineProperty(el, 'clientWidth', { value: clientWidth, configurable: true });
  Object.defineProperty(el, 'scrollLeft', { value: scrollLeft, writable: true, configurable: true });
}

async function setup(scrollWidth: number, clientWidth: number, scrollLeft = 0) {
  Object.defineProperty(globalThis, 'ResizeObserver', {
    writable: true,
    value: ResizeObserverStub,
  });
  const view = await render(Host);
  const el = view.container.querySelector('.strip') as HTMLElement;
  geometry(el, scrollWidth, clientWidth, scrollLeft);
  ResizeObserverStub.last?.cb();
  return { el, view };
}

describe('ScrollFadeDirective', () => {
  it('fades neither end when the strip fits', async () => {
    // The old rule masked by viewport width, so a strip that fitted still lost the edge
    // of its first and last item to a gradient.
    const { el } = await setup(400, 400);
    expect(el.classList.contains('is-fade-start')).toBe(false);
    expect(el.classList.contains('is-fade-end')).toBe(false);
  });

  it('fades only the trailing end at the start of the scroll', async () => {
    const { el } = await setup(800, 400, 0);
    expect(el.classList.contains('is-fade-start')).toBe(false);
    expect(el.classList.contains('is-fade-end')).toBe(true);
  });

  it('fades only the leading end at the end of the scroll', async () => {
    const { el } = await setup(800, 400, 400);
    expect(el.classList.contains('is-fade-start')).toBe(true);
    expect(el.classList.contains('is-fade-end')).toBe(false);
  });

  it('fades both ends in the middle', async () => {
    const { el } = await setup(800, 400, 200);
    expect(el.classList.contains('is-fade-start')).toBe(true);
    expect(el.classList.contains('is-fade-end')).toBe(true);
  });

  it('re-measures on scroll', async () => {
    const { el } = await setup(800, 400, 0);
    expect(el.classList.contains('is-fade-start')).toBe(false);

    (el as unknown as { scrollLeft: number }).scrollLeft = 200;
    el.dispatchEvent(new Event('scroll'));
    expect(el.classList.contains('is-fade-start')).toBe(true);
  });

  it('treats a sub-pixel remainder as fitting', async () => {
    // A fractional layout leaves a fraction of a pixel over on a strip that visibly fits,
    // which would otherwise fade an end for no reason anyone can see.
    const { el } = await setup(400.4, 400);
    expect(el.classList.contains('is-fade-end')).toBe(false);
  });

  it('stops observing when the host goes away', async () => {
    const { view } = await setup(800, 400);
    view.fixture.destroy();
    expect(ResizeObserverStub.last?.disconnected).toBe(true);
  });
});
