import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  BadgeComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  type SortState as TableSortState,
} from '@stupa-makers/ui-kit';

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
 * Applications table. It gives one look to the application list (`/applications`) and to
 * any other page that lists applications. A pure presentation component: the rows arrive
 * normalized, and each row links to the application detail page.
 *
 * The markup, the sort affordance and the loading state come from the shared
 * `app-data-table`. This component only maps application rows onto it, so a change to
 * how tables look lands here without an edit.
 */
@Component({
  selector: 'app-applications-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    LocalizedDatePipe,
    TranslatePipe,
    BadgeComponent,
    DataTableComponent,
    CellDirective,
  ],
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
  /** Keeps the header and shows skeleton rows instead of collapsing the table. */
  readonly loading = input(false);

  readonly rowId = (row: unknown): string => (row as ApplicationRow).id;

  /**
   * Only amount and creation date are sortable, and only when the caller passes a sort.
   * A page that renders a fixed list gets plain headers rather than controls that do
   * nothing.
   */
  protected readonly columns = computed<ColumnDef[]>(() => {
    const sortable = this.sort() !== null;
    return [
      // Widths are floors, so a column keeps its room and the table scrolls rather than
      // crushing one. Without them "Nicht-monetärer Antrag" broke across three lines and
      // made its row twice the height of its neighbours.
      // Named as the card's heading rather than left to fall there by being first, so a
      // column reorder cannot quietly move the heading onto a date.
      {
        key: 'title',
        label: this.i18n.translate('applications.list.col.title'),
        width: '26rem',
        card: 'title',
      },
      { key: 'typeLabel', label: this.i18n.translate('applications.list.col.type'), width: '12rem' },
      { key: 'stateLabel', label: this.i18n.translate('applications.list.col.state'), width: '13rem' },
      {
        key: 'amount',
        label: this.i18n.translate('applications.list.col.amount'),
        align: 'end',
        sortable,
        initialSort: 'desc',
        width: '8rem',
      },
      {
        key: 'createdAt',
        label: this.i18n.translate('applications.list.col.created'),
        sortable,
        initialSort: 'desc',
        width: '10rem',
      },
    ];
  });

  /** Map this component's sort shape onto the one the shared table speaks. */
  protected readonly tableSort = computed<TableSortState | undefined>(() => {
    const cur = this.sort();
    return cur ? { key: cur.field, direction: cur.order } : undefined;
  });

  protected onSortChange(next: TableSortState): void {
    this.sortChange.emit({
      field: next.key as SortField,
      order: next.direction,
    });
  }

  protected money(value: string | number | null | undefined, currency?: string | null): string {
    if (value === null || value === undefined || value === '') return '—';
    const n = Number(value);
    if (Number.isNaN(n)) return String(value);
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: currency ?? 'EUR',
    }).format(n);
  }
}
