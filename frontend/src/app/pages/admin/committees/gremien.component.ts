import { ExpandRowComponent } from '@shared/ui/expand-row/expand-row.component';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { FeatureService } from '@core/features/feature.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  type Action,
  ButtonComponent,
  ButtonGroupComponent,
  ConfirmDialogComponent,
  IconComponent,
  type ListRow,
  type LoadState,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  scrollBehavior,
  SearchPillComponent,
  StatusTextComponent,
  ToastService,
  SectionComponent,
  FactsComponent,
} from '@stupa-makers/ui-kit';
import {
  RecordsScreenComponent,
  ScreenHeadToolsDirective,
  ScreenIntroDirective,
  ScreenRecordDirective,
  ScreenSearchDirective,
} from '@stupa-makers/ui-kit/screens';
import { problemCode } from '@core/api/problem';
import { AdminApiService } from '../admin-api.service';
import type { CdVariantOption, Gremium } from '../admin.models';
import { GremiumRoleMatrixComponent } from '../gremium-roles/gremium-role-matrix.component';
import { GremiumDefaultsDialogComponent } from './gremium-defaults-dialog/gremium-defaults-dialog.component';
import { GremiumDialogComponent } from './gremium-dialog/gremium-dialog.component';
import { expandSet } from '@shared/expand-set';
import { listSearch, hitCount, searchedRows } from '../list-search';

/**
 * The message of a refused gremium delete. The delete applies the rules of the meeting
 * delete to every meeting of the gremium: an open vote gives 409 `open_vote`, a final
 * protocol without `meeting.delete_finalized` gives 403 `meeting_finalized`. A Gremium
 * that a budget belongs to gives 409 `gremium_has_budget`. Any other refusal keeps the
 * generic message.
 */
function deleteErrorKey(err: unknown): TranslationKey {
  switch (problemCode(err)) {
    case 'open_vote':
      return 'admin.gremien.deleteOpenVote';
    case 'meeting_finalized':
      return 'admin.gremien.deleteFinalized';
    case 'gremium_has_budget':
      return 'admin.gremien.deleteHasBudget';
    default:
      return 'admin.gremien.deleteFailed';
  }
}

/** One setting of a gremium in the read-out of an open row. */
interface Setting {
  readonly label: string;
  readonly value: string;
  /** The value is a list of e-mail addresses: it wraps and never gets cut. */
  readonly copyable?: boolean;
}

/**
 * Gremien administration (`/admin/committees`).
 *
 * One row per gremium: name, slug, "n Mitglieder · n Rollen", the link to the members,
 * edit, delete and the toggle. An open row shows the settings (gaps N38) and the role
 * matrix of the gremium (`app-gremium-role-matrix`); the first row starts open, or the row
 * of `?open=<gremium id>`, which the page then scrolls into view (002601). The
 * memberships come from the OIDC groups, so this page has no member editing. The dialog
 * `app-gremium-dialog` creates and edits a gremium. The header button "Vorgaben" opens
 * the values that the form of a new gremium starts with (§ 000906).
 *
 * The disclosure is a native button, because it needs aria-expanded on the button itself.
 */
@Component({
  selector: 'app-admin-gremien',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FactsComponent,
    ButtonComponent,
    ButtonGroupComponent,
    GremiumDefaultsDialogComponent,
    SectionComponent,
    ExpandRowComponent,
    ConfirmDialogComponent,
    TranslatePipe,
    IconComponent,
    RecordsScreenComponent,
    ScreenHeadToolsDirective,
    ScreenIntroDirective,
    ScreenRecordDirective,
    ScreenSearchDirective,
    SearchPillComponent,
    RowMenuComponent,
    StatusTextComponent,
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
  private readonly router = inject(Router);
  private readonly features = inject(FeatureService);
  private readonly route = inject(ActivatedRoute);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);

  readonly gremien = signal<Gremium[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal(false);
  /** The search of the list (§002690, §002691). */
  protected readonly search = listSearch();
  /** The rows of the records screen (§ui-kit:002257). */
  protected readonly rows = computed<LoadState<readonly ListRow[]>>(() => {
    if (this.loading()) return { state: 'loading' };
    if (this.loadError())
      return {
        state: 'error',
        message: this.i18n.translate('admin.gremien.error'),
        retry: () => this.reload(true),
      };
    const rows = this.search
      .filter(this.gremien(), (g) => [g.name, g.slug, this.counts(g)])
      .map((g) => ({ id: g.id, title: g.name }));
    return searchedRows(
      rows.length
        ? { state: 'ready', data: rows }
        : { state: 'empty', icon: 'landmark', heading: this.i18n.translate('admin.gremien.empty') },
      this.search,
      this.i18n.translate('admin.list.noHits'),
    );
  });
  /** The hits of the search for the pill. */
  protected readonly hits = computed(() => hitCount(this.rows(), this.search));
  /** "Gremium anlegen" as the FAB; "Vorgaben" is a button at the end of the head. */
  protected readonly actions = computed<readonly Action[]>(() => [
    {
      key: 'create',
      label: this.i18n.translate('fab.gremium'),
      icon: 'plus',
      priority: 'fab',
    },
  ]);
  /** CD variants from `GET /cd-variants`: the dropdown source and the read-out names. */
  readonly cdVariants = signal<CdVariantOption[]>([]);
  /** The ids of the open rows. */
  protected readonly expanded = expandSet<string>();
  /** The extra protocol recipients of the open rows, by gremium id. */
  private readonly recipients = signal<ReadonlyMap<string, string[] | null>>(new Map());

  /** The dialog: `undefined` = closed, `null` = a new gremium, else the gremium to edit. */
  protected readonly dialogGremium = signal<Gremium | null | undefined>(undefined);
  /** The last gremium of the dialog. It stays while the dialog closes. */
  protected readonly lastDialogGremium = signal<Gremium | null>(null);
  /** The dialog "Vorgaben für neue Gremien" is open. */
  protected readonly defaultsOpen = signal(false);
  readonly confirmDelete = signal<Gremium | null>(null);
  readonly deleting = signal(false);

  /** "Stellvertretungen" in the ⋮ menu: the page needs `admin.delegations` and Sitzungen on. */
  protected readonly canPool = computed(
    () => this.auth.can('admin.delegations') && this.features.isOn('meetings'),
  );

  constructor() {
    this.reload(true);
    this.api.listCdVariantOptions().subscribe({
      next: (v) => this.cdVariants.set(v),
      error: () => this.cdVariants.set([]),
    });
  }

  /** The gremium of a row of the records screen. */
  protected gremiumOf(id: string): Gremium {
    return this.gremien().find((g) => g.id === id)!;
  }

  /** An action of the head or the FAB. */
  protected onAction(key: string): void {
    if (key === 'create') this.openCreate();
  }

  protected isOpen(g: Gremium): boolean {
    return this.expanded.has(g.id);
  }

  protected toggle(g: Gremium): void {
    if (this.expanded.toggle(g.id)) this.loadRecipients(g.id);
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
        value: this.i18n.languageName(g.defaultLang),
      },
      {
        label: t('admin.gremien.quorumShort'),
        value:
          g.quorumPercent === null || g.quorumPercent === undefined
            ? t('admin.gremien.noQuorum')
            : t('admin.gremien.percent', { value: g.quorumPercent }),
      },
      ...(g.repeatQuorumPercent === null || g.repeatQuorumPercent === undefined
        ? []
        : [
            {
              label: t('admin.gremien.repeatQuorumShort'),
              value: t('admin.gremien.percent', { value: g.repeatQuorumPercent }),
            },
          ]),
      { label: t('admin.gremien.guestsMayVote'), value: yesNo(g.guestsMayVote) },
      { label: t('admin.gremien.delegation'), value: yesNo(g.allowVoteDelegation) },
      { label: t('admin.gremien.publicShort'), value: yesNo(g.protocolsPublic) },
      ...(g.allowVoteDelegation
        ? [
            {
              label: t('admin.gremien.delegationLeadShort'),
              value:
                lead > 0
                  ? t('admin.gremien.minutes', { value: lead })
                  : t('admin.gremien.untilStart'),
            },
            {
              label: t('admin.gremien.delegationExternal'),
              value: yesNo(g.delegationAllowExternal),
            },
            {
              label: t('admin.gremien.delegationMax'),
              value: String(g.delegationMaxPerDelegate ?? 2),
            },
            {
              label: t('admin.gremien.delegationInElections'),
              value: yesNo(g.delegationInElections),
            },
          ]
        : []),
      {
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
      },
    ];
    return list;
  }

  protected openCreate(): void {
    this.lastDialogGremium.set(null);
    this.dialogGremium.set(null);
  }

  /**
   * The ⋮ menu of a gremium row. The row itself opens the details (settings and roles),
   * so the edit of the base data is the first item here.
   */
  protected readonly rowMenu = computed<readonly RowMenuSection[]>(() => [
    {
      items: [
        { id: 'edit', label: this.i18n.translate('admin.gremien.editAction'), icon: 'edit' },
        { id: 'members', label: this.i18n.translate('admin.gremien.members'), icon: 'users' },
        ...(this.canPool()
          ? [
              {
                id: 'substitutes',
                label: this.i18n.translate('admin.substitutes.title'),
                icon: 'handshake' as const,
              },
            ]
          : []),
      ],
    },
    {
      items: [
        { id: 'delete', label: this.i18n.translate('admin.gremien.deleteAction'), icon: 'trash', danger: true },
      ],
    },
  ]);

  protected onRowMenu(item: RowMenuItem, g: Gremium): void {
    if (item.id === 'edit') this.openEdit(g);
    if (item.id === 'members') void this.router.navigate(['/admin/committees', g.id, 'members']);
    if (item.id === 'substitutes')
      void this.router.navigate(['/admin/committees', g.id, 'substitutes']);
    if (item.id === 'delete') this.askDelete(g);
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
    if (event.recipients) this.setRecipients(event.gremium.id, event.recipients);
    this.toast.show(
      this.i18n.translate(
        event.created ? 'admin.gremien.toast.created' : 'admin.gremien.toast.updated',
      ),
      'success',
    );
    if (event.created) this.expanded.open(event.gremium.id);
    this.reload(false);
  }

  /**
   * The dialog saved the base data, but not the recipients, and stays open. The list
   * reloads at once, so the row is correct also when the admin cancels the dialog.
   */
  protected onBaseSaved(event: { gremium: Gremium; created: boolean }): void {
    if (event.created && !this.isOpen(event.gremium)) {
      this.expanded.open(event.gremium.id);
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
        this.toast.show(this.i18n.translate('admin.gremien.toast.deleted'), 'success');
        this.reload(false);
      },
      error: (err: unknown) => {
        this.deleting.set(false);
        this.toast.show(this.i18n.translate(deleteErrorKey(err)), 'error');
      },
    });
  }

  /** `first`: the first load opens the row of `?open=<id>`, else the first row (002601). */
  protected reload(first: boolean): void {
    if (first) this.loading.set(true);
    this.loadError.set(false);
    this.api.listGremien({ quiet: true }).subscribe({
      next: (g) => {
        this.gremien.set(g);
        this.loading.set(false);
        if (first && g.length) this.openFirst(g);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Opens the row that `?open=` names and scrolls it into view; else the first row. */
  private openFirst(list: readonly Gremium[]): void {
    const asked = this.route.snapshot.queryParamMap.get('open');
    const target = list.find((g) => g.id === asked);
    this.toggle(target ?? list[0]);
    if (!target) return;
    afterNextRender(
      () => {
        // The head of the row, not the whole row: an open row is taller than the screen,
        // and the centre keeps the head clear of a sticky page head.
        const head = this.host.nativeElement.querySelector<HTMLElement>(
          `[data-gremium="${CSS.escape(target.id)}"] [aria-expanded]`,
        );
        head?.scrollIntoView?.({ block: 'center', behavior: scrollBehavior() });
      },
      { injector: this.injector },
    );
  }
}
