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
  templateUrl: './table.component.html',
  styleUrl: './table.component.scss',
})
export class TableComponent<T extends Record<string, unknown>> {
  @Input() columns: Column<T>[] = [];
  @Input() rows: T[] = [];
  @Input() caption = '';
  @Input() emptyText = 'Keine Einträge';
}
