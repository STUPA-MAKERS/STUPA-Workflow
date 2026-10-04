import {
  DestroyRef,
  Directive,
  ElementRef,
  afterRenderEffect,
  inject,
  input,
  signal,
} from '@angular/core';

/**
 * Tells if the text of a one-line element is cut.
 *
 * The host is an element with an ellipsis (`ell`). `truncated()` is true while its text
 * is wider than its box. A character count cannot know how wide a column ends up, so the
 * directive measures the element: after each render in which the text changes, and when
 * the box changes its size (ResizeObserver).
 *
 * Bind the text as the input (`[appTruncated]="text"`), so that a new text measures
 * again. Read the result through the template reference (`#t="appTruncated"`).
 */
@Directive({
  selector: '[appTruncated]',
  standalone: true,
  exportAs: 'appTruncated',
})
export class TruncatedDirective {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** The text of the host. A change measures again. */
  readonly text = input<string | null | undefined>('', { alias: 'appTruncated' });

  private readonly cut = signal(false);
  /** True while the text of the host is wider than its box. */
  readonly truncated = this.cut.asReadonly();

  constructor() {
    afterRenderEffect(() => {
      this.text();
      this.measure();
    });
    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(() => this.measure());
      observer.observe(this.host.nativeElement);
      inject(DestroyRef).onDestroy(() => observer.disconnect());
    }
  }

  /** Compare the text width with the box width. One pixel of slack absorbs rounding. */
  measure(): void {
    const el = this.host.nativeElement;
    this.cut.set(el.scrollWidth > el.clientWidth + 1);
  }
}
