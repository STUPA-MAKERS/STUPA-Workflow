import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { BadgeComponent } from '@shared/ui/badge/badge.component';

/** Normalisierte Antrags-Zeile für die geteilte Tabelle. */
export interface ApplicationRow {
  id: string;
  /** Anzeigetitel (bereits mit Fallback aufgelöst). */
  title: string;
  /** Antragstyp (graue Unterzeile + Typ-Spalte); leer = ausblenden. */
  typeLabel?: string | null;
  stateLabel?: string | null;
  /** Frei konfigurierte State-Farbe (Hex); `null` → neutrales Badge. */
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
 * Geteilte Antrags-Tabelle (#shared-apps-table). Eine Optik für die Antragsliste
 * (`/applications`) **und** die Antrags-Tabelle unter Budget. Reines Präsentations-
 * Component: Zeilen kommen normalisiert herein, Sortierung ist optional
 * (Header nur klickbar, wenn ``sort`` gesetzt ist). Jede Zeile verlinkt in die
 * Antrags-Detailseite.
 */
@Component({
  selector: 'app-applications-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, TranslatePipe, BadgeComponent],
  template: `
    <div class="atbl__wrap">
      <table class="atbl">
        <thead>
          <tr>
            <th scope="col">{{ 'applications.list.col.title' | t }}</th>
            <th scope="col">{{ 'applications.list.col.state' | t }}</th>
            <th scope="col" class="atbl__num" [attr.aria-sort]="ariaSort('amount')">
              @if (sort()) {
                <button type="button" class="atbl__sort" (click)="toggleSort('amount')">{{ 'applications.list.col.amount' | t }}{{ indicator('amount') }}</button>
              } @else {
                {{ 'applications.list.col.amount' | t }}
              }
            </th>
            <th scope="col" [attr.aria-sort]="ariaSort('createdAt')">
              @if (sort()) {
                <button type="button" class="atbl__sort" (click)="toggleSort('createdAt')">{{ 'applications.list.col.created' | t }}{{ indicator('createdAt') }}</button>
              } @else {
                {{ 'applications.list.col.created' | t }}
              }
            </th>
          </tr>
        </thead>
        <tbody>
          @for (row of rows(); track row.id) {
            <tr>
              <td>
                <a class="atbl__rowLink" [routerLink]="['/applications', row.id]">
                  <span class="atbl__rowTitle">{{ row.title }}</span>
                  @if (row.typeLabel) {
                    <span class="atbl__rowType">{{ row.typeLabel }}</span>
                  } @else {
                    <span class="atbl__rowHint">{{ 'applications.list.open' | t }}</span>
                  }
                </a>
              </td>
              <td>
                @if (row.stateLabel) {
                  <app-badge [color]="row.stateColor">{{ row.stateLabel }}</app-badge>
                } @else {
                  —
                }
              </td>
              <td class="atbl__num">{{ money(row.amount, row.currency) }}</td>
              <td>
                @if (row.createdAt) {
                  <time [attr.datetime]="row.createdAt">{{ row.createdAt | date: 'mediumDate' }}</time>
                } @else {
                  —
                }
              </td>
            </tr>
          } @empty {
            <tr>
              <td class="atbl__empty" colspan="4">{{ emptyText() }}</td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: [
    `
      .atbl__wrap {
        overflow-x: auto;
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        background: var(--color-surface);
      }
      .atbl {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
      }
      .atbl tbody tr:last-child td {
        border-bottom: none;
      }
      .atbl th,
      .atbl td {
        padding: var(--space-3) var(--space-4);
        border-bottom: var(--border-width) solid var(--color-border);
        text-align: start;
        vertical-align: middle;
      }
      .atbl th {
        font-weight: var(--fw-semibold);
        color: var(--color-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-size: var(--fs-xs);
      }
      .atbl__num {
        text-align: end;
        font-variant-numeric: tabular-nums;
      }
      .atbl__sort {
        background: transparent;
        border: 0;
        padding: 0;
        cursor: pointer;
        font: inherit;
        color: inherit;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-size: var(--fs-xs);
        font-weight: var(--fw-semibold);
      }
      .atbl__sort:hover {
        color: var(--color-primary);
      }
      .atbl tbody tr:hover {
        background: var(--color-surface-sunken);
      }
      .atbl__rowLink {
        display: inline-flex;
        flex-direction: column;
        color: var(--color-primary);
        font-weight: var(--fw-medium);
        text-decoration: none;
      }
      .atbl__rowLink:hover .atbl__rowTitle {
        text-decoration: underline;
      }
      .atbl__rowType,
      .atbl__rowHint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
        font-weight: var(--fw-normal);
      }
      .atbl__empty {
        text-align: center;
        color: var(--color-text-muted);
        padding: var(--space-6);
      }
    `,
  ],
})
export class ApplicationsTableComponent {
  private readonly i18n = inject(I18nService);

  readonly rows = input<ApplicationRow[]>([]);
  readonly emptyText = input<string>('');
  /** Aktuelle Sortierung; ``null`` → Header nicht klickbar. */
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
