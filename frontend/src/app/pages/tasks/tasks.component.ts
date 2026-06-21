import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { ApplicationListItem, ApplicationType, Uuid } from '@core/api/models';
import {
  BadgeComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
} from '@stupa-makers/ui-kit';

/**
 * Aufgaben (#64): Anträge mit ausstehender Entscheidung für die eigene Rolle
 * (vote-States, in denen der Nutzer abstimmen darf). Tabellarisch; Klick auf eine
 * Zeile öffnet die Detailansicht (dort liegt das Abstimmen / der Übergang).
 */
@Component({
  selector: 'app-tasks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, BadgeComponent, DataTableComponent, CellDirective],
  templateUrl: './tasks.component.html',
  styleUrl: './tasks.component.scss',
})
export class TasksComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);

  protected readonly tasks = signal<ApplicationListItem[]>([]);
  protected readonly loading = signal(true);
  private readonly types = signal<ApplicationType[]>([]);
  private readonly typesById = computed(
    () => new Map(this.types().map((t) => [t.id, t.name])),
  );

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'title', label: this.i18n.translate('tasks.col.title') },
    { key: 'type', label: this.i18n.translate('tasks.col.type') },
    { key: 'state', label: this.i18n.translate('tasks.col.state') },
    { key: 'amount', label: this.i18n.translate('tasks.col.amount'), align: 'end', width: '10rem' },
    { key: 'waiting', label: this.i18n.translate('tasks.col.waiting'), align: 'end', width: '10rem' },
  ]);

  /** Antragstitel (System-Titelfeld) mit Fallback. */
  protected titleOf(item: ApplicationListItem): string {
    return item.title?.trim() || this.i18n.translate('applications.list.untitled');
  }

  /** Antragstyp-Name (über die geladenen Typen aufgelöst). */
  protected typeName(typeId: Uuid): string {
    return this.typesById().get(typeId) ?? '—';
  }

  /**
   * Wartezeit als relative Angabe (z. B. „vor 5 Tagen") — für die Aufgaben-Queue
   * zählt das Alter, nicht das genaue Datum. Auf Basis von ``createdAt``.
   */
  protected waitingSince(createdAt: string | null): string {
    if (!createdAt) return '—';
    const days = Math.floor((Date.now() - new Date(createdAt).getTime()) / 86_400_000);
    const rtf = new Intl.RelativeTimeFormat(this.i18n.locale() === 'en' ? 'en' : 'de', {
      numeric: 'auto',
    });
    return days <= 0 ? rtf.format(0, 'day') : rtf.format(-days, 'day');
  }

  constructor() {
    this.api.applicationTypes({ quiet: true }).subscribe({
      next: (t) => this.types.set(t),
      error: () => this.types.set([]),
    });
    this.reload();
  }

  private reload(): void {
    this.api.listTasks().subscribe({
      next: (t) => {
        this.tasks.set(t);
        this.loading.set(false);
      },
      error: () => {
        this.tasks.set([]);
        this.loading.set(false);
      },
    });
  }

  protected open(id: Uuid): void {
    void this.router.navigate(['/applications', id]);
  }
}
