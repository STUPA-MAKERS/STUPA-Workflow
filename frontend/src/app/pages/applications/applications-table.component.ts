import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
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
  imports: [RouterLink, LocalizedDatePipe, TranslatePipe, BadgeComponent],
  templateUrl: './applications-table.component.html',
  styleUrl: './applications-table.component.scss',
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
