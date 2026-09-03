import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';

/**
 * The header every page starts with: breadcrumbs, title, subtitle and actions.
 *
 * One component owns the whole block, so the breadcrumb cannot drift away from the title
 * it belongs to, and a `wide` route aligns the same way a normal one does.
 *
 * Put actions in the `actions` slot:
 *
 * ```html
 * <app-page-header [title]="'invoices.title' | t" [subtitle]="'invoices.subtitle' | t">
 *   <app-button actions (click)="add()">…</app-button>
 * </app-page-header>
 * ```
 */
@Component({
  selector: 'app-page-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [BreadcrumbsComponent],
  host: {
    '[class.ph--flush]': 'flush()',
    '[class.ph--rail]': 'rail()',
  },
  templateUrl: './page-header.component.html',
  styleUrl: './page-header.component.scss',
})
export class PageHeaderComponent {
  readonly title = input.required<string>();
  readonly subtitle = input<string | null>(null);

  /**
   * Drop the header's own bottom margin.
   *
   * Set it when the surrounding layout already spaces its children — a flex column
   * with a `gap`, for example. Otherwise the margin and the gap both apply and the
   * band under the title grows to the sum of the two.
   */
  readonly flush = input(false);

  /**
   * Follow a rail layout: cap the header at `--layout-max-width` and centre it.
   *
   * A rail page puts its content in a three-column grid — a rail that breaks out into
   * the margin, a main column capped at `--layout-max-width`, and a matching margin on
   * the other side — so the content is CENTRED. Such a page is also a `wide` route,
   * which removes the cap from `.main`. Without this the header filled the viewport and
   * started at the gutter while the table it titles started wherever the centred column
   * began: at 1920px the title sat at x=24 and its table at x=363. Narrow viewports
   * collapse the outer columns to zero, which is why it stayed hidden.
   *
   * Do NOT set it on a wide page whose content really does start at the gutter. There
   * the full-width header is correct, and that case is why the cap was dropped in the
   * first place.
   */
  readonly rail = input(false);
}
