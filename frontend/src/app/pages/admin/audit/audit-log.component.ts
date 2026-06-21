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
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  ConfigDiffComponent,
  DatepickerComponent,
  DialogComponent,
  FilterBarComponent,
  FilterFieldComponent,
  IconComponent,
  type IconName,
  SelectComponent,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { AuditActor, AuditEntry, ConfigRevisionDiff } from '../admin.models';

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
  'config_revert',
  'role_change',
  'delegation_grant',
  'delegation_revoke',
  'delegation_use',
  'delegation_substitute_add',
  'delegation_substitute_remove',
  'export',
  'pii_access',
  'pii_deletion',
  'pii_export',
  'anonymization',
  'erasure_requested',
  'erasure_executed',
  'erasure_rejected',
  'principal_erased',
  'retention_anonymize',
  'webhook_config',
  'attachment_quarantine',
  'attachment_delete',
  // Budget-/Geld-Mutationen (#sec-audit) — Spiegel der BUDGET_*-Werte in actions.py.
  'budget_node_create',
  'budget_node_update',
  'budget_node_delete',
  'budget_allocation_set',
  'budget_expense_create',
  'budget_expense_update',
  'budget_expense_delete',
  'budget_transfer_create',
  'budget_invoice_create',
  'budget_invoice_update',
  'budget_invoice_delete',
  'budget_assign',
  'budget_move_fiscal_year',
] as const;

const KNOWN_ACTIONS = new Set<string>(AUDIT_ACTIONS);

/** Aktionstyp → Icon der Feed-Zeile (Kategorie-Glyph wie in der Nextcloud-Aktivität). */
const ACTION_ICONS: Record<string, IconName> = {
  login: 'key',
  status_change: 'repeat',
  vote_cast: 'check',
  config_change: 'gear',
  config_activation: 'gear',
  config_revert: 'repeat',
  role_change: 'roles',
  delegation_grant: 'handshake',
  delegation_revoke: 'handshake',
  delegation_use: 'handshake',
  delegation_substitute_add: 'handshake',
  delegation_substitute_remove: 'handshake',
  export: 'export',
  webhook_config: 'webhook',
  attachment_quarantine: 'paperclip',
  attachment_delete: 'paperclip',
  // Geld-Mutationen: €-Glyph; Kostenstellen-Struktur als Torten-Glyph wie im Budget-Tab.
  budget_node_create: 'chart-pie',
  budget_node_update: 'chart-pie',
  budget_node_delete: 'chart-pie',
  budget_allocation_set: 'chart-pie',
  budget_expense_create: 'euro',
  budget_expense_update: 'euro',
  budget_expense_delete: 'euro',
  budget_transfer_create: 'euro',
  budget_invoice_create: 'euro',
  budget_invoice_update: 'euro',
  budget_invoice_delete: 'euro',
  budget_assign: 'euro',
  budget_move_fiscal_year: 'euro',
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
  // Budget-Ziele → zuständiger Tab: Kostenstellen/Zuteilungen/Umbuchungen ins
  // Budget-Dashboard, Buchungen in die Ausgaben-, Rechnungen in die Rechnungsliste.
  budget: () => ['/budget'],
  budget_allocation: () => ['/budget'],
  budget_transfer: () => ['/budget'],
  budget_expense: () => ['/expenses'],
  invoice: () => ['/invoices'],
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
    ConfigDiffComponent,
    DialogComponent,
    FilterBarComponent,
    FilterFieldComponent,
    DatepickerComponent,
    IconComponent,
    SelectComponent,
  ],
  templateUrl: './audit-log.component.html',
  styleUrl: './audit-log.component.scss',
})
export class AuditLogComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);

  protected readonly entries = signal<AuditEntry[]>([]);
  protected readonly actors = signal<AuditActor[]>([]);
  protected readonly cursor = signal<number | null>(null);
  protected readonly hasMore = signal(false);
  protected readonly loading = signal(false);
  protected readonly loadError = signal(false);
  /** Ausgeklappte Einträge (Detail-Bereich sichtbar). */
  protected readonly open = signal<ReadonlySet<number>>(new Set());

  // --- Config-Diff + Revert (#config-versioning) ----------------------------
  /** ``audit.revert``-Permission (FE-Gate; Backend bleibt autoritativ). Reaktiv, da
   *  der Principal asynchron lädt. */
  protected readonly canRevert = computed(() => this.auth.can('audit.revert'));
  /** Geladene Config-Diffs je ``revisionId`` (``null`` = lädt noch). */
  protected readonly diffs = signal<ReadonlyMap<string, ConfigRevisionDiff | null>>(
    new Map(),
  );
  /** Eintrag, dessen Revert gerade bestätigt wird. */
  protected readonly confirmRevert = signal<AuditEntry | null>(null);
  protected readonly reverting = signal(false);

  // Filter
  protected readonly action = signal('');
  protected readonly actor = signal('');
  protected readonly since = signal('');
  protected readonly until = signal('');

  protected readonly actionOptions = computed<SelectOption[]>(() =>
    AUDIT_ACTIONS.map((a) => ({ value: a, label: this.actionLabel(a) })),
  );
  protected readonly actorOptions = computed<SelectOption[]>(() =>
    this.actors().map((a) => ({ value: a.sub, label: a.name || a.sub })),
  );
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
    if (this.isOpen(id)) {
      const entry = this.entries().find((e) => e.id === id);
      if (entry) this.loadDiff(entry);
    }
  }

  /** ``revisionId`` aus dem ``data``-Payload (nur Config-Changes tragen es). */
  protected revisionId(e: AuditEntry): string | null {
    const v = e.data?.['revisionId'];
    return typeof v === 'string' ? v : null;
  }

  /** Revert anbietbar: Permission vorhanden **und** vom Backend als zurücknehmbar
   *  markiert (Config mit Vorgänger, Statuswechsel, reversible Budget-Mutation). */
  protected isRevertable(e: AuditEntry): boolean {
    return this.canRevert() && e.revertable === true;
  }

  /** Geladener Diff des Eintrags (``null`` = lädt; ``undefined`` = kein Snapshot). */
  protected diffOf(e: AuditEntry): ConfigRevisionDiff | null | undefined {
    const id = this.revisionId(e);
    return id ? this.diffs().get(id) : undefined;
  }

  /** Beim Aufklappen den Config-Diff einmalig nachladen (#2-Diff im Audit-Log). */
  private loadDiff(e: AuditEntry): void {
    const rid = this.revisionId(e);
    if (!rid || this.diffs().has(rid)) return;
    this.diffs.update((m) => new Map(m).set(rid, null));
    this.api.getConfigRevisionDiff(rid).subscribe({
      next: (d) => this.diffs.update((m) => new Map(m).set(rid, d)),
      error: () =>
        this.diffs.update((m) => {
          const next = new Map(m);
          next.delete(rid);
          return next;
        }),
    });
  }

  protected askRevert(e: AuditEntry): void {
    this.confirmRevert.set(e);
  }

  protected doRevert(): void {
    const e = this.confirmRevert();
    if (!e) return;
    this.confirmRevert.set(null);
    this.reverting.set(true);
    this.api.revertAuditEntry(e.id).subscribe({
      next: () => {
        this.reverting.set(false);
        this.toast.success(this.i18n.translate('admin.audit.revert.success'));
        this.reload();
      },
      error: (err: { status?: number; error?: { code?: string } }) => {
        this.reverting.set(false);
        this.toast.error(this.i18n.translate(this.revertErrorKey(err)));
      },
    });
  }

  /** 409-Fehlercode (ProblemDetail) → passende Meldung; sonst generischer Fehler. */
  private revertErrorKey(err: {
    status?: number;
    error?: { code?: string };
  }): TranslationKey {
    if (err?.status !== 409) return 'admin.audit.revert.error';
    switch (err.error?.code) {
      case 'nothing_to_revert':
        return 'admin.audit.revert.nothingToRevert';
      case 'already_reverted':
        return 'admin.audit.revert.alreadyReverted';
      case 'not_revertable':
        return 'admin.audit.revert.notRevertable';
      case 'stale_revert':
      default:
        return 'admin.audit.revert.conflict';
    }
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

  /** Ziel-Typ lokalisiert (gremium → »Gremium« …); unbekannt → roher Key. */
  protected targetTypeLabel(type: string): string {
    const key = `admin.audit.targetType.${type}`;
    const label = this.i18n.translate(key as TranslationKey);
    return label === key ? type : label;
  }

  /** Router-Ziel des Eintrags-Ziels, falls eine Seite dafür existiert. */
  protected targetLink(e: AuditEntry): string[] | null {
    if (!e.targetType || !e.targetId) return null;
    return TARGET_ROUTES[e.targetType]?.(e.targetId) ?? null;
  }

  private actorLabel(e: AuditEntry): string {
    return e.actorName ?? e.actor ?? this.i18n.translate('admin.audit.system');
  }

  /** Akteur im Detail: „<Klarname> · <sub>" wenn aufgelöst, sonst roher sub/System. */
  protected actorDisplay(e: AuditEntry): string {
    if (e.actorName && e.actor) return `${e.actorName} · ${e.actor}`;
    return e.actorName ?? e.actor ?? this.i18n.translate('admin.audit.system');
  }

  /** Ziel im Satz: aufgelöstes Label (Backend) bevorzugt, sonst `type:id`. */
  private targetLabel(e: AuditEntry): string {
    if (e.targetLabel) return `„${e.targetLabel}“`;
    if (e.targetType && e.targetId) return `${e.targetType}:${e.targetId}`;
    return e.targetType ?? e.targetId ?? '—';
  }

  /** `data`-Inhalt als (key, value)-Paare für die Detail-Chips. UUID-Werte mit
   *  bekanntem Klarnamen werden als „<Name> · <uuid>" gerendert (#no-uuids-in-ui),
   *  sonst die rohe UUID. */
  protected dataPairs(e: AuditEntry): [string, string][] {
    const resolved = e.resolvedIds ?? {};
    const fmt = (v: unknown): string => {
      if (typeof v === 'string' && resolved[v]) return `${resolved[v]} · ${v}`;
      return v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v);
    };
    return Object.entries(e.data ?? {}).map(([k, v]) => [k, fmt(v)]);
  }
}
