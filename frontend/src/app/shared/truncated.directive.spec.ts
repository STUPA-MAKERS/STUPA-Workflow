import { Component, signal } from '@angular/core';
import { render } from '@testing-library/angular';
import { TruncatedDirective } from './truncated.directive';

@Component({
  standalone: true,
  imports: [TruncatedDirective],
  template: `<span class="ell" [appTruncated]="text()" #t="appTruncated">{{ text() }}</span
    ><output>{{ t.truncated() }}</output>`,
})
class HostComponent {
  readonly text = signal('kurz');
}

describe('TruncatedDirective', () => {
  let width = 0;
  let scrollSpy: jest.SpyInstance;
  let clientSpy: jest.SpyInstance;

  beforeEach(() => {
    width = 0;
    scrollSpy = jest
      .spyOn(HTMLElement.prototype, 'scrollWidth', 'get')
      .mockImplementation(() => width);
    clientSpy = jest
      .spyOn(HTMLElement.prototype, 'clientWidth', 'get')
      .mockImplementation(() => 100);
  });
  afterEach(() => {
    scrollSpy.mockRestore();
    clientSpy.mockRestore();
  });

  it('reports a text wider than its box and measures again on a new text', async () => {
    width = 100;
    const { fixture, container } = await render(HostComponent);
    const out = (): string | undefined => container.querySelector('output')?.textContent?.trim();
    expect(out()).toBe('false');
    width = 300;
    fixture.componentInstance.text.set('ein sehr langer Text');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(out()).toBe('true');
  });

  it('measures again when the box changes its size', async () => {
    let notify: (() => void) | null = null;
    const disconnect = jest.fn();
    const original = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      constructor(cb: () => void) {
        notify = cb;
      }
      observe(): void {}
      disconnect = disconnect;
    };
    try {
      width = 100;
      const { fixture, container } = await render(HostComponent);
      expect(container.querySelector('output')?.textContent?.trim()).toBe('false');
      width = 250;
      notify?.();
      fixture.detectChanges();
      expect(container.querySelector('output')?.textContent?.trim()).toBe('true');
      fixture.destroy();
      expect(disconnect).toHaveBeenCalled();
    } finally {
      (globalThis as { ResizeObserver?: unknown }).ResizeObserver = original;
    }
  });

  it('ignores one pixel of rounding', async () => {
    width = 101;
    const { container } = await render(HostComponent);
    expect(container.querySelector('output')?.textContent?.trim()).toBe('false');
  });
});
