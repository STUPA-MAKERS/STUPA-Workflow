import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { LocaleSwitchService } from '../locale-switch.service';

/** The native name of each language, the same in every locale. */
const LANGUAGE_NAME: Record<string, TranslationKey> = {
  de: 'shell.lang.de',
  en: 'shell.lang.en',
};

/**
 * The language switch (D8): the app-styled list of `app-filter-select`, never the native
 * list of the browser. Desktop: a popover under the chip. Phone: the shared bottom sheet.
 *
 * - `display="code"`: the chip shows "DE" with a globe (public top bar, guest page).
 * - `display="name"`: the chip shows "Deutsch" (account menu, beside its own label).
 *
 * The list always shows the native names. A choice goes through `LocaleSwitchService`,
 * which reloads the view.
 */
@Component({
  selector: 'app-language-select',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FilterSelectComponent],
  template: `
    <app-filter-select
      [label]="label()"
      [options]="options()"
      [value]="i18n.locale()"
      [text]="chipText()"
      [icon]="display() === 'code' ? 'globe' : null"
      [size]="size()"
      (valueChange)="choose($event)"
    />
  `,
  styles: [':host { display: inline-flex; flex: none; }'],
})
export class LanguageSelectComponent {
  protected readonly i18n = inject(I18nService);
  private readonly locales = inject(LocaleSwitchService);

  /** The name of the control and the title of the sheet. */
  readonly label = input.required<string>();
  readonly display = input<'code' | 'name'>('code');
  readonly size = input<'sm' | 'md'>('sm');

  protected readonly options = computed<FilterSelectOption[]>(() =>
    this.i18n.locales.map((loc) => ({ value: loc, label: this.nameOf(loc) })),
  );

  protected readonly chipText = computed(() => {
    const loc = this.i18n.locale();
    return this.display() === 'code' ? loc.toUpperCase() : this.nameOf(loc);
  });

  protected choose(value: string): void {
    this.locales.switchTo(value);
  }

  private nameOf(loc: string): string {
    const key = LANGUAGE_NAME[loc];
    return key ? this.i18n.translate(key) : loc.toUpperCase();
  }
}
