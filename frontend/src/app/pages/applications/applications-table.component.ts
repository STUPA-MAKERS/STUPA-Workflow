import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { BadgeComponent } from '@stupa-makers/ui-kit';

/** Normalized application row for the shared table. */
export interface ApplicationRow {
  id: string;
  /** Display title (already resolved with fallback). */
  title: string;
  /** Application type in the gray subline and the type column. Empty hides it. */
  typeLabel?: string | null;
  stateLabel?: string | null;
  /** Freely configured state color as hex. `null` gives a neutral badge. */
  stateColor?: string | null;
  amount?: string | number | null;
  currency?: string | null;
  createdAt?: string | null;
}

export type SortField = 'amount' | 'createdAt';
export interface SortState {
  field: SortField;
  order: 'asc' | 'desc';
}

/**
 * Shared applications table. It gives one look to the application list (`/applications`)
 * and to the applications table under budget. This is a pure presentation component. The
 * rows arrive normalized. Sorting is optional and the header is clickable only when `sort`
 * is set. Each row links to the application detail page.
 */
@Component({
  selector: 'app-applications-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LocalizedDatePipe, TranslatePipe, BadgeComponent],
  templateUrl: './applications-table.component.html',
  styleUrl: './applications-table.component.scss',
})
export class ApplicationsTableComponent {
  private readonly i18n = inject(I18nService);

  readonly rows = input<ApplicationRow[]>([]);
  readonly emptyText = input<string>('');
  /** Current sort. `null` makes the header text plain and not clickable. */
  readonly sort = input<SortState | null>(null);
  readonly sortChange = output<SortState>();

  protected money(value: string | number | null | undefined, currency?: string | null): string {
    if (value === null || value === undefined || value === '') return '—';
    const n = Number(value);
    if (Number.isNaN(n)) return String(value);
    return new Intl.NumberFormat(this.i18n.locale(), {
      style: 'currency',
      currency: currency ?? 'EUR',
    }).format(n);
  }

  protected toggleSort(field: SortField): void {
    const cur = this.sort();
    const order: 'asc' | 'desc' =
      cur?.field === field && cur.order === 'desc' ? 'asc' : 'desc';
    this.sortChange.emit({ field, order });
  }

  protected indicator(field: SortField): string {
    const cur = this.sort();
    if (!cur || cur.field !== field) return '';
    return cur.order === 'asc' ? ' ↑' : ' ↓';
  }

  protected ariaSort(field: SortField): 'ascending' | 'descending' | 'none' {
    const cur = this.sort();
    if (!cur || cur.field !== field) return 'none';
    return cur.order === 'asc' ? 'ascending' : 'descending';
  }
}
