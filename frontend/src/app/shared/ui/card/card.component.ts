import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

/** Container-Fläche. Slots: [card-header], default body, [card-footer]. */
@Component({
  selector: 'app-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './card.component.html',
  styleUrl: './card.component.scss',
})
export class CardComponent {
  @Input() heading = '';
  @Input() interactive = false;
  /** Überschriften-Ebene des `heading` (a11y/heading-order). Default `<h3>`. */
  @Input() headingLevel: 2 | 3 | 4 = 3;
}
