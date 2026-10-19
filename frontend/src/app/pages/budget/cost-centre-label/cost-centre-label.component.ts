import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * A cost centre in running text: its colour mark, then its name (or its path).
 *
 * The host is inline, so the label flows in a sub line or a definition and takes the
 * ellipsis of its line. The mark sits on the text baseline. Without a colour only the
 * name shows. Set `--ccl-size` (10px) for the size of the mark and `--ccl-gap` (6px) for
 * the space between the mark and the name.
 *
 * ```html
 * <app-cost-centre-label [name]="cc.name" [color]="cc.color" [title]="cc.name" />
 * ```
 */
@Component({
  selector: 'app-cost-centre-label',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './cost-centre-label.component.html',
  styleUrl: './cost-centre-label.component.scss',
})
export class CostCentreLabelComponent {
  /** The text after the mark: the name, or a path such as "AStA › Kultur". */
  readonly name = input.required<string>();
  /** The colour of the cost centre. `null`: no mark. */
  readonly color = input<string | null | undefined>(null);
}
