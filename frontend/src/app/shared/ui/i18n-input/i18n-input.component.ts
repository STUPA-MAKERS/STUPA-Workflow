import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { InputComponent } from '@stupa-makers/ui-kit';

/**
 * A text in both content languages: the German field, then the English field.
 *
 * The host has `display: contents`, so the two fields are items of the grid or the flex
 * row of the page (beside a key field, or as a pair of columns). The fields use
 * `ngModel` with `standalone`, so they do not join a form of the page and need no `name`.
 *
 * ```html
 * <div class="x__pair">
 *   <app-i18n-input [de]="draft().labelDe" (deChange)="patch('labelDe', $event)"
 *                   [en]="draft().labelEn" (enChange)="patch('labelEn', $event)" />
 * </div>
 * ```
 *
 * The labels default to "Bezeichnung (DE)" and "Bezeichnung (EN)". A short label (for
 * example "DE" in a narrow row) takes the long one as `deAriaLabel` / `enAriaLabel`.
 */
@Component({
  selector: 'app-i18n-input',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, InputComponent],
  templateUrl: './i18n-input.component.html',
  styleUrl: './i18n-input.component.scss',
})
export class I18nInputComponent {
  /** The German text. */
  readonly de = model<string>('');
  /** The English text. */
  readonly en = model<string>('');
  /** The label of the German field. `null`: "Bezeichnung (DE)". */
  readonly deLabel = input<string | null>(null);
  /** The label of the English field. `null`: "Bezeichnung (EN)". */
  readonly enLabel = input<string | null>(null);
  /** The accessible name of the German field, when its label is short. */
  readonly deAriaLabel = input('');
  /** The accessible name of the English field, when its label is short. */
  readonly enAriaLabel = input('');
  /** The placeholder of the German field. */
  readonly dePlaceholder = input('');
  /** The placeholder of the English field. */
  readonly enPlaceholder = input('');
}
