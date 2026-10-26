import { ChangeDetectionStrategy, Component, computed, inject, input, model } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { I18nMap } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { langFieldLabel, setI18n } from '@shared/forms/i18n-text';
import { InputComponent } from '@stupa-makers/ui-kit';

/** One field of the component: the language, its label and its accessible name. */
interface LangField {
  code: string;
  label: string;
  ariaLabel: string;
}

/**
 * A text in every content language: one field each for DE, EN and the active extra languages.
 *
 * The host has `display: contents`, so the fields are items of the grid or the flex row of
 * the page (beside a key field, or as columns). The fields use `ngModel` with `standalone`,
 * so they do not join a form of the page and need no `name`.
 *
 * ```html
 * <div class="x__pair">
 *   <app-i18n-input [value]="draft().label" (valueChange)="patch('label', $event)" />
 * </div>
 * ```
 *
 * Each field is labelled "<label> (<CODE>)", the label "Bezeichnung" by default. `short`
 * labels each field with its code alone (in a narrow row) and keeps the long label as the
 * accessible name. `placeholder` is the placeholder of the German field.
 */
@Component({
  selector: 'app-i18n-input',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, InputComponent],
  templateUrl: './i18n-input.component.html',
  styleUrl: './i18n-input.component.scss',
})
export class I18nInputComponent {
  private readonly i18n = inject(I18nService);

  /** The text per language. */
  readonly value = model<I18nMap>({});
  /** The label of the fields without the language. `null`: "Bezeichnung". */
  readonly label = input<string | null>(null);
  /** Label each field with its language code alone. */
  readonly short = input(false);
  /** The placeholder of the German field. */
  readonly placeholder = input('');

  protected readonly fields = computed<LangField[]>(() => {
    const label = this.label() ?? this.i18n.translate('admin.common.label');
    return this.i18n.locales().map((code) => {
      const long = langFieldLabel(label, code);
      return { code, label: this.short() ? code.toUpperCase() : long, ariaLabel: this.short() ? long : '' };
    });
  });

  protected set(code: string, text: string): void {
    this.value.set(setI18n(this.value(), code, text));
  }
}
