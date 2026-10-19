import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * The head of a section on a settings or admin page: the title, a count, actions at the end.
 *
 * ```html
 * <app-section-header headingId="dl-active-title" [heading]="'admin.deleg.active' | t" [count]="n">
 *   <app-button variant="text" size="sm">…</app-button>
 * </app-section-header>
 * ```
 *
 * The title has the global `section-title` look and carries `headingId`, so the section
 * can name itself with `aria-labelledby`. Without a heading the actions sit at the end.
 * The count is quiet small text (for example "3" or "8 von 24").
 *
 * The geometry follows the page with custom properties on the host:
 * `--sh-align` (center), `--sh-wrap` (wrap), `--sh-gap` (space-2 space-4),
 * `--sh-min-height` (auto), `--sh-inset` (the inline padding of the row, space-1),
 * `--sh-title-inset` (the inline padding of the title, 0), `--sh-title-min` (the min-width
 * of the title, auto) and `--sh-count-nums`
 * (tabular-nums).
 */
@Component({
  selector: 'app-section-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './section-header.component.html',
  styleUrl: './section-header.component.scss',
})
export class SectionHeaderComponent {
  /** The title. `null`: only the actions. */
  readonly heading = input<string | null>(null);
  /** The id of the title, for `aria-labelledby` of the section. */
  readonly headingId = input<string | null>(null);
  /** The level of the title: 2 on a page, 3 inside a card or a dialog. */
  readonly level = input<2 | 3>(2);
  /** A count beside the title. `null` shows none. */
  readonly count = input<string | number | null>(null);
}
