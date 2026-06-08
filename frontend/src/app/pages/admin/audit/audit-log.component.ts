import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
} from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import type { AuditEntry } from '../admin.models';

const PAGE_SIZE = 50;

/**
 * Audit-Log-Ansicht (#45, T-23). Liest das append-only Audit-Log über
 * `GET /admin/audit` (Server erzwingt `audit.read`; FE ist nur UX-Gate). Zeigt
 * Zeit/Aktion/Akteur/Ziel als geteilte {@link DataTableComponent}, „Mehr laden"
 * paginiert per Offset.
 */
@Component({
  selector: 'app-audit-log',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, TranslatePipe, ButtonComponent, BadgeComponent, DataTableComponent, CellDirective],
  template: `
    <section class="audit">
      <header class="audit__head">
        <div>
          <h1>{{ 'admin.audit.title' | t }}</h1>
          <p class="audit__desc">{{ 'admin.audit.desc' | t }}</p>
        </div>
      </header>

      @if (loadError()) {
        <p class="audit__status audit__status--error" role="alert">{{ 'admin.audit.error' | t }}</p>
      }

      <app-data-table [columns]="columns()" [rows]="entries()" [emptyText]="'admin.audit.empty' | t">
        <ng-template appCell="at" let-e>
          <span class="audit__mono">{{ $any(e).at | date: 'yyyy-MM-dd HH:mm:ss' }}</span>
        </ng-template>
        <ng-template appCell="action" let-e>
          <app-badge variant="neutral">{{ $any(e).action }}</app-badge>
        </ng-template>
        <ng-template appCell="target" let-e>
          <span class="audit__mono">{{ $any(e).targetType }}{{ $any(e).targetId ? ':' + $any(e).targetId : '' }}</span>
        </ng-template>
      </app-data-table>

      @if (hasMore()) {
        <div class="audit__more">
          <app-button variant="secondary" size="sm" [loading]="loading()" (click)="loadMore()">
            {{ 'admin.audit.loadMore' | t }}
          </app-button>
        </div>
      }
    </section>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
      }
      .audit__head h1 {
        margin: 0;
      }
      .audit__desc {
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
        margin: var(--space-1) 0 0;
      }
      .audit__mono {
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-xs);
      }
      .audit__status--error {
        color: var(--color-danger);
      }
      .audit__more {
        display: flex;
        justify-content: center;
      }
    `,
  ],
})
export class AuditLogComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);

  protected readonly entries = signal<AuditEntry[]>([]);
  protected readonly total = signal(0);
  protected readonly loading = signal(false);
  protected readonly loadError = signal(false);

  protected readonly hasMore = computed(() => this.entries().length < this.total());

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'at', label: this.i18n.translate('admin.audit.col.at'), width: '12rem' },
    { key: 'action', label: this.i18n.translate('admin.audit.col.action') },
    { key: 'actor', label: this.i18n.translate('admin.audit.col.actor') },
    { key: 'target', label: this.i18n.translate('admin.audit.col.target') },
  ]);

  constructor() {
    this.load();
  }

  protected loadMore(): void {
    this.load();
  }

  private load(): void {
    if (this.loading()) return;
    this.loading.set(true);
    this.loadError.set(false);
    this.api.listAuditLog({ limit: PAGE_SIZE, offset: this.entries().length }).subscribe({
      next: (page) => {
        this.entries.update((cur) => [...cur, ...page.items]);
        this.total.set(page.total);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }
}
