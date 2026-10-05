import { Component, signal } from '@angular/core';
import { render } from '@testing-library/angular';
import { StickyBarComponent } from './sticky-bar.component';

@Component({
  standalone: true,
  imports: [StickyBarComponent],
  template: `<app-sticky-bar [sticky]="sticky()"><input aria-label="Suche" /></app-sticky-bar>`,
})
class Host {
  readonly sticky = signal(true);
}

/** jsdom lays nothing out, so the box of the bar is stated directly. */
function place(el: HTMLElement, top: number, height = 60): void {
  el.getBoundingClientRect = () =>
    ({ top, height, bottom: top + height, left: 0, right: 0, width: 0, x: 0, y: top }) as DOMRect;
}

function scrollTo(y: number): void {
  Object.defineProperty(window, 'scrollY', { value: y, configurable: true });
}

/** Run the measure that a scroll schedules for the next frame. */
async function flushFrame(): Promise<void> {
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  await new Promise<void>((resolve) => setTimeout(resolve));
}

async function setup() {
  const view = await render(Host);
  const bar = view.container.querySelector('app-sticky-bar') as HTMLElement;
  return { view, bar };
}

describe('StickyBarComponent', () => {
  afterEach(() => {
    scrollTo(0);
    document.documentElement.style.removeProperty('scroll-padding-top');
  });

  it('projects its content', async () => {
    const { bar } = await setup();
    expect(bar.querySelector('input')).not.toBeNull();
  });

  it('is not stuck while the page is at the top', async () => {
    const { bar } = await setup();
    place(bar, 120);
    scrollTo(0);
    window.dispatchEvent(new Event('scroll'));
    await flushFrame();
    expect(bar.classList.contains('stb--stuck')).toBe(false);
  });

  it('is stuck when the page scrolled and the bar sits at its offset', async () => {
    const { bar, view } = await setup();
    place(bar, 0);
    scrollTo(400);
    window.dispatchEvent(new Event('scroll'));
    await flushFrame();
    view.fixture.detectChanges();
    expect(bar.classList.contains('stb--stuck')).toBe(true);

    // Back at the top: the bar is at its place in the flow again.
    place(bar, 120);
    scrollTo(0);
    window.dispatchEvent(new Event('scroll'));
    await flushFrame();
    view.fixture.detectChanges();
    expect(bar.classList.contains('stb--stuck')).toBe(false);
  });

  it('keeps the focus scroll clear of the bar and removes the padding when it goes', async () => {
    const { bar, view } = await setup();
    place(bar, 0, 64);
    window.dispatchEvent(new Event('resize'));
    await flushFrame();
    expect(document.documentElement.style.getPropertyValue('scroll-padding-top')).toBe('64px');

    view.fixture.destroy();
    expect(document.documentElement.style.getPropertyValue('scroll-padding-top')).toBe('');
  });

  it('turned off, it never sticks and sets no padding', async () => {
    const { bar, view } = await setup();
    view.fixture.componentInstance.sticky.set(false);
    view.fixture.detectChanges();
    place(bar, 0);
    scrollTo(400);
    window.dispatchEvent(new Event('scroll'));
    await flushFrame();
    view.fixture.detectChanges();
    expect(bar.classList.contains('stb--off')).toBe(true);
    expect(bar.classList.contains('stb--stuck')).toBe(false);
    expect(document.documentElement.style.getPropertyValue('scroll-padding-top')).toBe('');
  });

  it('an off bar does not remove the padding that another bar set', async () => {
    const { bar, view } = await setup();
    place(bar, 0, 64);
    window.dispatchEvent(new Event('resize'));
    await flushFrame();
    // Another bar on the page owns the padding now.
    document.documentElement.style.setProperty('scroll-padding-top', '80px');
    view.fixture.componentInstance.sticky.set(false);
    view.fixture.detectChanges();
    await flushFrame();
    // This bar set a padding before, so it removes it once; a second off measure must not.
    document.documentElement.style.setProperty('scroll-padding-top', '80px');
    window.dispatchEvent(new Event('scroll'));
    await flushFrame();
    expect(document.documentElement.style.getPropertyValue('scroll-padding-top')).toBe('80px');
  });
});
