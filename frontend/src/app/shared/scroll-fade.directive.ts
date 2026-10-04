import {
  DestroyRef,
  Directive,
  ElementRef,
  afterNextRender,
  inject,
  input,
} from '@angular/core';

/** The scroll direction: `x` for a strip, `y` for a list. */
export type ScrollFadeAxis = 'x' | 'y';

/**
 * Fade the ends of a scrolling strip or list, but only where content is hidden.
 *
 * A hidden scrollbar leaves a hard cut as the only cue that a strip scrolls at all, and a
 * half-sliced label reads as a rendering fault rather than "there is more".
 *
 * A pure-CSS mask cannot do this. Two static gradients fade both ends always, whatever
 * the scroll position, and a width media query cannot know whether a strip overflows —
 * that depends on how much room its siblings took, not on the viewport. So the state is
 * measured and written back as two classes:
 *
 * * `is-fade-start` — content is hidden to the left (`x`) or above (`y`)
 * * `is-fade-end` — content is hidden to the right (`x`) or below (`y`)
 *
 * A strip that fits carries neither and is not masked at all, so its first and last item
 * stay sharp.
 *
 * The axis is the value of the attribute: `appScrollFade` or `appScrollFade="x"` for a
 * horizontal strip, `appScrollFade="y"` for a vertical list. The page styles the mask.
 */
@Directive({
  selector: '[appScrollFade]',
  standalone: true,
  host: { '(scroll)': 'measure()' },
})
export class ScrollFadeDirective {
  private readonly el = inject<ElementRef<HTMLElement>>(ElementRef);

  /** The scroll direction. An empty attribute means `x`. */
  readonly axis = input<ScrollFadeAxis, ScrollFadeAxis | '' | null | undefined>('x', {
    alias: 'appScrollFade',
    transform: (v) => (v === 'y' ? 'y' : 'x'),
  });

  constructor() {
    const host = this.el.nativeElement;
    // A resize changes what fits, and so does a nav item appearing after a permission
    // loads. Observing the element covers both without a window listener.
    const observer = new ResizeObserver(() => this.measure());
    // Rows that appear or go away (a search, an expanded branch) change the scroll height
    // but not the size of the host, so the resize observer does not see them.
    const mutations = new MutationObserver(() => this.measure());
    afterNextRender(() => {
      observer.observe(host);
      mutations.observe(host, { childList: true, subtree: true });
      this.measure();
    });
    inject(DestroyRef).onDestroy(() => {
      observer.disconnect();
      mutations.disconnect();
    });
  }

  /** Read the scroll position and write the two classes. Cheap enough to run on scroll. */
  protected measure(): void {
    const el = this.el.nativeElement;
    // A sub-pixel layout leaves a fraction of a pixel over on a strip that visibly fits.
    const slack = 1;
    const y = this.axis() === 'y';
    const max = y ? el.scrollHeight - el.clientHeight : el.scrollWidth - el.clientWidth;
    const pos = y ? el.scrollTop : el.scrollLeft;
    el.classList.toggle('is-fade-start', pos > slack);
    el.classList.toggle('is-fade-end', pos < max - slack);
  }
}
