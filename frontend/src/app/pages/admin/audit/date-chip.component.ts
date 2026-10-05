import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  computed,
  inject,
  input,
  model,
  viewChild,
} from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent } from '@stupa-makers/ui-kit';

/**
 * A filter chip for one day ("Von", "Bis"). The whole chip opens the date picker of
 * the browser; a set chip shows the day and a clear button.
 *
 * `value` is an ISO day (`YYYY-MM-DD`) or an empty string. The picker is a hidden
 * `<input type="date">`; the chip opens it with `showPicker()`. Where the browser has no
 * `showPicker()`, the input takes the focus, so the keyboard can still set the day.
 */
@Component({
  selector: 'app-date-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, TranslatePipe],
  templateUrl: './date-chip.component.html',
  styleUrl: './date-chip.component.scss',
})
export class DateChipComponent {
  private readonly i18n = inject(I18nService);

  /** The name of the filter, for example "Von". */
  readonly label = input.required<string>();
  /** The chosen day (`YYYY-MM-DD`), or an empty string. */
  readonly value = model('');

  private readonly picker = viewChild.required<ElementRef<HTMLInputElement>>('picker');

  /** "Von" or "Von: 29.09.2026". */
  protected readonly text = computed(() => {
    const day = this.value();
    if (!day) return this.label();
    const [y, m, d] = day.split('-').map(Number);
    const shown = new Intl.DateTimeFormat(this.i18n.formatLocale(), { dateStyle: 'medium' }).format(
      new Date(y, m - 1, d),
    );
    return `${this.label()}: ${shown}`;
  });

  protected open(): void {
    const el = this.picker().nativeElement;
    if (typeof el.showPicker === 'function') {
      try {
        el.showPicker();
        return;
      } catch {
        // A browser that refuses the call (no user gesture) falls through to the focus.
      }
    }
    el.focus();
  }

  protected onPick(event: Event): void {
    this.value.set((event.target as HTMLInputElement).value);
  }

  protected clear(): void {
    this.value.set('');
  }
}
