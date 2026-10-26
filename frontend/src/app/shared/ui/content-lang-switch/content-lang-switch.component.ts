import { ChangeDetectionStrategy, Component, computed, inject, input, model } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { FilterSelectComponent, type FilterSelectOption } from '@stupa-makers/ui-kit';

/** A language of the content that an editor writes: `de`, `en` or an extra language. */
export type ContentLang = string;

/**
 * The dropdown of the language that the text fields of an editor show: DE, EN, then the
 * active extra languages, each by its native name. The chip shows the name of the picked
 * language. It is the app list (popover, bottom sheet on a phone), so any number of languages
 * fits.
 *
 * The editor keeps the language in a signal (or in {@link ContentLangState}) and binds it with
 * `[(value)]`. The dropdown changes only which language the fields show; it never changes the
 * page language.
 *
 * ```html
 * <app-content-lang-switch [(value)]="contentLang.lang" [ariaLabel]="'admin.common.contentLang' | t" />
 * ```
 */
@Component({
  selector: 'app-content-lang-switch',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FilterSelectComponent],
  templateUrl: './content-lang-switch.component.html',
  styleUrl: './content-lang-switch.component.scss',
})
export class ContentLangSwitchComponent {
  private readonly i18n = inject(I18nService);

  /** The language the fields show. */
  readonly value = model<ContentLang>('de');
  /** The accessible name of the dropdown and the title of its sheet. */
  readonly ariaLabel = input.required<string>();

  protected readonly options = computed<FilterSelectOption[]>(() =>
    this.i18n.locales().map((code) => ({ value: code, label: this.i18n.languageName(code) })),
  );

  /** The native name of the picked language. */
  protected readonly text = computed(() => this.i18n.languageName(this.value()));

  /** An empty value is German, so the editor always has a language. */
  protected pick(value: string | null): void {
    this.value.set(value || 'de');
  }
}
