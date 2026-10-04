import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { ApplicationListItem, ApplicationType, IsoDateTime, Uuid } from '@core/api/models';
import {
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  IconComponent,
} from '@stupa-makers/ui-kit';
// By path, not through the `@shared/ui` barrel, so this lazy chunk takes only the blocks
// it uses.
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { flowColorKind } from '@shared/status-kind.util';

const DAY_MS = 86_400_000;

/**
 * Tasks (board Arbeit-Aufgaben): the applications that wait for an action of the user,
 * from GET /applications/tasks, in server order.
 *
 * The columns are title, type, status (as coloured text), amount and "Wartet seit". The
 * waiting time counts from the last status change (`stateSince`). An older server that
 * does not send it gives the time of the last change (`updatedAt`). A click on a row
 * opens the application. The vote and the transition happen there. When the request
 * fails, the page shows an error message instead of the table and the header count.
 */
@Component({
  selector: 'app-tasks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    DataTableComponent,
    CellDirective,
    IconComponent,
    PageHeaderComponent,
    StatusTextComponent,
  ],
  templateUrl: './tasks.component.html',
  styleUrl: './tasks.component.scss',
})
export class TasksComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);

  protected readonly tasks = signal<ApplicationListItem[]>([]);
  protected readonly loading = signal(true);
  /** The task request failed. The page then shows an error and no count, not "0 offen". */
  protected readonly error = signal(false);
  private readonly types = signal<ApplicationType[]>([]);
  private readonly typesById = computed(
    () => new Map(this.types().map((t) => [t.id, t.name])),
  );

  protected readonly columns = computed<ColumnDef[]>(() => [
    // The title takes the width that the other columns leave. They keep their content on
    // one line, so they are as wide as their longest value.
    { key: 'title', label: this.i18n.translate('tasks.col.title'), card: 'title', width: '100%' },
    { key: 'type', label: this.i18n.translate('tasks.col.type') },
    { key: 'state', label: this.i18n.translate('tasks.col.state') },
    { key: 'amount', label: this.i18n.translate('tasks.col.amount'), align: 'end' },
    { key: 'waiting', label: this.i18n.translate('tasks.col.waiting'), align: 'end' },
    { key: 'open', label: '', align: 'end', width: '3.25rem', card: 'hidden' },
  ]);

  protected readonly flowColorKind = flowColorKind;

  /** Application title (system title field) with fallback. */
  protected titleOf(item: ApplicationListItem): string {
    return item.title?.trim() || this.i18n.translate('applications.list.untitled');
  }

  /** Application-type name (resolved via the loaded types). */
  protected typeName(typeId: Uuid): string {
    return this.typesById().get(typeId) ?? '—';
  }

  /** The amount in the currency of the application, or a dash. */
  protected money(item: ApplicationListItem): string {
    if (item.amount === null || item.amount === undefined || item.amount === '') return '—';
    const n = Number(item.amount);
    if (Number.isNaN(n)) return item.amount;
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: item.currency ?? 'EUR',
    }).format(n);
  }

  /** The moment the task started to wait: the last status change, else the last change. */
  protected since(item: ApplicationListItem): IsoDateTime {
    return item.stateSince ?? item.updatedAt;
  }

  /**
   * How long the task waits, in whole days: "seit heute", "seit 1 Tag", "seit 5 Tagen"
   * (EN "today", "for 1 day", "for 5 days" under the header "Waiting").
   * A missing or invalid time gives a dash.
   */
  protected waitingSince(at: IsoDateTime | null | undefined): string {
    if (!at) return '—';
    const t = new Date(at).getTime();
    if (Number.isNaN(t)) return '—';
    const days = Math.max(0, Math.floor((Date.now() - t) / DAY_MS));
    if (days === 0) return this.i18n.translate('tasks.waiting.today');
    if (days === 1) return this.i18n.translate('tasks.waiting.one');
    return this.i18n.translate('tasks.waiting.other', { n: days });
  }

  /** The exact moment, for the tooltip of the waiting time. */
  protected sinceTitle(at: IsoDateTime | null | undefined): string | null {
    if (!at) return null;
    const d = new Date(at);
    if (Number.isNaN(d.getTime())) return null;
    const when = new Intl.DateTimeFormat(this.i18n.formatLocale(), {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(d);
    return this.i18n.translate('tasks.waiting.title', { date: when });
  }

  constructor() {
    this.api.applicationTypes({ quiet: true }).subscribe({
      next: (t) => this.types.set(t),
      error: () => this.types.set([]),
    });
    this.api.listTasks().subscribe({
      next: (t) => {
        this.tasks.set(t);
        this.loading.set(false);
      },
      error: () => {
        this.tasks.set([]);
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  protected open(id: Uuid): void {
    void this.router.navigate(['/applications', id]);
  }
}
