import { ChangeDetectionStrategy, Component, computed, inject, input, model } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { I18nMap } from '@core/api/models';
import { I18nService, fallbackChain } from '@core/i18n/i18n.service';
import { langFieldLabel, setI18n } from '@shared/forms/i18n-text';
import { ContentLangState } from '@shared/ui/content-lang-switch/content-lang.state';
import { InputComponent } from '@stupa-makers/ui-kit';

/**
 * The text of a `{lang: text}` map in the content language of the editor: one field.
 *
 * The editor provides {@link ContentLangState} and puts `app-content-lang-switch` beside its
 * fields; the field shows the language picked there. Without a state the field is German.
 * An empty field shows the text that a reader of its language gets instead (the fallback
 * chain: an extra language → EN → DE) as its placeholder; the German field shows
 * `placeholder`.
 *
 * ```html
 * <app-i18n-input [value]="draft().label" (valueChange)="patch('label', $event)" />
 * ```
 *
 * The field is labelled "<label> (<CODE>)", the label "Bezeichnung" by default. `short`
 * labels it with the code alone (in a narrow row) and keeps the long label as the accessible
 * name. The host has `display: contents`, so the field is an item of the grid or the flex row
 * of the page. It uses `ngModel` with `standalone`, so it does not join a form of the page.
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
  private readonly state = inject(ContentLangState, { optional: true });

  /** The text per language. */
  readonly value = model<I18nMap>({});
  /** The label of the field without the language. `null`: "Bezeichnung". */
  readonly label = input<string | null>(null);
  /** Label the field with its language code alone. */
  readonly short = input(false);
  /** The placeholder of the German field. */
  readonly placeholder = input('');

  /** The language of the field. */
  protected readonly lang = computed(() => this.state?.lang() ?? 'de');

  protected readonly fieldLabel = computed(() => {
    const long = langFieldLabel(this.label() ?? this.i18n.translate('admin.common.label'), this.lang());
    return this.short() ? { label: this.lang().toUpperCase(), ariaLabel: long } : { label: long, ariaLabel: '' };
  });

  /** The text a reader of the language gets while the field is empty. */
  protected readonly fallback = computed(() => {
    const map = this.value();
    for (const code of fallbackChain(this.lang()).slice(1)) {
      if (map[code]) return map[code];
    }
    return this.lang() === 'de' ? this.placeholder() : '';
  });

  protected set(text: string): void {
    this.value.set(setI18n(this.value(), this.lang(), text));
  }
}
