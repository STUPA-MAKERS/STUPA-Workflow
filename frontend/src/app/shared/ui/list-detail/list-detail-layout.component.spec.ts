import { Component, signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { BREAKPOINTS } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import {
  LIST_DETAIL_SPLIT_MIN,
  ListDetailLayoutComponent,
  NAV_RAIL_WIDTH,
} from './list-detail-layout.component';

@Component({
  standalone: true,
  imports: [ListDetailLayoutComponent],
  template: `
    <app-list-detail [detailOpen]="open()" (back)="open.set(false)">
      <ul list aria-label="Anträge"><li>Druckkosten</li></ul>
      <article detail aria-label="Detail">Antrag Druckkosten</article>
    </app-list-detail>
  `,
})
class HostComponent {
  readonly open = signal(false);
}

/** Drives the ResizeObserver of the layout: the last observer created gets the width. */
let resize: ((width: number) => void) | null = null;
let disconnects = 0;

class ResizeObserverStub {
  constructor(private readonly cb: ResizeObserverCallback) {
    resize = (width) =>
      this.cb(
        [{ contentRect: { width } } as ResizeObserverEntry],
        this as unknown as ResizeObserver,
      );
  }
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {
    disconnects++;
  }
}

/** A viewport of `width`: the media query and the measured content width beside the rail. */
function viewport(width: number) {
  const wide = width >= BREAKPOINTS.wideMin;
  jest.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches: wide,
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }) as unknown as MediaQueryList,
  );
  jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    width: width - NAV_RAIL_WIDTH,
  } as DOMRect);
}

describe('ListDetailLayoutComponent', () => {
  const original = globalThis.ResizeObserver;

  beforeEach(() => {
    globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
    resize = null;
    disconnects = 0;
  });
  afterEach(() => {
    globalThis.ResizeObserver = original;
    jest.restoreAllMocks();
  });

  const list = () => screen.getByRole('list', { hidden: true });
  const detail = () => screen.getByRole('article', { hidden: true });
  const host = (c: Element) => c.querySelector('app-list-detail') as HTMLElement;

  it('splits at the first wide viewport and not below it', () => {
    expect(LIST_DETAIL_SPLIT_MIN).toBe(1104);
  });

  describe('at 1440px', () => {
    it('shows the list and the detail side by side, without a back control', async () => {
      viewport(1440);
      const view = await render(HostComponent);
      expect(host(view.container)).toHaveClass('ld--split');
      expect(list()).toBeVisible();
      expect(detail()).toBeVisible();
      expect(screen.queryByRole('button', { name: 'Zur Liste' })).toBeNull();
      view.fixture.componentInstance.open.set(true);
      view.fixture.detectChanges();
      expect(list()).toBeVisible();
      expect(detail()).toBeVisible();
      expect(await runAxe(view.container)).toHaveNoViolations();
    });
  });

  describe('at 960px', () => {
    it('shows the list alone until a row opens', async () => {
      viewport(960);
      const view = await render(HostComponent);
      expect(host(view.container)).toHaveClass('ld--collapsed');
      expect(list()).toBeVisible();
      expect(detail()).not.toBeVisible();
    });

    it('then shows the detail alone with "Zur Liste", which goes back', async () => {
      viewport(960);
      const view = await render(HostComponent);
      view.fixture.componentInstance.open.set(true);
      view.fixture.detectChanges();
      expect(list()).not.toBeVisible();
      expect(detail()).toBeVisible();
      await userEvent.setup().click(screen.getByRole('button', { name: 'Zur Liste' }));
      expect(view.fixture.componentInstance.open()).toBe(false);
      expect(list()).toBeVisible();
      expect(detail()).not.toBeVisible();
      expect(await runAxe(view.container)).toHaveNoViolations();
    });
  });

  it('follows its own width when the content area changes', async () => {
    viewport(1440);
    const view = await render(HostComponent);
    view.fixture.componentInstance.open.set(true);
    view.fixture.detectChanges();
    expect(host(view.container)).toHaveClass('ld--split');

    // The same viewport, but a pane beside the layout takes room: the content is narrow.
    resize?.(900);
    view.fixture.detectChanges();
    expect(host(view.container)).toHaveClass('ld--collapsed');
    expect(list()).not.toBeVisible();

    resize?.(LIST_DETAIL_SPLIT_MIN);
    view.fixture.detectChanges();
    expect(host(view.container)).toHaveClass('ld--split');
  });

  it('keeps the media query guess while it has no width', async () => {
    viewport(1440);
    jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 0,
    } as DOMRect);
    const view = await render(HostComponent);
    expect(host(view.container)).toHaveClass('ld--split');
    resize?.(0);
    view.fixture.detectChanges();
    expect(host(view.container)).toHaveClass('ld--split');
  });

  it('takes another split width', async () => {
    viewport(1440);
    const view = await render(ListDetailLayoutComponent, { inputs: { splitMin: 2000 } });
    view.fixture.detectChanges();
    expect(view.fixture.nativeElement).toHaveClass('ld--collapsed');
  });

  it('stops observing when it is destroyed', async () => {
    viewport(1440);
    const view = await render(HostComponent);
    view.fixture.destroy();
    expect(disconnects).toBe(1);
  });
});
