import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Ein Filter-Feld im {@link FilterBarComponent}-Popover: Label + projizierte
 * Steuerung (native input/select oder `<app-select>`). Einheitliche Optik für
 * alle Listen. Controls erben `.filter-field__control`-Styling über `::ng-deep`,
 * sodass Konsumenten nur ihr Control projizieren müssen.
 */
@Component({
  selector: 'app-filter-field',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './filter-field.component.html',
  styleUrl: './filter-field.component.scss',
})
export class FilterFieldComponent {
  /** Sichtbares Label über dem Control. */
  readonly label = input('');
}
