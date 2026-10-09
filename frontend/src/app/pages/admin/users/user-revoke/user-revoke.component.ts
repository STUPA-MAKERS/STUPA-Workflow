import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Subscription } from 'rxjs';
import type { I18nMap } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { AvatarComponent, NoteComponent, SkeletonComponent } from '@shared/ui';
import {
  ButtonComponent,
  CheckboxComponent,
  DialogComponent,
  IconComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import type {
  AdminPrincipal,
  RevokeAssignment,
  RevokeDelegation,
  RevokeGremium,
  RevokeGlobalRole,
  RevokePoolEntry,
  RevokePreview,
  RevokeResult,
} from '../../admin.models';
import {
  allEntries,
  gremiumEntry,
  roleEntry,
  selectionIds,
  sharedGroups,
  toggleEntry,
  type RevokeEntry,
} from './revoke-selection';

/** One line under an entry: what the person has there and what the revoke does with it. */
export interface RevokeLine {
  text: string;
  detail: string;
  /** A tie that the revoke keeps (a delegation of a live meeting). */
  kept?: boolean;
}

/**
 * The refusals of the server with their own message. Every other error gives the generic
 * "Rechte entziehen fehlgeschlagen.".
 */
export const REVOKE_ERROR_CODES = [
  'revoke_own_account',
  'principal_merged',
  'revoke_incomplete',
  'revoke_unknown_target',
  'revoke_empty',
] as const;
export type RevokeErrorCode = (typeof REVOKE_ERROR_CODES)[number];

function isRevokeErrorCode(code: string | undefined): code is RevokeErrorCode {
  return (REVOKE_ERROR_CODES as readonly string[]).includes(code ?? '');
}

/** The codes after which the selection is stale: the dialog loads the preview again. */
const RELOAD_CODES: ReadonlySet<string> = new Set(['revoke_incomplete', 'revoke_unknown_target']);

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * "Rechte entziehen" (Verwaltung → Benutzer, F3): take the Gremien and the global roles
 * away from a person whom the SSO removed from groups and who no longer logs in.
 *
 * The person header with the last login; "Gremien (n)" with one checkbox per Gremium and
 * everything the person has there below it (membership and gremium role with their SSO
 * groups, manual roles, pool entries, delegations, open votes); "Globale Rollen (n)"; a
 * note on the effects; the switch "Konto zusätzlich deaktivieren"; the danger button that
 * names the count. An SSO group that leads to several entries ties them together: checking
 * one checks all, and a hint says why. All entries start checked.
 *
 * A dialog on a desktop, a bottom sheet on a phone (`app-dialog` does both). The server
 * decides; the dialog only shows its answers. `revoked` fires after a successful revoke,
 * `closed` when the dialog closes.
 */
@Component({
  selector: 'app-user-revoke',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    AvatarComponent,
    NoteComponent,
    SkeletonComponent,
    ButtonComponent,
    CheckboxComponent,
    DialogComponent,
    IconComponent,
    SwitchComponent,
  ],
  templateUrl: './user-revoke.component.html',
  styleUrl: './user-revoke.component.scss',
})
export class UserRevokeComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly datePipe = new LocalizedDatePipe();

  /** The person. The dialog is open while it is set. */
  readonly source = input<AdminPrincipal | null>(null);
  readonly closed = output<void>();
  readonly revoked = output<RevokeResult>();

  protected readonly preview = signal<RevokePreview | null>(null);
  protected readonly loading = signal(false);
  protected readonly failed = signal(false);
  protected readonly selected = signal<ReadonlySet<RevokeEntry>>(new Set());
  protected readonly deactivate = signal(false);
  protected readonly submitting = signal(false);

  protected readonly gremiumCount = computed(
    () => [...this.selected()].filter((e) => e.startsWith('g:')).length,
  );
  protected readonly roleCount = computed(
    () => [...this.selected()].filter((e) => e.startsWith('r:')).length,
  );
  protected readonly allSelected = computed(() => {
    const p = this.preview();
    return !!p && allEntries(p).every((e) => this.selected().has(e));
  });
  protected readonly empty = computed(() => {
    const p = this.preview();
    return !!p && !p.gremien.length && !p.globalRoles.length;
  });
  protected readonly canSubmit = computed(() => {
    const p = this.preview();
    if (!p || p.isSelf || this.submitting()) return false;
    return this.selected().size > 0 || this.deactivate();
  });

  /** The danger button names what it takes away: "2 Gremien und 1 Rolle entziehen". */
  protected readonly confirmLabel = computed(() => {
    const g = this.gremiumCount();
    const r = this.roleCount();
    const t = (key: TranslationKey, params?: Record<string, string | number>) =>
      this.i18n.translate(key, params);
    const gremien =
      g === 1 ? t('admin.users.revoke.count.gremium') : t('admin.users.revoke.count.gremien', { n: g });
    const roles = r === 1 ? t('admin.users.revoke.count.role') : t('admin.users.revoke.count.roles', { n: r });
    if (g && r) return t('admin.users.revoke.confirm.both', { gremien, roles });
    if (g || r) return t('admin.users.revoke.confirm.one', { what: g ? gremien : roles });
    if (this.deactivate()) return t('admin.users.revoke.confirm.deactivate');
    return t('admin.users.revoke.confirm.none');
  });

  private sub?: Subscription;

  constructor() {
    // A new person starts the dialog again.
    effect(() => {
      const src = this.source();
      untracked(() => this.reset(src));
    });
  }

  private reset(src: AdminPrincipal | null): void {
    this.sub?.unsubscribe();
    this.preview.set(null);
    this.selected.set(new Set());
    this.deactivate.set(false);
    this.submitting.set(false);
    this.failed.set(false);
    if (src) this.load(src.id);
  }

  private load(id: string): void {
    this.sub?.unsubscribe();
    this.loading.set(true);
    this.failed.set(false);
    this.sub = this.api.previewPrincipalRevoke(id).subscribe({
      next: (p) => {
        this.preview.set(p);
        // Everything starts checked: the dialog is for people who lost their groups.
        this.selected.set(new Set(allEntries(p)));
        this.loading.set(false);
      },
      error: () => {
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }

  protected retry(): void {
    const src = this.source();
    if (src) this.load(src.id);
  }

  protected name(p: { displayName?: string | null; email?: string | null } | null): string {
    return p?.displayName || p?.email || this.i18n.translate('admin.users.merge.unnamed');
  }

  /** "vor 8 Monaten", "vor 12 Tagen", "heute". */
  protected age(iso: string, now = Date.now()): string {
    const days = Math.max(0, Math.floor((now - new Date(iso).getTime()) / DAY_MS));
    if (days === 0) return this.i18n.translate('admin.users.revoke.age.today');
    if (days < 60) {
      return days === 1
        ? this.i18n.translate('admin.users.revoke.age.day')
        : this.i18n.translate('admin.users.revoke.age.days', { n: days });
    }
    return this.i18n.translate('admin.users.revoke.age.months', { n: Math.floor(days / 30.44) });
  }

  protected label(map: I18nMap, key: string): string {
    return map[this.i18n.locale()] || map['de'] || key;
  }

  protected gEntry(g: RevokeGremium): RevokeEntry {
    return gremiumEntry(g.gremiumId);
  }

  protected rEntry(r: RevokeGlobalRole): RevokeEntry {
    return roleEntry(r.roleId);
  }

  protected isOn(entry: RevokeEntry): boolean {
    return this.selected().has(entry);
  }

  protected toggle(entry: RevokeEntry, on: boolean): void {
    const p = this.preview();
    if (!p) return;
    this.selected.set(toggleEntry(p, this.selected(), entry, on));
  }

  protected toggleAll(): void {
    const p = this.preview();
    if (!p) return;
    this.selected.set(this.allSelected() ? new Set() : new Set(allEntries(p)));
  }

  /** "SSO-Gruppe x gilt auch für Y: wird mit ausgewählt." per shared group of the entry. */
  protected sharedHints(entry: RevokeEntry): string[] {
    const p = this.preview();
    if (!p) return [];
    return sharedGroups(p, entry).map(({ group, others }) =>
      this.i18n.translate('admin.users.revoke.shared', {
        group,
        others: others.map((o) => this.entryName(p, o)).join(', '),
      }),
    );
  }

  private entryName(p: RevokePreview, entry: RevokeEntry): string {
    const id = entry.slice(2);
    if (entry.startsWith('g:')) return p.gremien.find((g) => g.gremiumId === id)?.name ?? id;
    const role = p.globalRoles.find((r) => r.roleId === id);
    return role ? this.label(role.roleLabel, role.roleKey) : id;
  }

  private groupsText(groups: readonly string[]): string {
    return this.i18n.translate(
      groups.length === 1 ? 'admin.users.revoke.fromGroup' : 'admin.users.revoke.fromGroups',
      { groups: groups.join(', ') },
    );
  }

  private date(iso: string | null): string {
    return iso ? this.datePipe.transform(iso, 'mediumDate') : '';
  }

  private assignmentLine(a: RevokeAssignment): RevokeLine {
    const role = this.label(a.roleLabel, a.roleKey);
    let detail: string;
    if (a.grantedBy === 'bootstrap') detail = this.i18n.translate('admin.users.revoke.bootstrap');
    else if (a.validFrom) {
      detail = this.i18n.translate('admin.users.revoke.grantedOn', {
        name: a.grantedBy ?? '—',
        date: this.date(a.validFrom),
      });
    } else detail = this.i18n.translate('admin.users.revoke.grantedBy', { name: a.grantedBy ?? '—' });
    return { text: this.i18n.translate('admin.users.revoke.assignment', { role }), detail };
  }

  private poolLine(e: RevokePoolEntry): RevokeLine {
    const unnamed = this.i18n.translate('admin.users.merge.unnamed');
    const text = !e.asSubstitute
      ? this.i18n.translate('admin.users.revoke.poolMember', { name: e.substituteName ?? unnamed })
      : e.gremiumWide
        ? this.i18n.translate('admin.users.revoke.poolWide')
        : this.i18n.translate('admin.users.revoke.poolFor', { name: e.memberName ?? unnamed });
    return { text, detail: this.i18n.translate('admin.users.revoke.poolDeleted') };
  }

  private delegationLine(d: RevokeDelegation, live: boolean): RevokeLine {
    const meeting = d.meetingDate ? `${d.meetingTitle} (${this.date(d.meetingDate)})` : d.meetingTitle;
    const params = { meeting, name: d.otherName ?? this.i18n.translate('admin.users.merge.unnamed') };
    const key: TranslationKey = live
      ? d.asDelegator
        ? 'admin.users.revoke.liveDelegator'
        : 'admin.users.revoke.liveDelegate'
      : d.asDelegator
        ? 'admin.users.revoke.plannedDelegator'
        : 'admin.users.revoke.plannedDelegate';
    return {
      text: this.i18n.translate(key, params),
      detail: this.i18n.translate(live ? 'admin.users.revoke.liveKept' : 'admin.users.revoke.plannedRevoked'),
      kept: live,
    };
  }

  /** Everything the person has in one Gremium, as lines under its checkbox. */
  protected gremiumLines(g: RevokeGremium): RevokeLine[] {
    const lines: RevokeLine[] = [];
    if (g.membership) {
      lines.push({
        text: this.i18n.translate('admin.users.revoke.membership', {
          role: this.label(g.membership.roleLabel, g.membership.roleKey),
        }),
        detail: g.membership.groups.length ? this.groupsText(g.membership.groups) : '',
      });
    }
    const extra = g.groups.filter((x) => !g.membership?.groups.includes(x));
    if (extra.length) {
      lines.push({
        text: this.i18n.translate('admin.users.revoke.groupsOnly', { groups: extra.join(', ') }),
        detail: this.i18n.translate('admin.users.revoke.groupsRemoved'),
      });
    }
    lines.push(...g.assignments.map((a) => this.assignmentLine(a)));
    lines.push(...g.poolEntries.map((e) => this.poolLine(e)));
    lines.push(...g.plannedDelegations.map((d) => this.delegationLine(d, false)));
    lines.push(...g.liveDelegations.map((d) => this.delegationLine(d, true)));
    if (g.openTasks) {
      lines.push({
        text:
          g.openTasks === 1
            ? this.i18n.translate('admin.users.revoke.openTask')
            : this.i18n.translate('admin.users.revoke.openTasks', { n: g.openTasks }),
        detail: this.i18n.translate('admin.users.revoke.openTasksDetail'),
      });
    }
    return lines;
  }

  /** The origin of one global role: its SSO groups and its manual assignments. */
  protected roleLines(r: RevokeGlobalRole): RevokeLine[] {
    const lines: RevokeLine[] = [];
    if (r.groups.length) {
      lines.push({ text: this.groupsText(r.groups), detail: this.i18n.translate('admin.users.revoke.groupsRemoved') });
    }
    lines.push(...r.assignments.map((a) => this.assignmentLine(a)));
    return lines;
  }

  protected submit(): void {
    const p = this.preview();
    if (!p || !this.canSubmit()) return;
    this.submitting.set(true);
    const ids = selectionIds(this.selected());
    this.api
      .revokePrincipal(p.principal.id, { ...ids, deactivate: this.deactivate() })
      .subscribe({
        next: (res) => {
          this.submitting.set(false);
          this.toast.success(this.i18n.translate('admin.users.revoke.done'));
          this.revoked.emit(res);
          this.close();
        },
        error: (err: { error?: { code?: string } }) => {
          this.submitting.set(false);
          const code = err?.error?.code;
          if (code && RELOAD_CODES.has(code)) this.load(p.principal.id);
          this.toast.error(
            this.i18n.translate(
              isRevokeErrorCode(code) ? `admin.users.revoke.error.${code}` : 'admin.users.revoke.failed',
            ),
          );
        },
      });
  }

  protected close(): void {
    this.sub?.unsubscribe();
    this.closed.emit();
  }
}
