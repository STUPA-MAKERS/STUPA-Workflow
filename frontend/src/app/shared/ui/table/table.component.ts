import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export interface Column<T> {
  key: keyof T & string;
  label: string;
  align?: 'start' | 'end';
}

/** Schlanke, datengetriebene Tabelle. Für komplexe Fälle später erweiterbar. */
@Component({
  selector: 'app-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <table class="tbl">
      @if (caption) {
        <caption class="tbl__caption">{{ caption }}</caption>
      }
      <thead>
        <tr>
          @for (col of columns; track col.key) {
            <th scope="col" [style.text-align]="col.align ?? 'start'">{{ col.label }}</th>
          }
        </tr>
      </thead>
      <tbody>
        @for (row of rows; track $index) {
          <tr>
            @for (col of columns; track col.key) {
              <td [style.text-align]="col.align ?? 'start'">{{ row[col.key] }}</td>
            }
          </tr>
        } @empty {
          <tr>
            <td class="tbl__empty" [attr.colspan]="columns.length">{{ emptyText }}</td>
          </tr>
        }
      </tbody>
    </table>
  `,
  styles: [
    `
      .tbl {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
      }
      .tbl__caption {
        text-align: start;
        padding-bottom: var(--space-3);
        color: var(--color-text-muted);
      }
      th,
      td {
        padding: var(--space-3) var(--space-4);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      th {
        font-weight: var(--fw-semibold);
        color: var(--color-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-size: var(--fs-xs);
      }
      tbody tr:hover {
        background: var(--color-surface-sunken);
      }
      .tbl__empty {
        text-align: center;
        color: var(--color-text-muted);
        padding: var(--space-6);
      }
    `,
  ],
})
export class TableComponent<T extends Record<string, unknown>> {
  @Input() columns: Column<T>[] = [];
  @Input() rows: T[] = [];
  @Input() caption = '';
  @Input() emptyText = 'Keine Einträge';
}
