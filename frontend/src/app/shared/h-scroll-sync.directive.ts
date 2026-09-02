import {
  Directive,
  ElementRef,
  type OnDestroy,
  afterNextRender,
  inject,
  input,
} from '@angular/core';

/**
 * Mirror a second horizontal scrollbar above an overflowing container. The container is
 * normally a wide table in `.exp__tableWrap`. The user reaches the right columns without a
 * scroll down to the bottom edge (#expenses-ux).
 *
 * The directive works on the DOM only. The template needs no change except the attribute
 * on the wrapper. The proxy goes in as a sibling directly before the wrapper. Its `scrollLeft`
 * stays in sync with the wrapper in both directions. The bar shows only when the content
 * really overflows, which is the desktop case. On mobile the cards reflow without an
 * overflow, and the bar hides itself.
 *
 * When the overflow lives inside a component rather than on the host — `app-data-table`
 * scrolls in its own `.dt__scroll` — pass that selector as `appHScrollSync`. The
 * directive then mirrors the inner element. Naming the selector at the call site keeps
 * the dependency on the component's internals visible in the template that takes it on,
 * instead of hiding it in here.
 */
@Directive({ selector: '[appHScrollSync]', standalone: true })
export class HScrollSyncDirective implements OnDestroy {
  /** CSS selector of the scrolling element inside the host. Empty means the host. */
  readonly appHScrollSync = input('');

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private bar: HTMLDivElement | null = null;
  private ro: ResizeObserver | null = null;
  private readonly disposers: Array<() => void> = [];

  constructor() {
    // Browser only, never SSR: build the DOM after the view renders.
    afterNextRender(() => this.setup());
  }

  private setup(): void {
    const sel = this.appHScrollSync();
    // A selector that matches nothing must NOT fall back to the host. The host is not the
    // thing that scrolls, so the proxy would mirror an element with no scroll range and
    // the two bars would disagree about how far there is to go.
    const wrap = sel
      ? this.host.nativeElement.querySelector<HTMLElement>(sel)
      : this.host.nativeElement;
    // The bar sits above whatever actually scrolls, which for an inner scroller means
    // above the component, not inside it.
    const parent = this.host.nativeElement.parentElement;
    if (typeof document === 'undefined' || !parent || !wrap) return;

    const bar = document.createElement('div');
    bar.setAttribute('aria-hidden', 'true');
    bar.style.cssText = 'overflow-x:auto;overflow-y:hidden;';
    const inner = document.createElement('div');
    inner.style.height = '1px';
    bar.appendChild(inner);
    parent.insertBefore(bar, this.host.nativeElement);
    this.bar = bar;

    // Mirror scrollLeft in both directions. The equality check prevents a ping-pong. The
    // mirrored scroll event finds two equal values and writes nothing.
    const mirror = (from: HTMLElement, to: HTMLElement): void => {
      if (to.scrollLeft !== from.scrollLeft) to.scrollLeft = from.scrollLeft;
    };
    const onWrap = (): void => mirror(wrap, bar);
    const onBar = (): void => mirror(bar, wrap);
    wrap.addEventListener('scroll', onWrap, { passive: true });
    bar.addEventListener('scroll', onBar, { passive: true });
    this.disposers.push(() => wrap.removeEventListener('scroll', onWrap));
    this.disposers.push(() => bar.removeEventListener('scroll', onBar));

    const update = (): void => {
      const range = wrap.scrollWidth - wrap.clientWidth;
      // Match the RANGE, not the width. The proxy and the real scroller sit in different
      // boxes — the boxed table draws a border, so its scroller is a couple of pixels
      // narrower than the bar above it — and sizing the proxy to `scrollWidth` gave the
      // two different distances to travel. The thumbs then had different lengths and
      // drifted apart as you dragged either one. Deriving the inner width from the bar's
      // own width plus the range makes both ranges identical whatever the boxes do.
      inner.style.width = `${bar.clientWidth + Math.max(0, range)}px`;
      // No overflow, for example after a mobile card reflow: hide the bar.
      bar.style.display = range > 1 ? 'block' : 'none';
    };
    update();
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(() => update());
      ro.observe(wrap);
      // The bar's own width feeds the calculation, so a change to it has to re-run too.
      ro.observe(bar);
      const table = wrap.firstElementChild;
      if (table) ro.observe(table);
      this.ro = ro;
    }
  }

  ngOnDestroy(): void {
    this.ro?.disconnect();
    for (const dispose of this.disposers) dispose();
    this.bar?.remove();
  }
}
