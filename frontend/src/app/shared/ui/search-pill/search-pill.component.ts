import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  model,
  output,
} from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { isApplePlatform, searchShortcutLabel } from '../../../features/search/shortcut';

/** `button` opens something (the command palette); `input` filters in place. */
export type SearchPillMode = 'button' | 'input';

/**
 * The round search field.
 *
 * - `input` (default): a search input that filters in place. `value` is two-way;
 *   Escape clears it.
 * - `button`: looks the same but is a button that emits `activate`, for example to open
 *   the command palette. With `shortcut` it shows the key hint ("Strg+K", "⌘K" on a Mac)
 *   and names the shortcut for screen readers.
 *
 * The `[trail]` slot takes a control at the end of the pill, for example the filter
 * button of a list or the account button on a phone. It sits beside the field, never in
 * it, so the two stay separate controls.
 */
@Component({
  selector: 'app-search-pill',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  host: {
    '[class.sp--md]': "size() === 'md'",
  },
  templateUrl: './search-pill.component.html',
  styleUrl: './search-pill.component.scss',
})
export class SearchPillComponent {
  private readonly i18n = inject(I18nService);

  readonly mode = input<SearchPillMode>('input');
  /** The visible text in the empty field, for example "Anträge durchsuchen". */
  readonly placeholder = input.required<string>();
  /** The accessible name. Defaults to the placeholder. */
  readonly label = input<string | null>(null);
  /** Show the shortcut hint (button mode). */
  readonly shortcut = input(false);
  /** `lg` is 52px high (the main search), `md` is 44px (a list filter). */
  readonly size = input<'lg' | 'md'>('lg');

  /** The search text (input mode). */
  readonly value = model('');
  /** The button was pressed (button mode). */
  readonly activate = output<void>();

  protected readonly name = computed(() => this.label() ?? this.placeholder());
  protected readonly keyLabel = computed(() => searchShortcutLabel(this.i18n.locale()));
  protected readonly keys = computed(() =>
    this.shortcut() ? (isApplePlatform() ? 'Meta+K' : 'Control+K') : null,
  );

  protected onInput(event: Event): void {
    this.value.set((event.target as HTMLInputElement).value);
  }

  protected onKey(event: KeyboardEvent): void {
    if (event.key === 'Escape' && this.value() !== '') {
      event.preventDefault();
      event.stopPropagation();
      this.value.set('');
    }
  }
}
