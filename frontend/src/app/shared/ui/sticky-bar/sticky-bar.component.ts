import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';

/**
 * A bar that never scrolls away: the search field of a list page and its filter chips.
 *
 * The bar is `position: sticky` at the top of the viewport, below the shell header and
 * the safe area (`--layout-header-height`, `env(safe-area-inset-top)`). It has the page
 * background, so the rows that scroll under it do not show through. While rows are under
 * it (the bar is "stuck"), a short fade below the bar shows that the list continues.
 *
 * Put the bar as a direct child of the element that holds the list, not into a small
 * wrapper: a sticky element stays inside its parent, so a parent as high as the bar holds
 * it in place and it scrolls away.
 *
 * In a list/detail column that scrolls by itself, the bar is not needed: the column keeps
 * the search above its scrolling list. The bar does no harm there, it never sticks.
 *
 * Scroll container: the bar sticks in the nearest ancestor that scrolls (`overflow-y`
 * auto or scroll), else in the window. In the admin sheet, whose body scrolls inside its
 * round corners, the bar so sticks to the top of the body and reads the body scroll.
 *
 * Keyboard focus: while the bar exists, its scroll container (the document, or the
 * scrolling ancestor) gets a `scroll-padding-top` of the height of the bar. A row that
 * gets the focus by Tab then scrolls to a position below the bar, not under it.
 *
 * `sticky` set to false turns the bar off (`display: contents`): the content stays in the
 * flow as if the bar were not there. A page so keeps one template for a header that sticks
 * only on some widths.
 *
 * Layers: the bar sits below the floating action button, the phone bottom bar, menus and
 * dialogs. While a control in the bar has an open popup (`aria-expanded="true"`, for
 * example the filter panel of the kit, which is a bottom sheet on a phone), the bar goes
 * up to the dialog layer, so that the popup is not under the bottom bar.
 */
@Component({
  selector: 'app-sticky-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '[class.stb--stuck]': 'sticky() && stuck()',
    '[class.stb--off]': '!sticky()',
  },
  template: '<ng-content />',
  styleUrl: './sticky-bar.component.scss',
})
export class StickyBarComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** False turns the bar off: no sticky position, no background, no fade. */
  readonly sticky = input(true);

  /** Rows scroll under the bar: it is at its sticky offset, above its place in the flow. */
  protected readonly stuck = signal(false);
  /** This bar set the scroll padding of its scroll container, so it removes it again. */
  private ownsPadding: HTMLElement | null = null;
  /** The scrolling ancestor, or null for the window (see {@link scrollParent}). */
  private scroller: HTMLElement | null = null;

  constructor() {
    let frame = 0;
    const schedule = (): void => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        this.measure();
      });
    };
    let observer: ResizeObserver | null = null;

    afterNextRender(() => {
      this.scroller = scrollParent(this.host.nativeElement);
      this.scroller?.addEventListener('scroll', schedule, { passive: true });
      window.addEventListener('scroll', schedule, { passive: true });
      window.addEventListener('resize', schedule, { passive: true });
      observer = new ResizeObserver(schedule);
      observer.observe(this.host.nativeElement);
      this.measure();
    });
    // A bar that turns on or off changes the room that the focus scroll must keep clear.
    effect(() => {
      this.sticky();
      schedule();
    });

    inject(DestroyRef).onDestroy(() => {
      if (frame) cancelAnimationFrame(frame);
      this.scroller?.removeEventListener('scroll', schedule);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      observer?.disconnect();
      this.setPadding(null);
    });
  }

  /** Read the position of the bar; set the stuck state and the scroll padding. */
  protected measure(): void {
    const el = this.host.nativeElement;
    if (!this.sticky()) {
      this.stuck.set(false);
      this.setPadding(null);
      return;
    }
    const rect = el.getBoundingClientRect();
    const top = parseFloat(getComputedStyle(el).top) || 0;
    // A sub-pixel layout leaves a fraction of a pixel between the bar and its offset.
    const slack = 1;
    const scroller = this.scroller;
    const scrolled = scroller ? scroller.scrollTop > 0 : window.scrollY > 0;
    const edge = scroller ? scroller.getBoundingClientRect().top + scroller.clientTop : 0;
    this.stuck.set(scrolled && rect.height > 0 && rect.top <= edge + top + slack);
    // A hidden bar (height 0) keeps nothing clear.
    this.setPadding(rect.height > 0 ? Math.ceil(top + rect.height) : null);
  }

  /**
   * Set the scroll padding of the scroll container (the document, or the scrolling
   * ancestor), or remove it (`null`) if this bar set it.
   */
  private setPadding(px: number | null): void {
    const target = this.scroller ?? document.documentElement;
    if (px !== null) {
      target.style.setProperty('scroll-padding-top', `${px}px`);
      this.ownsPadding = target;
    } else if (this.ownsPadding) {
      this.ownsPadding.style.removeProperty('scroll-padding-top');
      this.ownsPadding = null;
    }
  }
}

/** The nearest ancestor that scrolls vertically, or null when the window scrolls. */
export function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const y = getComputedStyle(p).overflowY;
    if (y === 'auto' || y === 'scroll') return p;
  }
  return null;
}
