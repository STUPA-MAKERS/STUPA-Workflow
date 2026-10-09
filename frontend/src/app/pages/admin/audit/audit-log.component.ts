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
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  FilterSelectComponent,
  type FilterSelectOption,
  PageHeaderComponent,
  RangeChipComponent,
  type RangeValue,
  SkeletonComponent,
} from '@shared/ui';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import { checkedAt, formatCount, triggerLabel } from '../admin-health/admin-health.util';
import type {
  AuditActor,
  AuditEntry,
  AuditVerification,
  ConfigRevisionDiff,
} from '../admin.models';

const PAGE_SIZE = 50;

/**
 * A UUID target id. Such an id says nothing to a reader, so the row leaves it out
 * (`[[no-uuids-in-ui]]`). A readable id — `global`, `1`, an export file name — stays.
 */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Audit action types. The list mirrors `AuditAction` in
 * `backend/app/modules/audit/actions.py`, and a spec compares the two. It fills the action
 * filter. Each action has a label `admin.audit.action.<key>`. Without a label, the view
 * shows the raw action key.
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
  'pii_export',
  'anonymization',
  'erasure_requested',
  'erasure_executed',
  'erasure_rejected',
  'principal_erased',
  // Account merge: an old principal merged into a new one.
  'principal_merge',
  'principal_access_revoke',
  'retention_anonymize',
  'webhook_config',
  // attachment_upload (F12) covers the application upload and the draft upload of the
  // wizard (Z4).
  'attachment_upload',
  'attachment_quarantine',
  'attachment_delete',
  // Content mutations that leave a trace outside the flow: application data, comments,
  // protocols, votes. application_create (F12) and guest_application_discard (Z1) mark the
  // start and the discard of an application.
  'application_create',
  // #11: an application captured on behalf of an applicant.
  'application_create_on_behalf',
  'guest_application_discard',
  'application_update',
  // Archive, public share link and delete of an application.
  'application_archive',
  'application_unarchive',
  'application_share',
  'application_share_revoke',
  // F1: the decision on an application (approval with deviations).
  'application_decision',
  'application_delete',
  'comment_update',
  'comment_delete',
  'protocol_delete',
  'protocol_finalize',
  // A protocol held back from the public protocol page, or published again.
  'protocol_publication',
  'vote_delete',
  // Vote lifecycle (F12). vote_branch_blocked marks an application that a person must move.
  'vote_open',
  'vote_close',
  'vote_cancel',
  'vote_branch_blocked',
  'vote_lot_drawn',
  // Meeting and agenda (F12). They mirror the MEETING_* and AGENDA_* values in actions.py.
  'meeting_create',
  'meeting_update',
  'meeting_delete',
  'agenda_item_add',
  'agenda_item_update',
  'agenda_item_remove',
  'agenda_reorder',
  // Attendance set or reset by the meeting lead (F12). They mirror ATTENDANCE_* in actions.py.
  'attendance_set',
  'attendance_reset',
  'protokollant_handover',
  // Public meeting with QR code (#17): only the ids of the guests, never their names.
  'meeting_public_join_changed',
  'meeting_join_code_rotated',
  'guest_admitted',
  'guest_rejected',
  'guest_removed',
  'guest_renamed',
  'guest_admit_all',
  // Budget and money mutations. They mirror the BUDGET_* values in actions.py.
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
  'budget_fiscal_year_delete',
  // Whole-platform backup and restore. They mirror the BACKUP_* values in actions.py.
  'backup_create',
  'backup_delete',
  'backup_export',
  'backup_import',
  'backup_restore',
] as const;

/** Target type to router target: the detail page or the admin list that owns the target. */
const TARGET_ROUTES: Record<string, (id: string) => string[]> = {
  application: (id) => ['/applications', id],
  vote: (id) => ['/voting', id],
  meeting: (id) => ['/meetings', id],
  gremium: () => ['/admin/gremien'],
  application_type: () => ['/admin/forms'],
  role: () => ['/admin/roles'],
  role_assignment: () => ['/admin/users'],
  principal: () => ['/admin/users'],
  group_mapping: () => ['/admin/users'],
  webhook: () => ['/admin/webhooks'],
  site_config: () => ['/admin/branding'],
  guest_application_settings: () => ['/admin/deadlines'],
  // Each budget target goes to the tab that owns it. Cost centers, allocations and transfers
  // go to the budget dashboard. Bookings go to the expenses list. Invoices go to the invoice
  // list.
  budget: () => ['/budget'],
  budget_allocation: () => ['/budget'],
  budget_transfer: () => ['/budget'],
  budget_expense: () => ['/expenses'],
  invoice: () => ['/invoices'],
  fiscal_year: () => ['/budget'],
  // The config pages of the admin area. A form target carries the id of its type.
  flow: () => ['/admin/flow'],
  form: (id) => ['/admin/forms', id],
  cd_variant: () => ['/admin/cd-variants'],
  notification_settings: () => ['/admin/notifications'],
  // The security and data pages.
  backup: () => ['/admin/backups'],
  erasure_request: () => ['/admin/privacy'],
  oauth_token: () => ['/admin/oauth-grants'],
  meeting_delegation: () => ['/admin/delegations'],
  delegation_substitute: () => ['/admin/delegations'],
};


/**
 * Data keys with a label of their own. `version` is the revision of a config change or
 * the data version of an application.
 */
const DATA_LABELS: Readonly<Record<string, TranslationKey>> = {
  version: 'admin.audit.data.version',
};

/** Data keys that the details show in the target line, not as a data row. */
const TARGET_KEYS = new Set(['revisionId']);

/** One data row of the details. A known key has a label; any other key shows as code. */
export interface AuditDataRow {
  key: string;
  label: string;
  value: string;
  known: boolean;
}

/** One changed field of a config diff: the old value (`-`) and the new value (`+`). */
export interface AuditDiffLine {
  key: string;
  before: string | null;
  after: string | null;
}

/** A diff value as code: a string in quotes, any other value as JSON. */
function diffValue(v: unknown): string {
  return v === undefined ? 'null' : JSON.stringify(v);
}

/** The state of the chain check at the top of the page. */
type VerifyState =
  | { status: 'loading' }
  | { status: 'stored'; check: AuditVerification }
  | { status: 'never' }
  | { status: 'error' };

/**
 * The audit log (board Admin-Audit-Log).
 *
 * - The chain check at the top: "Audit-Kette intakt" or "unterbrochen" as coloured text,
 *   when the newest stored check ran, its trigger and the number of entries
 *   (`GET /admin/audit/verify/latest`). "Jetzt prüfen" (`audit.verify`) checks the chain
 *   now and stores the result (`POST /admin/audit/verify`; 409 while a check runs, 429
 *   inside the cooldown).
 * - Filters: Aktion, Akteur (app menus), Von and Bis (dates).
 * - One row per entry: time, action, actor, target. A row opens its details: action,
 *   target (with the revision of a config change), actor, the data, the config diff of
 *   a config change as one compact code block (`-` old, `+` new), "Ziel öffnen" and
 *   "Zurücknehmen" (`audit.revert`, only where the server marks the entry revertable).
 * - Keyset paging over the `before` cursor: a sentinel loads more on scroll, "Mehr
 *   laden" is the fallback.
 */
@Component({
  selector: 'app-audit-log',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    FilterSelectComponent,
    PageHeaderComponent,
    SkeletonComponent,
    RangeChipComponent,
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
  /** Ids of the expanded entries. Their detail area is visible. */
  protected readonly open = signal<ReadonlySet<number>>(new Set());

  /** The `audit.revert` permission as a front-end gate. The backend stays authoritative. The
   *  value is reactive because the principal loads asynchronously. */
  protected readonly canRevert = computed(() => this.auth.can('audit.revert'));
  /** "Jetzt prüfen" needs `audit.verify`. */
  protected readonly canVerify = computed(() => this.auth.can('audit.verify'));
  /** Loaded config diffs per `revisionId`. A `null` value means the diff still loads. */
  protected readonly diffs = signal<ReadonlyMap<string, ConfigRevisionDiff | null>>(
    new Map(),
  );
  /** The entry whose revert the user confirms now. */
  protected readonly confirmRevert = signal<AuditEntry | null>(null);
  protected readonly reverting = signal(false);

  /** The newest stored chain check. */
  protected readonly verify = signal<VerifyState>({ status: 'loading' });
  protected readonly verifying = signal(false);

  protected readonly action = signal('');
  protected readonly actor = signal('');
  protected readonly since = signal('');
  protected readonly until = signal('');

  protected readonly actionOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('admin.audit.filter.allActions') },
    ...AUDIT_ACTIONS.map((a) => ({ value: a, label: this.actionLabel(a) })),
  ]);
  protected readonly actorOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('admin.audit.filter.allActors') },
    ...this.actors().map((a) => ({ value: a.sub, label: a.name || a.sub })),
  ]);
  /** "Aktion: Alle Aktionen" or "Aktion: <label>". */
  protected readonly actionChip = computed(() =>
    this.chipText('admin.audit.filter.action', this.actionOptions(), this.action()),
  );
  protected readonly actorChip = computed(() =>
    this.chipText('admin.audit.filter.actor', this.actorOptions(), this.actor()),
  );
  /** One per chip: the "Zeitraum" chip counts once, also when both days are set. */
  protected readonly activeFilterCount = computed(
    () =>
      (this.action() ? 1 : 0) +
      (this.actor() ? 1 : 0) +
      (this.since() || this.until() ? 1 : 0),
  );

  /** The title and the line of the chain check. */
  protected readonly verifyView = computed(() => {
    const state = this.verify();
    if (state.status === 'loading') return null;
    if (state.status === 'never') {
      return { kind: 'muted', title: this.i18n.translate('admin.health.audit.never'), sub: '' };
    }
    if (state.status === 'error') {
      return { kind: 'muted', title: this.i18n.translate('admin.health.audit.failed'), sub: '' };
    }
    const check = state.check;
    const at = new Intl.DateTimeFormat(this.i18n.formatLocale(), {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(checkedAt(check)));
    const parts = [
      this.i18n.translate('admin.audit.verify.checkedOn', { when: at }),
      triggerLabel(check.trigger, this.i18n),
      this.i18n.translate('admin.health.entries', { count: formatCount(check.checked, this.i18n) }),
    ];
    if (check.brokenAt != null) {
      parts.unshift(this.i18n.translate('admin.health.audit.brokenAt', { id: check.brokenAt }));
    }
    return check.valid
      ? { kind: 'ok', title: this.i18n.translate('admin.health.audit.ok'), sub: parts.join(' · ') }
      : { kind: 'error', title: this.i18n.translate('admin.health.audit.broken'), sub: parts.join(' · ') };
  });

  private readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  constructor() {
    this.api.listAuditActors().subscribe({
      next: (a) => this.actors.set(a),
      error: () => this.actors.set([]),
    });
    this.api.latestAuditVerification().subscribe({
      next: (check) => this.verify.set(check ? { status: 'stored', check } : { status: 'never' }),
      error: () => this.verify.set({ status: 'error' }),
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

  private chipText(label: TranslationKey, options: FilterSelectOption[], value: string): string {
    const hit = options.find((o) => o.value === value) ?? options[0];
    return `${this.i18n.translate(label)}: ${hit.label}`;
  }

  /** Check the chain now. The server stores the result, so the tiles see it too. */
  protected runVerify(): void {
    if (this.verifying()) return;
    this.verifying.set(true);
    this.api.runAuditVerification().subscribe({
      next: (check) => {
        this.verifying.set(false);
        this.verify.set({ status: 'stored', check });
        this.toast.success(
          this.i18n.translate(check.valid ? 'admin.audit.verify.done' : 'admin.audit.verify.broken'),
        );
      },
      error: (err: { status?: number }) => {
        this.verifying.set(false);
        const key: TranslationKey =
          err?.status === 409
            ? 'admin.audit.verify.running'
            : err?.status === 429
              ? 'admin.audit.verify.cooldown'
              : 'admin.audit.verify.failed';
        this.toast.error(this.i18n.translate(key));
      },
    });
  }

  protected setAction(v: string): void {
    this.action.set(v);
    this.reload();
  }
  protected setActor(v: string): void {
    this.actor.set(v);
    this.reload();
  }
  /** The period chip: both days at once, like the date ranges of the finance pages. */
  protected setRange(v: RangeValue): void {
    this.since.set(v.from);
    this.until.set(v.to);
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

  /** The `revisionId` from the `data` payload. Only config changes carry it. */
  protected revisionId(e: AuditEntry): string | null {
    const v = e.data?.['revisionId'];
    return typeof v === 'string' ? v : null;
  }

  /** Offer the revert when the permission is present and the backend marks the entry
   *  revertable. The backend marks a config with a predecessor, a status change and a
   *  reversible budget mutation. */
  protected isRevertable(e: AuditEntry): boolean {
    return this.canRevert() && e.revertable === true;
  }

  /** The loaded diff of the entry. `null` means it loads. `undefined` means no snapshot. */
  protected diffOf(e: AuditEntry): ConfigRevisionDiff | null | undefined {
    const id = this.revisionId(e);
    return id ? this.diffs().get(id) : undefined;
  }

  /** Load the config diff one time, when the user expands the entry. */
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

  /** Map the 409 error code of the ProblemDetail to a message. Any other error gets the
   *  generic message. */
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

  /** After a filter change, drop the list and load again from the newest entry. */
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
        // Day boundaries: since starts at 00:00 and until ends at 23:59:59, in local
        // time, sent as an aware UTC time.
        since: this.since() ? localDayBound(this.since(), false) : undefined,
        until: this.until() ? localDayBound(this.until(), true) : undefined,
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

  /** Localized action label for the rows, the details and the filter options. */
  protected actionLabel(action: string): string {
    const key = `admin.audit.action.${action}`;
    const label = this.i18n.translate(key as TranslationKey);
    return label === key ? action : label;
  }

  /** Localized target type. An unknown type gives the raw key back. */
  protected targetTypeLabel(type: string): string {
    const key = `admin.audit.targetType.${type}`;
    const label = this.i18n.translate(key as TranslationKey);
    return label === key ? type : label;
  }

  /**
   * The target in a row: "Antrag · Zuschuss Sommerfest". The label the backend resolved
   * wins; without it a readable id stands after the type. A UUID stays out of the row,
   * because it tells the reader nothing; the details still show it.
   */
  protected targetText(e: AuditEntry): string {
    const type = e.targetType ? this.targetTypeLabel(e.targetType) : null;
    const id = e.targetId && !UUID_RE.test(e.targetId) ? e.targetId : null;
    const name = e.targetLabel ?? id;
    return [type, name].filter((x): x is string => !!x).join(' · ') || '—';
  }

  /** Router target for the target of the entry, if a page exists for it. */
  protected targetLink(e: AuditEntry): string[] | null {
    if (!e.targetType || !e.targetId) return null;
    return TARGET_ROUTES[e.targetType]?.(e.targetId) ?? null;
  }

  /** The actor of a row: the clear name, the raw sub, or "System". */
  protected actorLabel(e: AuditEntry): string {
    return e.actorName ?? e.actor ?? this.i18n.translate('admin.audit.system');
  }

  /** Actor in the details: "<clear name> · <sub>" when resolved, else the raw sub or system. */
  protected actorDisplay(e: AuditEntry): string {
    if (e.actorName && e.actor) return `${e.actorName} · ${e.actor}`;
    return e.actorName ?? e.actor ?? this.i18n.translate('admin.audit.system');
  }

  /**
   * The `data` content as rows for the details. A known key gets its label; the
   * `revisionId` shows in the target line instead. A UUID value with a known clear name
   * reads as "<name> · <uuid>", else as the raw UUID.
   */
  protected dataRows(e: AuditEntry): AuditDataRow[] {
    const resolved = e.resolvedIds ?? {};
    const fmt = (v: unknown): string => {
      if (typeof v === 'string' && resolved[v]) return `${resolved[v]} · ${v}`;
      return v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v);
    };
    return Object.entries(e.data ?? {})
      .filter(([k]) => !TARGET_KEYS.has(k))
      .map(([key, v]) => {
        const labelKey = DATA_LABELS[key];
        return labelKey
          ? { key, label: this.i18n.translate(labelKey), value: fmt(v), known: true }
          : { key, label: key, value: fmt(v), known: false };
      });
  }

  /** The changed fields of a config diff, in the order changed, added, removed. */
  protected diffLines(d: ConfigRevisionDiff): AuditDiffLine[] {
    const diff = d.diff;
    if (!diff) return [];
    return [
      ...diff.changed.map((c) => ({ key: c.key, before: diffValue(c.old), after: diffValue(c.new) })),
      ...diff.added.map((a) => ({ key: a.key, before: null, after: diffValue(a.value) })),
      ...diff.removed.map((r) => ({ key: r.key, before: diffValue(r.value), after: null })),
    ];
  }
}

/**
 * The start (00:00:00) or the end (23:59:59.999) of a local day as a UTC time, for
 * example `2026-05-31T22:00:00.000Z` for the start of 1 June in Berlin summer time.
 *
 * The server takes only aware times. A UTC time with `Z` is aware and has no `+` sign:
 * Angular sends a `+` in a query parameter as it is, and the server reads it as a space.
 */
export function localDayBound(day: string, end: boolean): string {
  const [y, m, d] = day.split('-').map(Number);
  const date = end ? new Date(y, m - 1, d, 23, 59, 59, 999) : new Date(y, m - 1, d, 0, 0, 0, 0);
  return date.toISOString();
}
