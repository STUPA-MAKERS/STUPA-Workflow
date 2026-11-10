import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { LocaleSwitchService } from '../locale-switch.service';
import { FilterSelectComponent, type FilterSelectOption } from '@stupa-makers/ui-kit';

/**
 * The language switch: the app-styled list of `app-filter-select`, never the native
 * list of the browser. Desktop: a popover under the chip. Phone: the shared bottom sheet.
 *
 * - `display="code"`: the chip shows "DE" with a globe (public top bar, guest page).
 * - `display="name"`: the chip shows "Deutsch" (account menu, beside its own label).
 *
 * The list always shows the native names: DE, EN, then the active extra languages with the
 * name from the admin page. A choice goes through `LocaleSwitchService`,
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
      [value]="i18n.uiLocale()"
      [text]="chipText()"
      [icon]="display() === 'code' ? 'globe' : null"
      [size]="size()"
      (valueChange)="choose($event)"
    />
  `,
  // The chip shows only capitals ("DE") or a name, and IBM Plex Sans puts the capitals of a
  // centred line box about 1px above the middle of the globe and the chevron. Two pixels of
  // top padding move the centred box, and with it the text, 1px down.
  styles: [':host { display: inline-flex; flex: none; } :host ::ng-deep .fs__text { padding-top: 2px; }'],
})
export class LanguageSelectComponent {
  protected readonly i18n = inject(I18nService);
  private readonly locales = inject(LocaleSwitchService);

  /** The name of the control and the title of the sheet. */
  readonly label = input.required<string>();
  readonly display = input<'code' | 'name'>('code');
  readonly size = input<'sm' | 'md'>('sm');

  protected readonly options = computed<FilterSelectOption[]>(() =>
    this.i18n.locales().map((loc) => ({ value: loc, label: this.i18n.languageName(loc) })),
  );

  protected readonly chipText = computed(() => {
    const loc = this.i18n.uiLocale();
    return this.display() === 'code' ? loc.toUpperCase() : this.i18n.languageName(loc);
  });

  protected choose(value: string): void {
    this.locales.switchTo(value);
  }
}
