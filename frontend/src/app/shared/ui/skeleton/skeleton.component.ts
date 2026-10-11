import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** What shape the waiting content will have. */
export type SkeletonVariant = 'lines' | 'panel' | 'rows' | 'items';

/**
 * A loading placeholder in the shape of the content that is coming.
 *
 * One component rather than a `.skel` block per page: hand-rolled blocks drifted into
 * different heights, counts and rhythms, so two pages loading side by side looked like
 * two different applications. `app-data-table` draws its own skeleton rows and needs
 * nothing from here; this is for everything that is not a table.
 *
 * The blocks are decorative and hidden from the accessibility tree, so the component
 * always carries a `role="status"` line. A screen reader is told the page is loading;
 * it is not read a list of empty boxes.
 */
@Component({
  selector: 'app-skeleton',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './skeleton.component.html',
  styleUrl: './skeleton.component.scss',
})
export class SkeletonComponent {
  /**
   * `lines` for text, `rows` for a list of records, `panel` for one large block, `items`
   * for a list of `app-list-item` rows (title, sub line, trailing value) in their exact
   * geometry, so the list does not move when the rows arrive.
   */
  readonly variant = input<SkeletonVariant>('lines');
  /** `items`: the rows sit in a row group (`.rowgroup`), as the loaded list does. */
  readonly grouped = input(false);
  /** How many placeholders to draw. Ignored by `panel`, which is always one. */
  readonly count = input(3);
  /** What a screen reader hears. Always pass the page's own "loading" string. */
  readonly label = input('');

  protected readonly items = () => Array.from({ length: Math.max(1, this.count()) });

  /** Widths of the bars of an `items` row. Fixed per index, so a reload looks the same. */
  protected itemWidths(i: number): { title: string; a: string; b: string; trail: string } {
    return ITEM_WIDTHS[i % ITEM_WIDTHS.length];
  }
}

/** Bar widths that vary like real titles and sub lines, the same on every load. */
const ITEM_WIDTHS = [
  { title: '78%', a: '5.75rem', b: '4.5rem', trail: '4.5rem' },
  { title: '64%', a: '4.25rem', b: '4.5rem', trail: '3.5rem' },
  { title: '71%', a: '5.75rem', b: '5.75rem', trail: '4.5rem' },
  { title: '58%', a: '3.75rem', b: '4.5rem', trail: '4.5rem' },
  { title: '82%', a: '4.25rem', b: '4.5rem', trail: '4.5rem' },
  { title: '67%', a: '4.25rem', b: '4.5rem', trail: '3.5rem' },
] as const;
