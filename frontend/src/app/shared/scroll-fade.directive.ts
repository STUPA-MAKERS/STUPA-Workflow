import {
  DestroyRef,
  Directive,
  ElementRef,
  afterNextRender,
  inject,
} from '@angular/core';

/**
 * Fade the ends of a horizontally scrolling strip, but only where content is hidden.
 *
 * A hidden scrollbar leaves a hard cut as the only cue that a strip scrolls at all, and a
 * half-sliced label reads as a rendering fault rather than "there is more".
 *
 * A pure-CSS mask cannot do this. Two static gradients fade both ends always, whatever
 * the scroll position, and a width media query cannot know whether a strip overflows —
 * that depends on how much room its siblings took, not on the viewport. So the state is
 * measured and written back as two classes:
 *
 * * `is-fade-start` — content is hidden to the left
 * * `is-fade-end` — content is hidden to the right
 *
 * A strip that fits carries neither and is not masked at all, so its first and last item
 * stay sharp.
 */
@Directive({
  selector: '[appScrollFade]',
  standalone: true,
  host: { '(scroll)': 'measure()' },
})
export class ScrollFadeDirective {
  private readonly el = inject<ElementRef<HTMLElement>>(ElementRef);

  constructor() {
    const host = this.el.nativeElement;
    // A resize changes what fits, and so does a nav item appearing after a permission
    // loads. Observing the element covers both without a window listener.
    const observer = new ResizeObserver(() => this.measure());
    afterNextRender(() => {
      observer.observe(host);
      this.measure();
    });
    inject(DestroyRef).onDestroy(() => observer.disconnect());
  }

  /** Read the scroll position and write the two classes. Cheap enough to run on scroll. */
  protected measure(): void {
    const el = this.el.nativeElement;
    // A sub-pixel layout leaves a fraction of a pixel over on a strip that visibly fits.
    const slack = 1;
    const max = el.scrollWidth - el.clientWidth;
    el.classList.toggle('is-fade-start', el.scrollLeft > slack);
    el.classList.toggle('is-fade-end', el.scrollLeft < max - slack);
  }
}
