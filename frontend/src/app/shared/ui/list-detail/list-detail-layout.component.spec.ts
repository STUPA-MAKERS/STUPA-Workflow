import { Component, signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { BREAKPOINTS } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import {
  LAYOUT_GUTTER,
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

@Component({
  standalone: true,
  imports: [ListDetailLayoutComponent],
  template: `
    <app-list-detail [detailOpen]="open() !== null" (back)="open.set(null)">
      <ul list aria-label="Anträge">
        @for (row of rows(); track row) {
          <li><button type="button" (click)="open.set(row)">{{ row }}</button></li>
        }
      </ul>
      <article detail aria-label="Detail">{{ open() }}</article>
    </app-list-detail>
  `,
})
class FocusHostComponent {
  readonly rows = signal(['Druckkosten', 'Lastenrad']);
  readonly open = signal<string | null>(null);
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

/** Fires the `change` event of the wide media query. */
let mediaChange: ((matches: boolean) => void) | null = null;

/**
 * A viewport of `width`. The measured content width is, by default, the rail shell
 * content box: the viewport minus the rail and the two page gutters. `content` gives
 * another content width (for example the current shell without a rail).
 */
function viewport(width: number, content = width - NAV_RAIL_WIDTH - 2 * LAYOUT_GUTTER) {
  const wide = width >= BREAKPOINTS.wideMin;
  jest.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches: wide,
        media: query,
        addEventListener: (_: string, cb: (e: MediaQueryListEvent) => void) => {
          mediaChange = (matches) => cb({ matches } as MediaQueryListEvent);
        },
        removeEventListener: () => {
          mediaChange = null;
        },
      }) as unknown as MediaQueryList,
  );
  jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    width: content,
  } as DOMRect);
}

describe('ListDetailLayoutComponent', () => {
  const original = globalThis.ResizeObserver;

  beforeEach(() => {
    globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
    resize = null;
    mediaChange = null;
    disconnects = 0;
  });
  afterEach(() => {
    globalThis.ResizeObserver = original;
    jest.restoreAllMocks();
  });

  const list = () => screen.getByRole('list', { hidden: true });
  const detail = () => screen.getByRole('article', { hidden: true });
  const host = (c: Element) => c.querySelector('app-list-detail') as HTMLElement;

  it('takes the content box of the first wide viewport as the split width', () => {
    expect(LIST_DETAIL_SPLIT_MIN).toBe(1200 - 96 - 2 * 24);
  });

  describe('at the wide breakpoint', () => {
    // [viewport, content width, split]: the rail shell (default content) and the current
    // shell without a rail (content = min(viewport, 1180) - 2 gutters).
    it.each([
      [1199, undefined, false],
      [1200, undefined, true],
      [1199, 1199 - 2 * LAYOUT_GUTTER, false],
      [1152, 1152 - 2 * LAYOUT_GUTTER, false],
      [1200, 1180 - 2 * LAYOUT_GUTTER, true],
    ])('at %ipx with content %p splits: %p', async (width, content, split) => {
      viewport(width, content);
      const view = await render(HostComponent);
      expect(host(view.container)).toHaveClass(split ? 'ld--split' : 'ld--collapsed');
    });
  });

  it('follows the viewport class when it changes', async () => {
    viewport(1440);
    const view = await render(HostComponent);
    expect(host(view.container)).toHaveClass('ld--split');
    mediaChange?.(false);
    view.fixture.detectChanges();
    expect(host(view.container)).toHaveClass('ld--collapsed');
    mediaChange?.(true);
    view.fixture.detectChanges();
    expect(host(view.container)).toHaveClass('ld--split');
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

  describe('focus in the one-view layout', () => {
    it('moves the focus to "Zur Liste" when a row opens, and back to the row', async () => {
      viewport(390);
      const view = await render(FocusHostComponent);
      const user = userEvent.setup();
      const row = screen.getByRole('button', { name: 'Lastenrad' });
      await user.click(row);
      await view.fixture.whenStable();
      const back = screen.getByRole('button', { name: 'Zur Liste' });
      expect(back).toHaveFocus();

      await user.click(back);
      await view.fixture.whenStable();
      expect(view.fixture.componentInstance.open()).toBeNull();
      expect(row).toHaveFocus();
    });

    it('opens from the keyboard and returns to the same row', async () => {
      viewport(960);
      const view = await render(FocusHostComponent);
      const user = userEvent.setup();
      const row = screen.getByRole('button', { name: 'Druckkosten' });
      row.focus();
      await user.keyboard('{Enter}');
      await view.fixture.whenStable();
      expect(screen.getByRole('button', { name: 'Zur Liste' })).toHaveFocus();
      await user.keyboard('{Enter}');
      await view.fixture.whenStable();
      expect(row).toHaveFocus();
    });

    it('focuses the list when the row that opened the detail is gone', async () => {
      viewport(390);
      const view = await render(FocusHostComponent);
      const user = userEvent.setup();
      await user.click(screen.getByRole('button', { name: 'Lastenrad' }));
      await view.fixture.whenStable();
      view.fixture.componentInstance.rows.set(['Druckkosten']);
      await user.click(screen.getByRole('button', { name: 'Zur Liste' }));
      await view.fixture.whenStable();
      expect(screen.queryByRole('button', { name: 'Lastenrad' })).toBeNull();
      expect(screen.getByRole('button', { name: 'Druckkosten' })).not.toHaveFocus();
      expect(view.container.querySelector('.ld__list')).toHaveFocus();
    });

    it('focuses the list on "Zur Liste" after a deep link to a row', async () => {
      viewport(390);
      const view = await render(FocusHostComponent, {
        detectChangesOnRender: false,
        autoDetectChanges: false,
      });
      view.fixture.componentInstance.open.set('Druckkosten');
      view.fixture.detectChanges();
      view.fixture.autoDetectChanges();
      await view.fixture.whenStable();
      await userEvent.setup().click(screen.getByRole('button', { name: 'Zur Liste' }));
      await view.fixture.whenStable();
      expect(view.container.querySelector('.ld__list')).toHaveFocus();
    });

    it('does not move the focus on the first render with an open row', async () => {
      viewport(390);
      const view = await render(FocusHostComponent, {
        detectChangesOnRender: false,
        autoDetectChanges: false,
      });
      view.fixture.componentInstance.open.set('Druckkosten');
      view.fixture.detectChanges();
      await view.fixture.whenStable();
      expect(screen.getByRole('button', { name: 'Zur Liste' })).not.toHaveFocus();
    });

    it('does not move the focus in the split layout', async () => {
      viewport(1440);
      const view = await render(FocusHostComponent);
      const row = screen.getByRole('button', { name: 'Lastenrad' });
      await userEvent.setup().click(row);
      await view.fixture.whenStable();
      expect(screen.queryByRole('button', { name: 'Zur Liste' })).toBeNull();
      expect(row).toHaveFocus();
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
    expect(mediaChange).toBeNull();
  });
});
