import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { ButtonComponent, InfiniteScrollDirective } from '@stupa-makers/ui-kit';

/**
 * The end of a list that loads more: the infinite-scroll sentinel and, beside it, the small
 * text button that loads the next page by hand (the fallback without
 * `IntersectionObserver`, and the keyboard way).
 *
 * ```html
 * @if (hasMore()) {
 *   <app-load-more [label]="'x.loadMore' | t" [loading]="loadingMore()" (more)="loadMore()" />
 * }
 * ```
 */
@Component({
  selector: 'app-load-more',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, InfiniteScrollDirective],
  template: `<div class="lm__sentinel" appInfiniteScroll [scrollRoot]="scrollRoot()" (scrolledToEnd)="more.emit()" aria-hidden="true"></div>
    <div class="lm__btn">
      <app-button variant="text" size="sm" [loading]="loading()" (click)="more.emit()">{{ label() }}</app-button>
    </div>`,
  styles: `
    :host { display: block; }
    .lm__sentinel { height: 1px; }
    .lm__btn { display: flex; justify-content: center; padding: var(--space-2) 0; }
  `,
})
export class LoadMoreComponent {
  /** The text of the button ("Mehr laden"). */
  readonly label = input.required<string>();
  /** The next page is on its way. */
  readonly loading = input(false);
  /** The box that scrolls, when the list scrolls in its own box; null = the viewport. */
  readonly scrollRoot = input<Element | null>(null);
  /** Load the next page. */
  readonly more = output<void>();
}
