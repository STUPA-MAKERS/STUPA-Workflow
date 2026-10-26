import { ChangeDetectionStrategy, Component, computed, inject, input, model } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { SegmentedComponent, type SegmentedOption } from '@stupa-makers/ui-kit';

/** A language of the content that an editor writes: `de`, `en` or an extra language. */
export type ContentLang = string;

/**
 * "DE | EN | …": the language of the text fields of an editor (mail templates, branding). The
 * active extra languages follow DE and EN.
 *
 * The editor keeps the language in a signal and binds it with `[(value)]`. The switch
 * changes only which language the fields show; it never changes the page language.
 *
 * ```html
 * <app-content-lang-switch [(value)]="lang" [ariaLabel]="'admin.brand.textLang' | t" />
 * ```
 *
 * `width="fill"` lets the switch take the width of its container, so a page can make it
 * full width on a phone.
 */
@Component({
  selector: 'app-content-lang-switch',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SegmentedComponent],
  templateUrl: './content-lang-switch.component.html',
  styleUrl: './content-lang-switch.component.scss',
})
export class ContentLangSwitchComponent {
  /** The language the fields show. */
  readonly value = model<ContentLang>('de');
  /** The accessible name of the switch. */
  readonly ariaLabel = input.required<string>();
  /** `equal`: as wide as its segments. `fill`: as wide as its container. */
  readonly width = input<'equal' | 'fill'>('equal');

  private readonly i18n = inject(I18nService);

  /** The language codes as the editors show them. */
  protected readonly options = computed<SegmentedOption[]>(() =>
    this.i18n.locales().map((code) => ({ value: code, label: code.toUpperCase() })),
  );

  /** An empty value is German, so the editor always has a language. */
  protected pick(value: string | null): void {
    this.value.set(value || 'de');
  }
}
