import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgTemplateOutlet } from '@angular/common';
import { FormGroup, FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type {
  Application,
  ApplicationComment,
  ApplicationType,
  ApplicationVersion,
  CommentVisibility,
  FormFieldDef,
  Transition,
  Uuid,
} from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
import { toFormlyFields } from '@shared/forms/formly-mapper';
import {
  AvatarComponent,
  EmptyStateComponent,
  FieldGroupComponent,
  FieldRowComponent,
  NoteComponent,
  RowMenuComponent,
  StatusTextComponent,
  flowColorKind,
  type RowMenuItem,
  type RowMenuSection,
} from '@shared/ui';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  MEDIA,
  SelectComponent,
  TabsComponent,
  ToastService,
  type SelectOption,
  type TabItem,
} from '@stupa-makers/ui-kit';
import {
  BudgetTreeApi,
  type BudgetTreeNode,
  type FiscalYear,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import { AttachmentsPanelComponent } from './attachments-panel.component';
import {
  applicationTitle,
  formatDateRangeValue,
  formatFieldValue,
  formatIsoDate,
  transitionLooks,
} from './applications.util';
import { ApplicationsPageService } from './applications-page.service';
import { ForceStatusDialogComponent } from './force-status-dialog/force-status-dialog.component';
import { ShareLinksDialogComponent } from './share-links-dialog/share-links-dialog.component';
import { mediaQuerySignal } from '../../layout/media-query';
import { RailStatusService } from '../../layout/rail-status.service';

/** Comparison offer / cost position for the structured detail view. */
interface DetailOffer {
  label?: string;
  value?: number | null;
  preferred?: boolean;
}
interface DetailPosition {
  label: string;
  offers: DetailOffer[];
  /** Opt-out of comparison offers (with the applicant's reason). */
  noOffers?: boolean;
  noOffersReason?: string;
}

/** The tabs of the detail when the list and the detail do not sit side by side. */
type DetailTab = 'app' | 'history' | 'comments' | 'files';

/**
 * Application detail: the sheet beside the list (board Anträge), or alone with tabs on a
 * narrow screen (board Schmal-Anträge-Detail).
 *
 * Header: "<Typ> · Version n", the title, "status · gremium · amount", the firable
 * transitions as buttons, and the actions (share links, edit, archive, and a menu with
 * Status setzen, Versionen vergleichen, Löschen, Anonymisierung beantragen). Body: the
 * details, the answers, the attachments, the version history and the comments.
 *
 * RBAC here only gates the UX. The server decides.
 */
@Component({
  selector: 'app-applications-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    RouterLink,
    FormsModule,
    FormlyForm,
    LocalizedDatePipe,
    TranslatePipe,
    AvatarComponent,
    EmptyStateComponent,
    FieldGroupComponent,
    FieldRowComponent,
    NoteComponent,
    RowMenuComponent,
    StatusTextComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    SelectComponent,
    TabsComponent,
    CostCentreTreeComponent,
    AttachmentsPanelComponent,
    MarkdownViewComponent,
    ShareLinksDialogComponent,
    ForceStatusDialogComponent,
  ],
  templateUrl: './applications-detail.component.html',
  styleUrl: './applications-detail.component.scss',
})
export class ApplicationsDetailComponent {
  private readonly api = inject(ApiClient);
  private readonly budgetApi = inject(BudgetTreeApi);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly railStatus = inject(RailStatusService);
  private readonly route = inject(ActivatedRoute);
  /** The link to the list pane. Absent when the detail runs without the list page. */
  private readonly page = inject(ApplicationsPageService, { optional: true });

  /** The list sits beside the detail: two columns, no tabs. */
  readonly split = computed(() => this.page?.split() ?? false);
  /** Phone: every header action goes into the menu. */
  readonly phone = mediaQuerySignal(MEDIA.phone);

  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly error = signal(false);

  readonly app = signal<Application | null>(null);
  readonly versions = signal<ApplicationVersion[]>([]);
  readonly comments = signal<ApplicationComment[]>([]);
  /** Field definitions of the effective form for labels and typed values. Empty on error. */
  readonly formFields = signal<FormFieldDef[]>([]);
  /** The same field definitions by key. The data rows and the version diff both
   *  look a key up, so they share one map. */
  private readonly fieldByKey = computed(
    () => new Map(this.formFields().map((f) => [f.key, f])),
  );

  readonly newComment = signal('');
  readonly visibility = signal<CommentVisibility>('public');
  readonly posting = signal(false);

  // Edit and delete of one comment. Both run in a dialog. The server allows the
  // author of the comment and a holder of `application.manage`. `isOwn` carries
  // the same author check the server makes, so the UI offers nothing that gives
  // a 403. Only the body changes. The visibility stays as written.
  readonly editingComment = signal<ApplicationComment | null>(null);
  readonly commentDraft = signal('');
  readonly savingComment = signal(false);
  readonly deletingComment = signal<ApplicationComment | null>(null);
  readonly removingComment = signal(false);

  /** The active tab of the narrow layout. */
  readonly tab = signal<DetailTab>('app');
  /** The number of attachments, from the panel. `null` until it loaded them. */
  readonly attachmentCount = signal<number | null>(null);

  /** Manual transitions that the server guard allows, plus the fire in flight. */
  readonly transitions = signal<Transition[]>([]);
  readonly firing = signal<Uuid | null>(null);
  readonly canTransition = computed(() => this.auth.can('application.transition'));

  protected readonly budgetTree = signal<BudgetTreeNode[]>([]);
  protected readonly budgetChoice = signal('');
  protected readonly assigningBudget = signal(false);
  protected readonly budgetDialogOpen = signal(false);
  /** Fiscal-year choice among the years of the top budget of the selected cost centre.
   *  An empty value means automatic. The server then derives the single active year,
   *  or it answers 422. */
  protected readonly fiscalYears = signal<FiscalYear[]>([]);
  protected readonly fiscalChoice = signal('');
  /** Maps `budgetId` to "FULL-PATH – name" for the badge of the current cost centre. */
  private readonly budgetLabels = computed(
    () => new Map(flattenBudgetOptions(this.budgetTree()).map((o) => [o.value, o.label])),
  );
  protected budgetLabel(id: string | null | undefined): string {
    return (id && this.budgetLabels().get(id)) || '';
  }
  /** Maps `fiscalYearId` to the display text of a loaded fiscal year, for example `2026`. */
  private readonly fiscalLabels = computed(
    () => new Map(this.fiscalYears().map((y) => [y.id, y.display])),
  );
  protected fiscalLabel(id: string | null | undefined): string {
    return (id && this.fiscalLabels().get(id)) || '';
  }
  /** Dropdown options: "automatic" plus every fiscal year of the top budget.
   *  An inactive year carries a mark. */
  protected readonly fiscalOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('applications.budget.fiscalAuto') },
    ...this.fiscalYears().map((y) => ({
      value: y.id,
      label: y.active
        ? y.display
        : `${y.display} (${this.i18n.translate('applications.budget.fiscalInactive')})`,
    })),
  ]);
  /** Find the top budget (root) whose subtree contains the cost centre. */
  private topLevelIdOf(budgetId: string): string | null {
    const contains = (n: BudgetTreeNode): boolean =>
      n.id === budgetId || (n.children?.some(contains) ?? false);
    for (const root of this.budgetTree()) if (contains(root)) return root.id;
    return null;
  }
  /** Load the fiscal years of the selected cost centre's top budget (dropdown + badge). */
  private loadFiscalYears(budgetId: string | null): void {
    const top = budgetId ? this.topLevelIdOf(budgetId) : null;
    if (!top) {
      this.fiscalYears.set([]);
      return;
    }
    const seq = this.loadSeq;
    this.budgetApi.listFiscalYears(top).subscribe({
      next: (ys) => {
        if (seq === this.loadSeq) this.fiscalYears.set(ys);
      },
      error: () => {
        if (seq === this.loadSeq) this.fiscalYears.set([]);
      },
    });
  }
  /** Handle a cost centre picked in the dialog and reload the fiscal-year list.
   *  The fiscal-year choice survives only when the user picks the original cost
   *  centre again. */
  protected onBudgetPicked(id: string): void {
    this.budgetChoice.set(id);
    this.fiscalChoice.set(
      id === (this.app()?.budgetId ?? '') ? (this.app()?.fiscalYearId ?? '') : '',
    );
    this.loadFiscalYears(id || null);
  }
  protected openBudgetDialog(): void {
    const cur = this.app()?.budgetId ?? '';
    this.budgetChoice.set(cur);
    this.fiscalChoice.set(this.app()?.fiscalYearId ?? '');
    this.loadFiscalYears(cur || null);
    this.budgetDialogOpen.set(true);
  }

  // Inline editing for the creator or a manager, plus delete.
  readonly editing = signal(false);
  readonly editFields = signal<FormlyFieldConfig[]>([]);
  readonly savingEdit = signal(false);
  editForm = new FormGroup({});
  editModel: Record<string, unknown> = {};
  readonly confirmDelete = signal(false);
  readonly deleting = signal(false);
  readonly confirmErase = signal(false);
  readonly requestingErasure = signal(false);

  // Force status is a privileged override that needs `application.force_status`. The
  // dialog loads the flow states itself.
  readonly canForceStatus = computed(() => this.auth.can('application.force_status'));
  readonly forceDialogOpen = signal(false);

  private readonly router = inject(Router);
  readonly canManage = computed(() => this.auth.can('application.manage'));
  /**
   * Delete is irreversible and needs `application.delete`. An admin holds it
   * through the role bypass. Any other role holds it through an explicit grant. The
   * server gates on the same key.
   */
  readonly canDelete = computed(() => this.auth.can('application.delete'));
  readonly canArchive = computed(() => this.auth.can('application.archive'));
  readonly archiving = signal(false);

  /**
   * Move the application out of the working list, or bring it back.
   *
   * Reversible and destructive of nothing, so unlike the delete and the erasure request
   * it asks for no confirmation: the way back is one click on the same button.
   */
  toggleArchived(): void {
    const current = this.app();
    if (!current || this.archiving()) return;
    const next = current.archivedAt === null;
    this.archiving.set(true);
    this.api.setApplicationArchived(current.id, next).subscribe({
      next: (updated) => {
        this.app.set(updated);
        this.archiving.set(false);
        this.page?.notify({ id: updated.id, kind: 'updated', source: 'detail' });
        this.toast.success(
          this.i18n.translate(next ? 'applications.archived' : 'applications.unarchived'),
        );
      },
      error: () => {
        this.archiving.set(false);
        this.toast.error(this.i18n.translate('applications.detail.error'));
      },
    });
  }
  /**
   * Public share links. `application.share` is its own permission on purpose: reading an
   * application and deciding it may be read by anyone holding a URL are different
   * decisions, and the server gates on the same key. The dialog does the rest.
   */
  readonly canShare = computed(() => this.auth.can('application.share'));
  readonly shareDialogOpen = signal(false);

  openShareDialog(): void {
    this.shareDialogOpen.set(true);
  }

  /**
   * One value of the version diff, formatted the way the data rows show the field.
   *
   * The diff carries a key, not a field definition, so the type comes from the key.
   * A date then reads as a day and a date range as a span, not as an ISO string or
   * as JSON.
   *
   * A key the active form does not define — an answer of an older form version
   * whose field is gone — keeps the plain rule. A type it never had cannot format
   * it, and the stored text tells the reader more than a placeholder does.
   */
  readonly fmt = (value: unknown, key?: string): string => {
    const field = key === undefined ? undefined : this.fieldByKey().get(key);
    return field ? this.formatByField(field, value) : formatFieldValue(value);
  };

  private id: Uuid = '';

  readonly title = computed(() =>
    applicationTitle(this.app()?.data, this.i18n.translate('applications.list.untitled')),
  );

  /** The application types, for "<Typ> · Version n". */
  private readonly types = signal<ApplicationType[]>([]);
  /** Gremium names from the meeting filter list, for a gremium the reader is not in. */
  private readonly filterGremien = signal<{ id: Uuid; name: string }[]>([]);
  private gremienRequested = false;

  /** "<Typ> · Version n" above the title. */
  readonly metaLine = computed(() => {
    const app = this.app();
    if (!app) return '';
    const type = this.types().find((t) => t.id === app.typeId)?.name;
    const version = this.i18n.translate('applications.detail.version', { version: app.version });
    return type ? `${type} · ${version}` : version;
  });

  /** The name of the gremium of the application, or null when it is not known here. */
  readonly gremiumName = computed(() => {
    const id = this.app()?.gremiumId;
    if (!id) return null;
    const own = this.auth.gremien().find((g) => g.id === id)?.name;
    return own ?? this.filterGremien().find((g) => g.id === id)?.name ?? null;
  });

  /** The status of the application as coloured text. */
  readonly stateKind = computed(() => flowColorKind(this.app()?.state?.color));

  /** The look of each transition button: main action, tonal, or danger (a rejection). */
  readonly looks = computed(() => transitionLooks(this.transitions()));

  /** The data can change: the edit button and the menu item. */
  readonly canEditData = computed(() => {
    const app = this.app();
    return !!app?.canEdit && !!app.state?.editAllowed;
  });

  /** The owner may ask for the anonymization of their data (GDPR Art. 17). */
  readonly canRequestErasure = computed(() => {
    const app = this.app();
    return !!app?.isOwner && !app.applicant?.anonymized;
  });

  /**
   * The header menu. On a phone it also holds the actions that wider screens show as
   * icon buttons (share links, edit, archive).
   */
  readonly menuSections = computed<RowMenuSection[]>(() => {
    const app = this.app();
    if (!app) return [];
    const t = (key: TranslationKey) => this.i18n.translate(key);
    const quick: RowMenuItem[] = [];
    if (this.phone()) {
      if (this.canShare()) quick.push({ id: 'share', label: t('applications.row.share'), icon: 'link' });
      if (this.canEditData()) quick.push({ id: 'edit', label: t('applications.detail.edit'), icon: 'edit' });
      if (this.canArchive()) {
        quick.push({
          id: 'archive',
          label: t(app.archivedAt ? 'applications.row.unarchive' : 'applications.row.archive'),
          icon: 'archive',
        });
      }
    }
    const more: RowMenuItem[] = [];
    if (this.canForceStatus()) {
      more.push({ id: 'force', label: t('applications.detail.forceStatus'), icon: 'flow' });
    }
    if (this.versions().length > 1) {
      more.push({ id: 'versions', label: t('applications.detail.compareVersions'), icon: 'history' });
    }
    const danger: RowMenuItem[] = [];
    if (this.canDelete()) {
      danger.push({ id: 'delete', label: t('applications.detail.delete'), icon: 'trash', danger: true });
    }
    if (this.canRequestErasure()) {
      danger.push({ id: 'erase', label: t('applications.detail.eraseRequest'), icon: 'user', danger: true });
    }
    return [{ items: quick }, { items: more }, { items: danger }].filter((sec) => sec.items.length);
  });

  /** The tabs of the narrow layout, with their counts. */
  readonly tabs = computed<TabItem[]>(() => [
    { id: 'app', label: this.i18n.translate('applications.detail.tab.app') },
    {
      id: 'history',
      label: this.i18n.translate('applications.detail.tab.history'),
      count: this.versions().length,
    },
    {
      id: 'comments',
      label: this.i18n.translate('applications.detail.tab.comments'),
      count: this.comments().length,
    },
    {
      id: 'files',
      label: this.i18n.translate('applications.detail.tab.files'),
      count: this.attachmentCount(),
    },
  ]);

  constructor() {
    // Use `paramMap`, not `snapshot`. Angular reuses the component on a
    // detail-to-detail navigation, so the constructor does not run again. A snapshot
    // would keep the old `id`. The subscription reloads on every `id` change.
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.loadApplication(pm.get('id') ?? '');
    });
    this.api.applicationTypes({ quiet: true }).subscribe({
      next: (types) => this.types.set(types),
      error: () => this.types.set([]),
    });
    // The list pane changed this application (a row action): show the new state.
    this.page?.changes$.pipe(takeUntilDestroyed()).subscribe((change) => {
      if (change.source === 'list' && change.id === this.id && change.kind === 'updated') {
        this.refresh();
      }
    });
  }

  /** A tab of the narrow layout was chosen. */
  selectTab(id: string | null): void {
    if (id === 'app' || id === 'history' || id === 'comments' || id === 'files') this.tab.set(id);
  }

  /** An item of the header menu was chosen. */
  onMenu(item: RowMenuItem): void {
    const app = this.app();
    if (!app) return;
    switch (item.id) {
      case 'share':
        this.openShareDialog();
        break;
      case 'edit':
        this.startEdit(app);
        break;
      case 'archive':
        this.toggleArchived();
        break;
      case 'force':
        this.openForceDialog();
        break;
      case 'versions':
        this.showVersions();
        break;
      case 'delete':
        this.confirmDelete.set(true);
        break;
      case 'erase':
        this.confirmErase.set(true);
        break;
    }
  }

  /**
   * "Versionen vergleichen": the history holds every version with its changes. The tabs
   * switch to it; side by side the history section scrolls into view.
   */
  showVersions(): void {
    if (!this.split()) {
      this.tab.set('history');
      return;
    }
    const el = document.getElementById('ad-history');
    el?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    el?.focus({ preventScroll: true });
  }

  /** Load the gremium names once, when the gremium is not one of the reader's own. */
  private resolveGremium(app: Application): void {
    if (!app.gremiumId || this.gremienRequested) return;
    if (this.auth.gremien().some((g) => g.id === app.gremiumId)) return;
    this.gremienRequested = true;
    this.api.listMeetingFilterGremien().subscribe({
      next: (list) => this.filterGremien.set(list),
      error: () => this.filterGremien.set([]),
    });
  }

  /** Load sequence number that guards against a late response.
   *  A fast switch between detail pages can deliver a response of an earlier
   *  application. Such a response must not overwrite the current one. Each response
   *  checks that it still belongs to the latest load. */
  private loadSeq = 0;

  private loadApplication(id: Uuid): void {
    this.id = id;
    const seq = ++this.loadSeq;
    // Reset state for the (possibly new) id so nothing stale flashes through.
    this.app.set(null);
    this.versions.set([]);
    this.comments.set([]);
    this.formFields.set([]);
    this.newComment.set('');
    this.visibility.set('public');
    this.editing.set(false);
    this.confirmDelete.set(false);
    this.notFound.set(false);
    this.error.set(false);
    this.editingComment.set(null);
    this.deletingComment.set(null);
    this.transitions.set([]);
    this.attachmentCount.set(null);
    this.tab.set('app');
    if (!id) {
      this.notFound.set(true);
      this.loading.set(false);
      return;
    }
    this.loading.set(true);
    this.api.getApplication(id, { quiet: true }).subscribe({
      next: (app) => {
        if (seq !== this.loadSeq) return;
        this.app.set(app);
        this.loading.set(false);
        this.resolveGremium(app);
        this.loadAux();
        // Take the effective form from the pinned version of the application, not from
        // the active one. The labels and the edit fields then match the data that the
        // server validates.
        this.api.applicationForm(app.id).subscribe({
          next: (eff) => {
            if (seq === this.loadSeq) this.formFields.set(eff.sections.flatMap((s) => s.fields));
          },
          error: () => {
            if (seq === this.loadSeq) this.formFields.set([]);
          },
        });
      },
      error: (err: { status?: number }) => {
        if (seq !== this.loadSeq) return;
        this.loading.set(false);
        if (err.status === 404) this.notFound.set(true);
        else this.error.set(true);
      },
    });
  }

  /** Load the versions, the comments and the available transitions.
   *  An error degrades silently to an empty result. The transitions load only with
   *  the needed permission. The server filters them again. */
  private loadAux(): void {
    const seq = this.loadSeq;
    this.api.versions(this.id).subscribe({
      next: (v) => {
        if (seq === this.loadSeq) this.versions.set(v);
      },
      error: () => {},
    });
    this.api.comments(this.id, { quiet: true }).subscribe({
      next: (c) => {
        if (seq === this.loadSeq) this.comments.set(c);
      },
      error: () => {},
    });
    if (this.canTransition()) {
      this.api.transitions(this.id).subscribe({
        next: (t) => {
          if (seq === this.loadSeq) this.transitions.set(t);
        },
        error: () => {
          if (seq === this.loadSeq) this.transitions.set([]);
        },
      });
    }
    // The badge label and the dialog picker both need the cost-centre tree.
    if (this.canManage()) {
      this.budgetChoice.set(this.app()?.budgetId ?? '');
      this.fiscalChoice.set(this.app()?.fiscalYearId ?? '');
      this.budgetApi.tree().subscribe({
        next: (tree) => {
          if (seq !== this.loadSeq) return;
          this.budgetTree.set(tree);
          // The badge needs the fiscal years of the current cost centre.
          this.loadFiscalYears(this.app()?.budgetId ?? null);
        },
        error: () => {
          if (seq === this.loadSeq) this.budgetTree.set([]);
        },
      });
    }
  }

  /** Assign or unassign the cost centre with POST /assign-budget, then reload. */
  assignBudget(): void {
    if (this.assigningBudget()) return;
    this.assigningBudget.set(true);
    this.budgetApi
      .assignBudget(this.id, this.budgetChoice() || null, this.fiscalChoice() || null)
      .subscribe({
        next: () => {
          this.assigningBudget.set(false);
          this.budgetDialogOpen.set(false);
          this.toast.success(this.i18n.translate('applications.actions.success'));
          this.changed();
        },
        error: (err: { status?: number }) => {
          this.assigningBudget.set(false);
          const key =
            err.status === 422
              ? 'applications.budget.invalid'
              : err.status === 403
                ? 'applications.transitions.forbidden'
                : 'applications.actions.error';
          this.toast.error(this.i18n.translate(key));
        },
      });
  }

  /** Build the application data as label and value rows.
   *  A field definition gives the label and the typed value. An unknown key stays
   *  raw. The rows omit `title`, because the header shows it, and they omit the pure
   *  display fields. A long text (`textarea`) carries the `md` flag and renders as
   *  Markdown. This keeps the newlines and the simple formatting. */
  dataEntries(app: Application): { key: string; label: string; value: string; md: boolean }[] {
    const lang = this.i18n.locale();
    const byKey = this.fieldByKey();
    const rows: { key: string; label: string; value: string; md: boolean }[] = [];
    const seen = new Set<string>();

    const pushField = (f: FormFieldDef): void => {
      if (f.type === 'markdown' || f.type === 'computed') return;
      // Cost positions get their own block with the positions and the offers.
      if (f.type === 'positions') return;
      if (f.key === 'title') return;
      if (!(f.key in app.data)) return;
      seen.add(f.key);
      rows.push({
        key: f.key,
        label: resolveI18n(f.label, lang),
        value: this.formatByField(f, app.data[f.key]),
        md: f.type === 'textarea',
      });
    };

    for (const f of this.formFields()) pushField(f);
    // Show data without a matching field definition as a raw value. Skip `title`.
    for (const [key, value] of Object.entries(app.data)) {
      if (seen.has(key) || key === 'title' || byKey.has(key)) continue;
      rows.push({ key, label: key, value: formatFieldValue(value), md: false });
    }
    return rows;
  }

  /** Format a value for display based on its field type. */
  private formatByField(field: FormFieldDef, value: unknown): string {
    if (value === null || value === undefined || value === '') return '—';
    const lang = this.i18n.locale();
    if (field.type === 'positions') return this.formatPositions(value);
    if (field.type === 'checkbox' && typeof value === 'boolean') {
      return this.i18n.translate(value ? 'common.yes' : 'common.no');
    }
    // A date and a date range read as a day, not as an ISO string or as JSON. The
    // public share page shows the same span, so both views agree.
    if (field.type === 'date') return formatIsoDate(value, lang) || '—';
    if (field.type === 'daterange') return formatDateRangeValue(value, lang) || '—';
    // A dynamic picker for a Gremium or a budget carries the options of the server in
    // the effective form. Resolve them to names, like a plain select.
    if (field.type === 'select' || field.type === 'gremium_select' || field.type === 'budget_select') {
      const opt = field.options?.find((o) => o.value === value);
      return opt ? resolveI18n(opt.label, lang) : formatFieldValue(value);
    }
    if (field.type === 'multiselect' && Array.isArray(value)) {
      return value
        .map((v) => {
          const opt = field.options?.find((o) => o.value === v);
          return opt ? resolveI18n(opt.label, lang) : String(v);
        })
        .join(', ');
    }
    if (field.type === 'currency') {
      const n = Number(value);
      if (Number.isFinite(n)) {
        return new Intl.NumberFormat(this.i18n.formatLocale(), {
          style: 'currency',
          currency: 'EUR',
        }).format(n);
      }
    }
    return formatFieldValue(value);
  }

  /** Build the cost-position fields as a structured block for the detail view.
   *  Each position carries its comparison offers, the preferred one included. */
  positionEntries(app: Application): {
    key: string;
    label: string;
    positions: DetailPosition[];
  }[] {
    const lang = this.i18n.locale();
    const out: { key: string; label: string; positions: DetailPosition[] }[] = [];
    for (const f of this.formFields()) {
      if (f.type !== 'positions' || !(f.key in app.data)) continue;
      const raw = app.data[f.key];
      if (!Array.isArray(raw)) continue;
      const positions = (raw as DetailPosition[]).map((p) => ({
        label: p.label ?? '',
        offers: Array.isArray(p.offers) ? p.offers : [],
        noOffers: p.noOffers === true,
        noOffersReason: typeof p.noOffersReason === 'string' ? p.noOffersReason : '',
      }));
      out.push({ key: f.key, label: resolveI18n(f.label, lang), positions });
    }
    return out;
  }

  /** Value of a comparison offer / position as currency. */
  money(value: number | null | undefined): string {
    const n = Number(value ?? 0);
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: 'EUR',
    }).format(Number.isFinite(n) ? n : 0);
  }

  /** The value of a position is the value of the preferred offer. */
  positionValue(p: DetailPosition): number {
    return p.offers.find((o) => o.preferred)?.value ?? 0;
  }

  /** Sum over all position values. */
  positionsTotal(positions: DetailPosition[]): number {
    return positions.reduce((s, p) => s + this.positionValue(p), 0);
  }

  /** Format the cost positions compactly: the position count and the preferred sum. */
  private formatPositions(value: unknown): string {
    if (!Array.isArray(value)) return '—';
    let total = 0;
    for (const p of value as { offers?: { value?: number | null; preferred?: boolean }[] }[]) {
      const pref = (p.offers ?? []).find((o) => o.preferred);
      total += pref?.value ?? 0;
    }
    const sum = new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: 'EUR',
    }).format(total);
    return `${value.length} × ${this.i18n.translate('applications.detail.positionsTotal')}: ${sum}`;
  }


  amount(app: Application): string {
    if (app.amount === null) return this.i18n.translate('applications.detail.notProvided');
    const value = Number(app.amount);
    if (Number.isNaN(value)) return app.amount;
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: app.currency ?? 'EUR',
    }).format(value);
  }

  isEmptyDiff(version: ApplicationVersion): boolean {
    const d = version.diff;
    return !!d && !d.added.length && !d.removed.length && !d.changed.length;
  }

  startEdit(app: Application): void {
    const lang = this.i18n.locale();
    // A reader without the PII right gets `data` without the isPII fields (O21), and
    // the server names them in `hiddenKeys`. The form leaves them out, because the
    // server keeps their stored values anyway. A key that is only missing from `data`
    // was never answered, so that field stays editable.
    const hidden = new Set(app.hiddenKeys ?? []);
    const fields = this.formFields().filter((f) => !hidden.has(f.key));
    this.editFields.set(toFormlyFields(fields, lang, { has_budget: true }));
    this.editModel = structuredClone(app.data);
    this.editForm = new FormGroup({});
    this.editing.set(true);
  }

  cancelEdit(): void {
    this.editing.set(false);
  }

  saveEdit(): void {
    if (this.editForm.invalid || this.savingEdit()) return;
    this.savingEdit.set(true);
    this.api.updateApplication(this.id, { ...this.editModel }).subscribe({
      next: () => {
        this.savingEdit.set(false);
        this.editing.set(false);
        this.toast.success(this.i18n.translate('applications.detail.saved'));
        this.changed();
      },
      error: (err: { status?: number }) => {
        this.savingEdit.set(false);
        const key =
          err.status === 409 ? 'applications.detail.locked' : 'applications.detail.saveFailed';
        this.toast.error(this.i18n.translate(key));
      },
    });
  }

  doDelete(): void {
    if (this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteApplication(this.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(false);
        this.toast.success(this.i18n.translate('applications.detail.deleted'));
        this.page?.notify({ id: this.id, kind: 'deleted', source: 'detail' });
        void this.router.navigate(['/applications'], { queryParamsHandling: 'preserve' });
      },
      error: () => {
        this.deleting.set(false);
        this.toast.error(this.i18n.translate('applications.detail.deleteFailed'));
      },
    });
  }

  /** Request the erasure of the application data of the applicant, per GDPR Art. 17.
   *  The magic-link view offers this action. */
  doRequestErasure(): void {
    if (this.requestingErasure()) return;
    this.requestingErasure.set(true);
    this.api.requestErasure(this.id).subscribe({
      next: () => {
        this.requestingErasure.set(false);
        this.confirmErase.set(false);
        this.toast.success(this.i18n.translate('applications.detail.eraseRequested'));
      },
      error: () => {
        this.requestingErasure.set(false);
        this.toast.error(this.i18n.translate('applications.detail.eraseRequestFailed'));
      },
    });
  }

  /** Open the force-status dialog. It loads the flow states itself. */
  openForceDialog(): void {
    this.forceDialogOpen.set(true);
  }

  /** The force-status dialog set a state: load the application again. */
  onForced(): void {
    this.changed();
  }

  /** Display name of a comment: the author, or a fallback based on the role. */
  protected authorName(comment: ApplicationComment): string {
    if (comment.author) return comment.author;
    return this.i18n.translate(
      comment.authorKind === 'applicant'
        ? 'applications.comments.author.applicant'
        : 'applications.comments.author.committee',
    );
  }

  /** Enter sends the comment. Shift+Enter makes a line break.
   *  The Angular `keydown.enter` binding matches the unmodified Enter only. */
  protected onComposerEnter(event: Event): void {
    this.submitComment(event);
  }

  submitComment(event: Event): void {
    event.preventDefault();
    const body = this.newComment().trim();
    if (!body || this.posting()) return;
    this.posting.set(true);
    this.api.addComment(this.id, body, this.visibility()).subscribe({
      next: (created) => {
        this.comments.update((list) => [...list, created]);
        this.newComment.set('');
        this.posting.set(false);
        this.toast.success(this.i18n.translate('applications.comments.added'));
      },
      error: () => {
        this.posting.set(false);
        this.toast.error(this.i18n.translate('applications.comments.error'));
      },
    });
  }

  // --- edit / delete of a comment -----------------------------------------

  /** The author of the comment, or a manager, may change it. The server checks
   *  the same rule, so no visible control ends in a 403. */
  protected canEditComment(comment: ApplicationComment): boolean {
    return comment.isOwn || this.canManage();
  }

  protected openEditComment(comment: ApplicationComment): void {
    this.commentDraft.set(comment.body);
    this.editingComment.set(comment);
  }

  protected closeEditComment(): void {
    this.editingComment.set(null);
  }

  /** Translation key for a failed comment change. 403 and 404 read as reasons. */
  private commentErrorKey(status: number | undefined): TranslationKey {
    if (status === 403) return 'applications.comments.forbidden';
    if (status === 404) return 'applications.comments.gone';
    return 'applications.comments.error';
  }

  /** PATCH the body of the comment. The visibility is not patchable. */
  protected saveComment(): void {
    const comment = this.editingComment();
    const body = this.commentDraft().trim();
    if (!comment || !body || this.savingComment()) return;
    this.savingComment.set(true);
    this.api.updateComment(this.id, comment.id, body).subscribe({
      next: (updated) => {
        this.savingComment.set(false);
        this.editingComment.set(null);
        this.comments.update((list) => list.map((c) => (c.id === updated.id ? updated : c)));
        this.toast.success(this.i18n.translate('applications.comments.updated'));
      },
      error: (err: { status?: number }) => {
        this.savingComment.set(false);
        this.toast.error(this.i18n.translate(this.commentErrorKey(err.status)));
      },
    });
  }

  protected askDeleteComment(comment: ApplicationComment): void {
    this.deletingComment.set(comment);
  }

  protected doDeleteComment(): void {
    const comment = this.deletingComment();
    if (!comment || this.removingComment()) return;
    this.removingComment.set(true);
    this.api.deleteComment(this.id, comment.id).subscribe({
      next: () => {
        this.removingComment.set(false);
        this.deletingComment.set(null);
        this.comments.update((list) => list.filter((c) => c.id !== comment.id));
        this.toast.success(this.i18n.translate('applications.comments.deleted'));
      },
      error: (err: { status?: number }) => {
        this.removingComment.set(false);
        this.toast.error(this.i18n.translate(this.commentErrorKey(err.status)));
      },
    });
  }

  /** Fire a manual transition with POST /transition, then reload the application.
   *  The server checks the guard again. A 403 or a 409 answer shows a toast and
   *  refreshes. */
  fire(t: Transition): void {
    if (this.firing() !== null) return;
    this.firing.set(t.id);
    this.api.fireTransition(this.id, { transitionId: t.id }).subscribe({
      next: () => {
        this.firing.set(null);
        this.toast.success(this.i18n.translate('applications.actions.success'));
        this.changed();
      },
      error: (err: { status?: number }) => {
        this.firing.set(null);
        const key =
          err.status === 403
            ? 'applications.transitions.forbidden'
            : err.status === 409
              ? 'applications.actions.conflict'
              : 'applications.actions.error';
        this.toast.error(this.i18n.translate(key));
        this.changed();
      },
    });
  }

  /** This pane changed the application: load it again and tell the list pane. */
  private changed(): void {
    this.refresh();
    this.page?.notify({ id: this.id, kind: 'updated', source: 'detail' });
  }

  /** Reload the application and the dependent sections after a transition. The task
   *  count of the navigation changes with the state, so it is asked again too. */
  private refresh(): void {
    this.railStatus.refresh();
    const seq = this.loadSeq;
    this.api.getApplication(this.id, { quiet: true }).subscribe({
      next: (app) => {
        if (seq !== this.loadSeq) return;
        this.app.set(app);
        this.loadAux();
      },
      error: () => {},
    });
  }
}
