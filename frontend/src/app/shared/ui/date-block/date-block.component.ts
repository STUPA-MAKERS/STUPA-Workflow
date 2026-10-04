import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';

/**
 * A date as a block: the day large, the month short and in capitals below it ("29" over
 * "SEP"). For lists of meetings and the dashboard.
 *
 * `live` fills the block with the accent, for the meeting that runs now. A screen reader
 * hears the full date instead of the two parts.
 *
 * A missing or invalid date (null, or a string that is not a date) shows an empty block
 * with a dash, so the rows of a list stay aligned.
 */
@Component({
  selector: 'app-date-block',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '[class.db--live]': 'live()',
  },
  templateUrl: './date-block.component.html',
  styleUrl: './date-block.component.scss',
})
export class DateBlockComponent {
  private readonly i18n = inject(I18nService);

  /** The date, as an ISO string or a Date. Shown in local time. */
  readonly date = input.required<string | Date | null | undefined>();
  readonly live = input(false);

  private readonly parsed = computed(() => {
    const value = this.date();
    return value == null || value === '' ? new Date(NaN) : new Date(value);
  });

  /** False for a missing or invalid date. The template then shows the empty block. */
  protected readonly valid = computed(() => !Number.isNaN(this.parsed().getTime()));

  protected readonly iso = computed(() => (this.valid() ? this.parsed().toISOString() : ''));
  protected readonly day = computed(() => String(this.parsed().getDate()).padStart(2, '0'));
  /** "SEP", "OKT", "MÄR": the short month without its dot, three letters. */
  protected readonly month = computed(() =>
    this.parsed()
      .toLocaleDateString(this.i18n.formatLocale(), { month: 'short' })
      .replace('.', '')
      .slice(0, 3)
      .toLocaleUpperCase(this.i18n.formatLocale()),
  );
  protected readonly full = computed(() =>
    this.parsed().toLocaleDateString(this.i18n.formatLocale(), {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    }),
  );
}
