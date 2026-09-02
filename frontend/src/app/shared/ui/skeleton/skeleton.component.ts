import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** What shape the waiting content will have. */
export type SkeletonVariant = 'lines' | 'panel' | 'rows';

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
  /** `lines` for text, `rows` for a list of records, `panel` for one large block. */
  readonly variant = input<SkeletonVariant>('lines');
  /** How many placeholders to draw. Ignored by `panel`, which is always one. */
  readonly count = input(3);
  /** What a screen reader hears. Always pass the page's own "loading" string. */
  readonly label = input('');

  protected readonly items = () => Array.from({ length: Math.max(1, this.count()) });
}
