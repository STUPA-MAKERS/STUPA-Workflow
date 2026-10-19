import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';
import { SegmentedComponent, type SegmentedOption } from '@stupa-makers/ui-kit';

/** A language of the content that an editor writes. */
export type ContentLang = 'de' | 'en';

/** The options of the switch: the language codes as the editors show them. */
const OPTIONS: readonly SegmentedOption[] = [
  { value: 'de', label: 'DE' },
  { value: 'en', label: 'EN' },
];

/**
 * "DE | EN": the language of the text fields of an editor (mail templates, branding).
 *
 * The editor keeps the language in a signal and binds it with `[(value)]`. The switch
 * changes only which language the fields show; it never changes the page language.
 *
 * ```html
 * <app-content-lang-switch [(value)]="lang" [ariaLabel]="'admin.brand.textLang' | t" />
 * ```
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

  protected readonly options = OPTIONS as SegmentedOption[];

  /** Anything but English is German, so the editor always has a language. */
  protected pick(value: string | null): void {
    this.value.set(value === 'en' ? 'en' : 'de');
  }
}
