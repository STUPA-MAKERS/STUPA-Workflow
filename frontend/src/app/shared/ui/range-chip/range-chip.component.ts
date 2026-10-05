import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  IconComponent,
  MEDIA,
} from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { SideSheetComponent } from '../side-sheet/side-sheet.component';

/** What a range chip filters: an amount in euro or a date (ISO `YYYY-MM-DD`). */
export type RangeKind = 'amount' | 'date';

/** The two bounds of a range. An empty string is an open bound. */
export interface RangeValue {
  from: string;
  to: string;
}

/**
 * A filter chip for a range: an amount from and to, or a date from and to.
 *
 * The chip opens a sheet with the two fields, from the start edge on a wide screen and
 * from the bottom on a phone, like the other filter sheets. The values are typed, so the
 * sheet edits a draft and only "Anwenden" applies it (`applied`). "Zurücksetzen" clears
 * both bounds and applies at once. Another close of the sheet keeps the old range.
 *
 * The chip shows the label while no bound is set. With a bound it shows the range, for
 * example "Betrag: 100,00 € – 500,00 €" or "Zeitraum: ab 01.09.2026", in the selected
 * look with a check mark.
 */
@Component({
  selector: 'app-range-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    FormsModule,
    IconComponent,
    SideSheetComponent,
    TranslatePipe,
  ],
  templateUrl: './range-chip.component.html',
  styleUrl: './range-chip.component.scss',
})
export class RangeChipComponent {
  private readonly i18n = inject(I18nService);

  /** The name of the filter: the chip text without a range and the sheet heading. */
  readonly label = input.required<string>();
  readonly kind = input<RangeKind>('amount');
  readonly from = input('');
  readonly to = input('');

  /** "Anwenden" or "Zurücksetzen" set a new range. */
  readonly applied = output<RangeValue>();

  private readonly phone = mediaQuerySignal(MEDIA.phone);
  protected readonly side = computed(() => (this.phone() ? 'bottom' : 'start'));

  protected readonly open = signal(false);
  protected readonly draftFrom = signal('');
  protected readonly draftTo = signal('');

  /** A bound is set. */
  readonly active = computed(() => this.from().trim() !== '' || this.to().trim() !== '');

  /** The chip text: the label, or the label with the range. */
  readonly chipText = computed(() => {
    const from = this.from().trim();
    const to = this.to().trim();
    if (!from && !to) return this.label();
    let range: string;
    if (from && to) range = `${this.format(from)} – ${this.format(to)}`;
    else if (from) range = this.i18n.translate('ui.range.fromOnly', { value: this.format(from) });
    else range = this.i18n.translate('ui.range.toOnly', { value: this.format(to) });
    return `${this.label()}: ${range}`;
  });

  /** The draft is a valid range: no bound, one bound, or a start before the end. */
  protected readonly draftValid = computed(() => {
    const from = this.draftFrom().trim();
    const to = this.draftTo().trim();
    if (!from || !to) return true;
    if (this.kind() === 'amount') return Number(from) <= Number(to);
    return from <= to;
  });

  /** Open the sheet on a copy of the current range. */
  openSheet(): void {
    this.draftFrom.set(this.from());
    this.draftTo.set(this.to());
    this.open.set(true);
  }

  apply(): void {
    if (!this.draftValid()) return;
    this.open.set(false);
    this.applied.emit({ from: this.draftFrom().trim(), to: this.draftTo().trim() });
  }

  reset(): void {
    this.draftFrom.set('');
    this.draftTo.set('');
    this.open.set(false);
    this.applied.emit({ from: '', to: '' });
  }

  private format(value: string): string {
    if (this.kind() === 'amount') {
      const n = Number(value);
      if (!Number.isFinite(n)) return value;
      return n.toLocaleString(this.i18n.formatLocale(), { style: 'currency', currency: 'EUR' });
    }
    const [y, m, d] = value.split('-').map(Number);
    if (!y || !m || !d) return value;
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(this.i18n.formatLocale(), {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      timeZone: 'UTC',
    });
  }
}
