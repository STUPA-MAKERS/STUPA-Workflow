import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  EmptyStateComponent,
  NoteComponent,
  PageHeaderComponent,
  SkeletonComponent,
} from '@shared/ui';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { CdVariantOption, Gremium } from '../admin.models';
import { GremiumRoleMatrixComponent } from '../gremium-roles/gremium-role-matrix.component';
import { GremiumDialogComponent } from './gremium-dialog/gremium-dialog.component';

/** One setting of a gremium in the read-out of an open row. */
interface Setting {
  label: string;
  value: string;
  /** The value is a list of e-mail addresses: it wraps and never gets cut. */
  copyable?: boolean;
}

/**
 * Gremien administration (`/admin/gremien`, boards Verwaltung-Gremium-Dialog and
 * Verwaltung-Gremiumrolle-Dialog).
 *
 * One row per gremium: name, slug, "n Mitglieder · n Rollen", the link to the members,
 * edit, delete and the toggle. An open row shows the settings (gaps N38) and the role
 * matrix of the gremium (`app-gremium-role-matrix`); the first row starts open. The
 * memberships come from the OIDC groups, so this page has no member editing. The dialog
 * `app-gremium-dialog` creates and edits a gremium.
 */
@Component({
  selector: 'app-admin-gremien',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    EmptyStateComponent,
    NoteComponent,
    PageHeaderComponent,
    SkeletonComponent,
    GremiumDialogComponent,
    GremiumRoleMatrixComponent,
  ],
  templateUrl: './gremien.component.html',
  styleUrl: './gremien.component.scss',
})
export class AdminGremienComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly gremien = signal<Gremium[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal(false);
  /** CD variants from `GET /cd-variants`: the dropdown source and the read-out names. */
  readonly cdVariants = signal<CdVariantOption[]>([]);
  /** The ids of the open rows. */
  protected readonly expanded = signal<ReadonlySet<string>>(new Set());
  /** The extra protocol recipients of the open rows, by gremium id. */
  private readonly recipients = signal<ReadonlyMap<string, string[] | null>>(new Map());

  /** The dialog: `undefined` = closed, `null` = a new gremium, else the gremium to edit. */
  protected readonly dialogGremium = signal<Gremium | null | undefined>(undefined);
  /** The last gremium of the dialog. It stays while the dialog closes. */
  protected readonly lastDialogGremium = signal<Gremium | null>(null);
  readonly confirmDelete = signal<Gremium | null>(null);
  readonly deleting = signal(false);

  /** The note links to the group mappings only with that permission. */
  protected readonly canMappings = computed(() => this.auth.can('admin.group_mappings'));

  constructor() {
    this.reload(true);
    this.api.listCdVariantOptions().subscribe({
      next: (v) => this.cdVariants.set(v),
      error: () => this.cdVariants.set([]),
    });
  }

  protected isOpen(g: Gremium): boolean {
    return this.expanded().has(g.id);
  }

  protected toggle(g: Gremium): void {
    const next = new Set(this.expanded());
    if (next.has(g.id)) {
      next.delete(g.id);
    } else {
      next.add(g.id);
      this.loadRecipients(g.id);
    }
    this.expanded.set(next);
  }

  private loadRecipients(id: Uuid): void {
    if (this.recipients().has(id)) return;
    this.api.getGremiumMailRecipients(id).subscribe({
      next: ({ recipients }) => this.setRecipients(id, recipients),
      error: () => this.setRecipients(id, null),
    });
  }

  private setRecipients(id: string, list: string[] | null): void {
    this.recipients.update((m) => new Map(m).set(id, list));
  }

  /** "n Mitglieder · n Rollen" of a row, or `null` without the counts. */
  protected counts(g: Gremium): string | null {
    if (g.memberCount === undefined || g.roleCount === undefined) return null;
    const members = this.i18n.translate(
      g.memberCount === 1 ? 'admin.home.memberCountOne' : 'admin.home.memberCount',
      { count: g.memberCount },
    );
    const roles = this.i18n.translate(
      g.roleCount === 1 ? 'admin.home.roleCountOne' : 'admin.home.roleCount',
      {
        count: g.roleCount,
      },
    );
    return `${members} · ${roles}`;
  }

  /** The settings of a gremium as label and value, for the read-out of an open row. */
  protected settings(g: Gremium): Setting[] {
    const t = (k: Parameters<I18nService['translate']>[0], p?: Record<string, string | number>) =>
      this.i18n.translate(k, p);
    const yesNo = (v: boolean | undefined) => t(v ? 'admin.gremien.yes' : 'admin.gremien.no');
    const cd = this.cdVariants().find((v) => v.id === g.cdVariantId);
    const lead = g.delegationLeadMinutes ?? 0;
    const recipients = this.recipients().get(g.id);
    const list: Setting[] = [
      {
        label: t('admin.gremien.cdVariant'),
        value: cd ? cd.name : t('admin.gremien.cdVariantDefault'),
      },
      {
        label: t('admin.gremien.defaultLang'),
        value: t(g.defaultLang === 'en' ? 'admin.gremien.langEn' : 'admin.gremien.langDe'),
      },
      {
        label: t('admin.gremien.quorumShort'),
        value:
          g.quorumPercent === null || g.quorumPercent === undefined
            ? t('admin.gremien.noQuorum')
            : t('admin.gremien.percent', { value: g.quorumPercent }),
      },
      { label: t('admin.gremien.delegation'), value: yesNo(g.allowVoteDelegation) },
    ];
    if (g.allowVoteDelegation) {
      list.push(
        {
          label: t('admin.gremien.delegationLeadShort'),
          value:
            lead > 0 ? t('admin.gremien.minutes', { value: lead }) : t('admin.gremien.untilStart'),
        },
        { label: t('admin.gremien.delegationExternal'), value: yesNo(g.delegationAllowExternal) },
      );
    }
    list.push({
      label: t('admin.gremien.mailRecipients'),
      value:
        recipients === undefined
          ? '…'
          : recipients === null
            ? t('admin.gremien.recipientsLoadFailed')
            : recipients.length
              ? recipients.join(', ')
              : t('admin.gremien.noRecipients'),
      copyable: !!recipients?.length,
    });
    return list;
  }

  protected openCreate(): void {
    this.lastDialogGremium.set(null);
    this.dialogGremium.set(null);
  }

  protected openEdit(g: Gremium): void {
    this.lastDialogGremium.set(g);
    this.dialogGremium.set(g);
  }

  protected closeDialog(): void {
    this.dialogGremium.set(undefined);
  }

  protected onSaved(event: {
    gremium: Gremium;
    created: boolean;
    recipients: string[] | null;
  }): void {
    this.dialogGremium.set(undefined);
    // `null`: the dialog did not save the recipients, so the row keeps what it shows.
    if (event.recipients) this.setRecipients(event.gremium.id, event.recipients);
    this.toast.success(
      this.i18n.translate(
        event.created ? 'admin.gremien.toast.created' : 'admin.gremien.toast.updated',
      ),
    );
    // A new gremium opens, so its roles show at once.
    if (event.created) this.expanded.update((s) => new Set(s).add(event.gremium.id));
    this.reload(false);
  }

  /**
   * The dialog saved the base data, but not the recipients, and stays open. The list
   * reloads at once, so the row is correct also when the admin cancels the dialog.
   */
  protected onBaseSaved(event: { gremium: Gremium; created: boolean }): void {
    if (event.created && !this.isOpen(event.gremium)) {
      this.expanded.update((s) => new Set(s).add(event.gremium.id));
      // The recipients of the new gremium are not saved: read what the server has.
      this.loadRecipients(event.gremium.id);
    }
    this.reload(false);
  }

  /** A role was added or deleted in the matrix: the count of the row follows. */
  protected onRoleCount(g: Gremium, count: number): void {
    this.gremien.update((list) =>
      list.map((x) => (x.id === g.id ? { ...x, roleCount: count } : x)),
    );
  }

  askDelete(g: Gremium): void {
    this.confirmDelete.set(g);
  }

  doDelete(): void {
    const g = this.confirmDelete();
    if (!g || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteGremium(g.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(null);
        this.toast.success(this.i18n.translate('admin.gremien.toast.deleted'));
        this.reload(false);
      },
      error: () => {
        this.deleting.set(false);
        this.toast.error(this.i18n.translate('admin.gremien.deleteFailed'));
      },
    });
  }

  /** `first`: the first load opens the first row, as on the board. */
  private reload(first: boolean): void {
    if (first) this.loading.set(true);
    this.loadError.set(false);
    this.api.listGremien({ quiet: true }).subscribe({
      next: (g) => {
        this.gremien.set(g);
        this.loading.set(false);
        if (first && g.length) this.toggle(g[0]);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }
}
