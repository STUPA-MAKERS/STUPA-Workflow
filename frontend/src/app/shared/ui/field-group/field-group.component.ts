import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * A group of rows that reads as one block: the rows sit 2px apart, and only the outer
 * corners are round.
 *
 * It holds field rows (`app-field-row`) and also any other row, for example the rows of a
 * history day or a short list. The look is the global `.rowgroup` class in `styles.scss`, so a
 * page can also put `class="rowgroup"` on a plain element.
 *
 * `surface` picks the row colour: 2 (default) on the page or on a sheet of surface 1,
 * 3 in a side sheet of surface 2, 1 where the rows must stand out less.
 */
@Component({
  selector: 'app-field-group',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'rowgroup',
    '[class.rowgroup--bg1]': 'surface() === 1',
    '[class.rowgroup--bg3]': 'surface() === 3',
  },
  templateUrl: './field-group.component.html',
  styleUrl: './field-group.component.scss',
})
export class FieldGroupComponent {
  readonly surface = input<1 | 2 | 3>(2);
}

/**
 * A label above its value, one row of a field group.
 *
 * Give the value as `value` or as content. The `[trail]` slot takes an action for the
 * field, for example an edit button.
 */
@Component({
  selector: 'app-field-row',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'fld' },
  templateUrl: './field-row.component.html',
  styleUrl: './field-row.component.scss',
})
export class FieldRowComponent {
  readonly label = input.required<string>();
  /** The value as text. Leave it out to project the value as content. */
  readonly value = input<string | number | null>(null);
  /** Show the value in the mono face: amounts, dates, short IDs. */
  readonly mono = input(false);
}
