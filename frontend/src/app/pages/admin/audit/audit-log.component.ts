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
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  DatepickerComponent,
  FilterBarComponent,
  FilterFieldComponent,
  IconComponent,
  type IconName,
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
  'webhook_config',
  'attachment_quarantine',
  'attachment_delete',
] as const;

const KNOWN_ACTIONS = new Set<string>(AUDIT_ACTIONS);

/** Aktionstyp → Icon der Feed-Zeile (Kategorie-Glyph wie in der Nextcloud-Aktivität). */
const ACTION_ICONS: Record<string, IconName> = {
  login: 'key',
  status_change: 'repeat',
  vote_cast: 'check',
  config_change: 'gear',
  config_activation: 'gear',
  role_change: 'roles',
  delegation_grant: 'handshake',
  delegation_revoke: 'handshake',
  delegation_use: 'handshake',
  export: 'export',
  webhook_config: 'webhook',
  attachment_quarantine: 'paperclip',
  attachment_delete: 'paperclip',
};

/** Ziel-Typ → Router-Ziel (Detailseite bzw. zuständige Admin-Liste). */
const TARGET_ROUTES: Record<string, (id: string) => string[]> = {
  application: (id) => ['/applications', id],
  vote: (id) => ['/voting/vote', id],
  gremium: () => ['/admin/gremien'],
  application_type: () => ['/admin/forms'],
  role: () => ['/admin/roles'],
  role_assignment: () => ['/admin/users'],
  principal: () => ['/admin/users'],
  group_mapping: () => ['/admin/users'],
  webhook: () => ['/admin/webhooks'],
  site_config: () => ['/admin/branding'],
};

/** Tagesgruppe des Feeds (lokale Tagesgrenzen). */
interface DayGroup {
  key: string;
  date: Date;
  entries: AuditEntry[];
}

/**
 * Audit-Log-Ansicht (#45, T-23) als Aktivitäts-Feed (#2, Nextcloud-Stil):
 * Einträge nach Tag gruppiert, pro Eintrag ein Kategorie-Icon + ein
 * menschenlesbarer Satz (`admin.audit.msg.*`, Ziel als Klarname/Link) und
 * eine Uhrzeit; Details (Ziel-Id, Daten, Hash) ausklappbar.
 *
 * - **Lazy infinite scroll**: Keyset-Paging über `before`-Cursor (id); ein
 *   `IntersectionObserver`-Sentinel lädt nach, „Mehr laden" als Fallback.
 * - **Filter**: Aktionstyp, Akteur (aufgelöster Klarname), Zeitfenster.
 */
@Component({
  selector: 'app-audit-log',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    BadgeComponent,
    FilterBarComponent,
    FilterFieldComponent,
    DatepickerComponent,
    IconComponent,
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

      @if (!groups().length && !loading()) {
        <p class="audit__status">{{ 'admin.audit.empty' | t }}</p>
      }

      @for (g of groups(); track g.key) {
        <h2 class="audit__day">{{ dayLabel(g) }}</h2>
        <ul class="audit__feed">
          @for (e of g.entries; track e.id) {
            <li class="audit__item">
              <button
                type="button"
                class="audit__row"
                (click)="toggle(e.id)"
                [attr.aria-expanded]="isOpen(e.id)"
              >
                <span class="audit__icon" aria-hidden="true">
                  <app-icon [name]="icon(e.action)" [size]="14" />
                </span>
                <span class="audit__msg">{{ message(e) }}</span>
                <time class="audit__time" [attr.datetime]="e.at">{{ e.at | ldate: 'time' }}</time>
                <app-icon
                  class="audit__chev"
                  [name]="isOpen(e.id) ? 'chevron-up' : 'chevron-down'"
                  [size]="12"
                />
              </button>
              @if (isOpen(e.id)) {
                <div class="audit__details">
                  <div class="audit__chips">
                    <app-badge variant="neutral">{{ actionLabel(e.action) }}</app-badge>
                    @if (e.targetType && e.targetId) {
                      <span class="audit__chip audit__mono">{{ e.targetType }}:{{ e.targetId }}</span>
                    }
                    @if (e.actor) {
                      <span class="audit__chip audit__mono">{{ e.actor }}</span>
                    }
                    @for (p of dataPairs(e); track p[0]) {
                      <span class="audit__chip audit__mono">{{ p[0] }}: {{ p[1] }}</span>
                    }
                  </div>
                  @if (targetLink(e); as link) {
                    <a class="audit__target" [routerLink]="link">{{ 'admin.audit.openTarget' | t }}</a>
                  }
                </div>
              }
            </li>
          }
        </ul>
      }

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
      .audit__day {
        margin: var(--space-3) 0 var(--space-2);
        font-size: var(--fs-sm);
        font-weight: 600;
        color: var(--color-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }
      .audit__feed {
        list-style: none;
        margin: 0;
        padding: 0;
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface);
        overflow: hidden;
      }
      .audit__item + .audit__item {
        border-top: var(--border-width) solid var(--color-border);
      }
      .audit__row {
        display: grid;
        grid-template-columns: auto 1fr auto auto;
        align-items: center;
        gap: var(--space-3);
        width: 100%;
        padding: var(--space-2) var(--space-3);
        border: 0;
        background: transparent;
        color: inherit;
        font: inherit;
        text-align: left;
        cursor: pointer;
      }
      .audit__row:hover {
        background: var(--color-surface-sunken);
      }
      .audit__icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.75rem;
        height: 1.75rem;
        border-radius: 50%;
        background: var(--color-surface-sunken);
        color: var(--color-text-muted);
        flex-shrink: 0;
      }
      .audit__msg {
        min-width: 0;
        overflow-wrap: anywhere;
      }
      .audit__time {
        color: var(--color-text-muted);
        font-size: var(--fs-xs);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
      }
      .audit__chev {
        color: var(--color-text-muted);
      }
      .audit__details {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        padding: 0 var(--space-3) var(--space-3) calc(1.75rem + 2 * var(--space-3));
      }
      .audit__chips {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--space-1);
      }
      .audit__chip {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
        background: var(--color-surface-sunken);
        border-radius: var(--radius-sm);
        padding: 1px var(--space-2);
        overflow-wrap: anywhere;
      }
      .audit__mono {
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-xs);
      }
      .audit__target {
        font-size: var(--fs-sm);
        align-self: flex-start;
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
          grid-template-columns: auto 1fr auto;
        }
        .audit__chev {
          display: none;
        }
        .audit__details {
          padding-left: var(--space-3);
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
  /** Ausgeklappte Einträge (Detail-Bereich sichtbar). */
  protected readonly open = signal<ReadonlySet<number>>(new Set());

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

  /** Feed-Gruppen: Einträge nach lokalem Tag (neueste zuerst, wie geliefert). */
  protected readonly groups = computed<DayGroup[]>(() => {
    const out: DayGroup[] = [];
    for (const e of this.entries()) {
      const date = new Date(e.at);
      const key = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
      const last = out[out.length - 1];
      if (last && last.key === key) last.entries.push(e);
      else out.push({ key, date, entries: [e] });
    }
    return out;
  });

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

  protected isOpen(id: number): boolean {
    return this.open().has(id);
  }

  protected toggle(id: number): void {
    this.open.update((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  /** Filter geändert → Liste verwerfen und vom neuesten Eintrag neu laden. */
  private reload(): void {
    this.entries.set([]);
    this.cursor.set(null);
    this.hasMore.set(false);
    this.open.set(new Set());
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
  /** Tages-Überschrift: Heute/Gestern, sonst lokalisiertes Datum. */
  protected dayLabel(g: DayGroup): string {
    const today = new Date();
    const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    if (this.sameDay(g.date, today)) return this.i18n.translate('admin.audit.today');
    if (this.sameDay(g.date, yesterday)) return this.i18n.translate('admin.audit.yesterday');
    const locale = this.i18n.locale() === 'en' ? 'en-US' : 'de-DE';
    return new Intl.DateTimeFormat(locale, { dateStyle: 'full' }).format(g.date);
  }

  private sameDay(a: Date, b: Date): boolean {
    return (
      a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() &&
      a.getDate() === b.getDate()
    );
  }

  /** Kategorie-Icon der Feed-Zeile (unbekannte Aktion → Audit-Glyph). */
  protected icon(action: string): IconName {
    return ACTION_ICONS[action] ?? 'audit';
  }

  /** Lokalisierte Aktions-Bezeichnung (Detail-Badge + Filter-Optionen). */
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

  /** Router-Ziel des Eintrags-Ziels, falls eine Seite dafür existiert. */
  protected targetLink(e: AuditEntry): string[] | null {
    if (!e.targetType || !e.targetId) return null;
    return TARGET_ROUTES[e.targetType]?.(e.targetId) ?? null;
  }

  private actorLabel(e: AuditEntry): string {
    return e.actorName ?? e.actor ?? this.i18n.translate('admin.audit.system');
  }

  /** Ziel im Satz: aufgelöstes Label (Backend) bevorzugt, sonst `type:id`. */
  private targetLabel(e: AuditEntry): string {
    if (e.targetLabel) return `„${e.targetLabel}“`;
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
