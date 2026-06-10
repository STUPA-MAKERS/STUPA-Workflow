import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DatepickerComponent,
  FilterBarComponent,
  FilterFieldComponent,
} from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import type { AuditActor, AuditEntry } from '../admin.models';

const PAGE_SIZE = 50;

/**
 * Audit-Aktionstypen — Spiegel von `backend/app/modules/audit/actions.py`
 * (`AuditAction`). Treibt den Aktions-Filter und entscheidet, ob eine spezifische
 * Nachrichtenvorlage existiert (sonst Fallback `admin.audit.msg.unknown`).
 */
export const AUDIT_ACTIONS = [
  'login',
  'status_change',
  'vote_cast',
  'config_change',
  'config_activation',
  'role_change',
  'delegation_grant',
  'delegation_revoke',
  'delegation_use',
  'export',
  'pii_access',
  'pii_deletion',
  'anonymization',
  'webhook_config',
  'attachment_quarantine',
] as const;

const KNOWN_ACTIONS = new Set<string>(AUDIT_ACTIONS);

/**
 * Audit-Log-Ansicht (#45, T-23). Liest das append-only Audit-Log über
 * `GET /admin/audit` (Server erzwingt `audit.read`; FE ist nur UX-Gate).
 *
 * - **Lazy infinite scroll**: Keyset-Paging über `before`-Cursor (id); ein
 *   `IntersectionObserver`-Sentinel lädt nach, „Mehr laden" als Fallback.
 * - **Human-readable**: pro Aktionstyp eine i18n-Vorlage (`admin.audit.msg.*`),
 *   gefüllt aus `actor`/`target`/`data`; unbekannte Typen → `…msg.unknown`.
 * - **Filter**: Aktionstyp, Akteur (aufgelöster Klarname), Zeitfenster.
 */
@Component({
  selector: 'app-audit-log',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    BadgeComponent,
    FilterBarComponent,
    FilterFieldComponent,
    DataTableComponent,
    CellDirective,
    DatepickerComponent,
  ],
  template: `
    <section class="audit">
      <header class="audit__head">
        <div>
          <h1>{{ 'admin.audit.title' | t }}</h1>
          <p class="audit__desc">{{ 'admin.audit.desc' | t }}</p>
        </div>
        <app-filter-bar [live]="true" [activeCount]="activeFilterCount()" (reset)="resetFilters()">
          <app-filter-field [label]="'admin.audit.filter.action' | t">
            <select [value]="action()" (change)="setAction($any($event.target).value)">
              <option value="">{{ 'admin.audit.filter.allActions' | t }}</option>
              @for (a of actionOptions(); track a) {
                <option [value]="a">{{ actionLabel(a) }}</option>
              }
            </select>
          </app-filter-field>
          <app-filter-field [label]="'admin.audit.filter.actor' | t">
            <select [value]="actor()" (change)="setActor($any($event.target).value)">
              <option value="">{{ 'admin.audit.filter.allActors' | t }}</option>
              @for (a of actors(); track a.sub) {
                <option [value]="a.sub">{{ a.name || a.sub }}</option>
              }
            </select>
          </app-filter-field>
          <app-filter-field [label]="'admin.audit.filter.since' | t">
            <app-datepicker [ngModel]="since()" (ngModelChange)="setSince($event)" />
          </app-filter-field>
          <app-filter-field [label]="'admin.audit.filter.until' | t">
            <app-datepicker [ngModel]="until()" (ngModelChange)="setUntil($event)" />
          </app-filter-field>
        </app-filter-bar>
      </header>

      @if (loadError()) {
        <p class="audit__status audit__status--error" role="alert">{{ 'admin.audit.error' | t }}</p>
      }

      <app-data-table [columns]="columns()" [rows]="entries()" [rowKey]="rowId" [emptyText]="(loading() ? 'admin.audit.loading' : 'admin.audit.empty') | t">
        <ng-template appCell="at" let-e><span class="audit__mono">{{ $any(e).at | ldate: 'medium' }}</span></ng-template>
        <ng-template appCell="action" let-e><app-badge variant="neutral">{{ actionLabel($any(e).action) }}</app-badge></ng-template>
        <ng-template appCell="message" let-e>{{ message($any(e)) }}</ng-template>
        <ng-template appCell="data" let-e>
          @if (dataPairs($any(e)).length) {
            <div class="audit__data">
              @for (p of dataPairs($any(e)); track p[0]) {
                <span class="audit__chip audit__mono">{{ p[0] }}: {{ p[1] }}</span>
              }
            </div>
          } @else { — }
        </ng-template>
      </app-data-table>

      <div #sentinel class="audit__sentinel" aria-hidden="true"></div>

      @if (loading()) {
        <p class="audit__status" aria-live="polite">{{ 'admin.audit.loading' | t }}</p>
      } @else if (hasMore()) {
        <div class="audit__more">
          <app-button variant="secondary" size="sm" (click)="loadMore()">
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
      .audit__head {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: var(--space-3);
        flex-wrap: wrap;
      }
      .audit__head h1 {
        margin: 0;
      }
      .audit__desc {
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
        margin: var(--space-1) 0 0;
      }
      .audit__list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .audit__row {
        display: grid;
        grid-template-columns: 11rem 9rem 1fr;
        align-items: start;
        gap: var(--space-3);
        padding: var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface);
      }
      .audit__at {
        color: var(--color-text-muted);
      }
      .audit__body {
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .audit__msg {
        margin: 0;
      }
      .audit__data {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-1);
      }
      .audit__chip {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
        background: var(--color-surface-sunken);
        border-radius: var(--radius-sm);
        padding: 1px var(--space-2);
      }
      .audit__mono {
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-xs);
      }
      .audit__empty {
        color: var(--color-text-muted);
        padding: var(--space-4) 0;
        text-align: center;
        list-style: none;
      }
      .audit__status {
        color: var(--color-text-muted);
        text-align: center;
      }
      .audit__status--error {
        color: var(--color-danger);
      }
      .audit__sentinel {
        height: 1px;
      }
      .audit__more {
        display: flex;
        justify-content: center;
      }
      @media (max-width: 40rem) {
        .audit__row {
          grid-template-columns: 1fr;
        }
      }
    `,
  ],
})
export class AuditLogComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);

  protected readonly entries = signal<AuditEntry[]>([]);
  protected readonly actors = signal<AuditActor[]>([]);
  protected readonly cursor = signal<number | null>(null);
  protected readonly hasMore = signal(false);
  protected readonly loading = signal(false);
  protected readonly loadError = signal(false);

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'at', label: this.i18n.translate('admin.audit.col.at'), width: '12rem' },
    { key: 'action', label: this.i18n.translate('admin.audit.col.action'), width: '12rem' },
    { key: 'message', label: this.i18n.translate('admin.audit.col.message') },
    { key: 'data', label: this.i18n.translate('admin.audit.col.data') },
  ]);
  protected readonly rowId = (r: unknown): string => String((r as AuditEntry).id);

  // Filter
  protected readonly action = signal('');
  protected readonly actor = signal('');
  protected readonly since = signal('');
  protected readonly until = signal('');

  protected readonly actionOptions = computed(() => [...AUDIT_ACTIONS]);
  protected readonly activeFilterCount = computed(
    () =>
      (this.action() ? 1 : 0) +
      (this.actor() ? 1 : 0) +
      (this.since() ? 1 : 0) +
      (this.until() ? 1 : 0),
  );

  private readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  constructor() {
    this.api.listAuditActors().subscribe({
      next: (a) => this.actors.set(a),
      error: () => this.actors.set([]),
    });
    this.reload();

    effect((onCleanup) => {
      const el = this.sentinel()?.nativeElement;
      if (!el || typeof IntersectionObserver === 'undefined') return;
      const obs = new IntersectionObserver(
        (items) => {
          if (items.some((i) => i.isIntersecting)) this.loadMore();
        },
        { rootMargin: '400px' },
      );
      obs.observe(el);
      onCleanup(() => obs.disconnect());
    });
  }

  // --- Filter setters (each resets the list) --------------------------------
  protected setAction(v: string): void {
    this.action.set(v);
    this.reload();
  }
  protected setActor(v: string): void {
    this.actor.set(v);
    this.reload();
  }
  protected setSince(v: string): void {
    this.since.set(v);
    this.reload();
  }
  protected setUntil(v: string): void {
    this.until.set(v);
    this.reload();
  }
  protected resetFilters(): void {
    this.action.set('');
    this.actor.set('');
    this.since.set('');
    this.until.set('');
    this.reload();
  }

  protected loadMore(): void {
    if (this.hasMore()) this.load(false);
  }

  /** Filter geändert → Liste verwerfen und vom neuesten Eintrag neu laden. */
  private reload(): void {
    this.entries.set([]);
    this.cursor.set(null);
    this.hasMore.set(false);
    this.load(true);
  }

  private load(reset: boolean): void {
    if (this.loading()) return;
    this.loading.set(true);
    this.loadError.set(false);
    this.api
      .listAuditLog({
        limit: PAGE_SIZE,
        before: reset ? undefined : (this.cursor() ?? undefined),
        action: this.action() || undefined,
        actor: this.actor() || undefined,
        // Tagesgrenzen: since ab 00:00, until bis 23:59:59 (lokal interpretiert).
        since: this.since() ? `${this.since()}T00:00:00` : undefined,
        until: this.until() ? `${this.until()}T23:59:59` : undefined,
      })
      .subscribe({
        next: (page) => {
          this.entries.update((cur) => (reset ? page.items : [...cur, ...page.items]));
          this.cursor.set(page.nextCursor);
          this.hasMore.set(page.hasMore);
          this.loading.set(false);
        },
        error: () => {
          this.loadError.set(true);
          this.loading.set(false);
        },
      });
  }

  // --- Rendering ------------------------------------------------------------
  /** Lokalisierte Aktions-Bezeichnung (Badge + Filter-Optionen). */
  protected actionLabel(action: string): string {
    const key = `admin.audit.action.${action}`;
    const label = this.i18n.translate(key as TranslationKey);
    return label === key ? action : label;
  }

  /** Menschenlesbarer Satz pro Eintrag (Vorlage je Aktionstyp + Fallback). */
  protected message(e: AuditEntry): string {
    const key = KNOWN_ACTIONS.has(e.action)
      ? `admin.audit.msg.${e.action}`
      : 'admin.audit.msg.unknown';
    return this.i18n.translate(key as TranslationKey, {
      actor: this.actorLabel(e),
      action: this.actionLabel(e.action),
      target: this.targetLabel(e),
      targetType: e.targetType ?? '',
      targetId: e.targetId ?? '',
    });
  }

  private actorLabel(e: AuditEntry): string {
    return e.actorName ?? e.actor ?? this.i18n.translate('admin.audit.system');
  }

  private targetLabel(e: AuditEntry): string {
    if (e.targetType && e.targetId) return `${e.targetType}:${e.targetId}`;
    return e.targetType ?? e.targetId ?? '—';
  }

  /** `data`-Inhalt als (key, value)-Paare für die Detail-Chips. */
  protected dataPairs(e: AuditEntry): [string, string][] {
    return Object.entries(e.data ?? {}).map(([k, v]) => [
      k,
      typeof v === 'object' ? JSON.stringify(v) : String(v),
    ]);
  }
}
