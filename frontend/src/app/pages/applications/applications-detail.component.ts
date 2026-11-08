import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgTemplateOutlet } from '@angular/common';
import { FormGroup, FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { ApiClient } from '@core/api/api-client.service';
import { API_BASE_URL } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type {
  ActorInfo,
  Application,
  ApplicationComment,
  ApplicationLinks,
  ApplicationListItem,
  LinkedApplication,
  ApplicationType,
  ApplicationVersion,
  FormFieldDef,
  FormSection,
  ProblemDetail,
  TimelineEntry,
  Transition,
  Uuid,
} from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
import { actorLabel } from '@shared/actor-label.util';
import { toFormlySections } from '@shared/forms/formly-mapper';
import { formatAnswer, formatFieldValue } from '@shared/forms/answer-format';
import {
  normalizePositions,
  positionValue,
  positionsTotal,
} from '@shared/forms/positions';
import { applyServerErrors, clearServerErrors } from '@shared/forms/server-errors';
import { AnswerViewComponent } from '@shared/forms/answer-view/answer-view.component';
import { PredecessorFieldComponent } from '../../features/apply/predecessor-field/predecessor-field.component';
import { ChatComponent, ChatDrafts, ChatOutbox, appendOnce, withScanStates, draftDropper, filesRefused, sendErrorKey, toChatAttachments, HistoryComponent, flowColorKind, chatPeople, type ChatEdit, type ChatPerson, type ChatMessage, type ChatRef, type ChatSend, type ChatVisibility, type HistoryChange, type HistoryEntry } from '@shared/ui';
import {
  ButtonComponent,
  ConfirmDialogComponent,
  DialogComponent,
  DropOverlayComponent,
  EmptyStateComponent,
  FieldGroupComponent,
  FieldRowComponent,
  FileDropDirective,
  IconComponent,
  ListDetailNav,
  type ListDetailTask,
  MEDIA,
  mediaQuery,
  NoteComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SelectFieldComponent,
  type SelectOption,
  SheetBarComponent,
  SheetBarTitleDirective,
  SideSheetComponent,
  StatusTextComponent,
  type TabItem,
  TabPageDirective,
  TabPagerComponent,
  TabsComponent,
  ToastService,
  FabComponent,
  SectionComponent,
} from '@stupa-makers/ui-kit';
import {
  BudgetTreeApi,
  FISCAL_YEAR_CLOSED,
  type BudgetTreeNode,
  type FiscalYear,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';
import { problemCode } from '@core/api/problem';
import { CostCentreSelectComponent } from '../budget/cost-centre-select/cost-centre-select.component';
import { AttachmentsPanelComponent } from './attachments-panel.component';
import { applicationTitle, transitionLooks } from './applications.util';
import { AgendaDialogComponent } from './agenda-dialog/agenda-dialog.component';
import { DecisionDialogComponent } from './decision-dialog/decision-dialog.component';
import { DecisionSectionComponent } from '@shared/decision/decision-section.component';
import { decisionHistoryLine } from '@shared/decision/decision.util';
import { ApplicationsPageService } from './applications-page.service';
import { ForceStatusDialogComponent } from './force-status-dialog/force-status-dialog.component';
import {
  type LinkedLead,
  TodoLinkedListComponent,
} from '../../features/todos/linked-list/todo-linked-list.component';
import { RailStatusService } from '../../layout/rail-status.service';
import { provideFormly } from '@shared/formly/formly.providers';
import { AmountComponent } from '@shared/ui/amount/amount.component';
import { formatMoney } from '@shared/format-money';
import { withoutKey } from '@shared/util/immutable';
import { pageItemTitle } from '../../layout/page-title.service';

/** Field types whose old and new value do not fit on one line of the history. The
 *  history opens them as blocks below the change ("Werte anzeigen"). */
const BLOCK_DIFF: ReadonlySet<string> = new Set(['positions', 'table', 'textarea']);

/**
 * The applications whose comments refused files in this tab (422 `application_anonymized`).
 * A reader without the PII right gets no applicant block, so this refusal is the only
 * sign of an anonymized application, and it stays for the next visit.
 */
const NO_FILES = new Set<string>();

/** The tabs of the detail when the list and the detail do not sit side by side. */
type DetailTab = 'app' | 'history' | 'files';

/** A link to the comments: `#comments`, or `#comment-<id>` for one comment. */
const COMMENTS_FRAGMENT = /^comment(?:s|-(.+))$/;

/**
 * Application detail: the sheet beside the list, or alone with tabs on a
 * narrow screen.
 *
 * Header: "<Typ> · Version n", the title, "status · gremium · amount", the firable
 * transitions as buttons, and the actions (edit, archive, and a menu with
 * Status setzen, Versionen vergleichen, Löschen, Anonymisierung beantragen). Body: the
 * details, the answers by section (`app-answer-view`), the attachments, the history
 * (status changes and versions by day) and the comments.
 *
 * A transition with `addsToAgenda` opens the agenda dialog, which asks for the meeting.
 * "Bearbeiten" turns the sheet into the edit form: the bar
 * "Antrag bearbeiten · Speichern legt Version n+1 an" with Abbrechen over the fields of
 * the form by section. The floating "Speichern" shows after the first change of a field.
 * A 422 of the server shows on its field.
 *
 * The comments run in `app-chat`, in a sheet over the page: from the end on a wide
 * screen, from the bottom on a phone. The header action "Kommentare" with the count
 * opens it. A link with `#comments` or `#comment-<id>` opens it too, and scrolls to that
 * comment. A comment is internal or public. The composer offers
 * the internal visibility only with `application.manage`. Without it, a new comment is
 * public. The author edits and deletes an own comment; the visibility stays as written.
 *
 * RBAC here only gates the UX. The server decides.
 *
 * An archived application shows a banner, because it looks like an
 * active one and someone arriving from a link has no other way to know. Every tab page stays in the
 * DOM, so the attachment count and the scroll of a list survive a tab change. The edit form has no
 * form element, so Enter in a field does not save the whole application. The comment chat exists
 * only while its sheet shows (open, or still sliding out), because projected content lives even
 * where the sheet does not render it, and a hidden chat would mark the thread as seen. The
 * page provides `ChatDrafts`, so the composer files stay with the page too.
 *
 * The component provides the field types of the form (`provideFormly`), so Formly is not
 * part of the initial bundle.
 */
@Component({
  selector: 'app-applications-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SectionComponent,
    AmountComponent,
    DropOverlayComponent,
    FileDropDirective,
    ConfirmDialogComponent,
    FabComponent,
    SheetBarComponent,
    SheetBarTitleDirective,
    NgTemplateOutlet,
    RouterLink,
    FormsModule,
    FormlyForm,
    LocalizedDatePipe,
    TranslatePipe,
    ChatComponent,
    EmptyStateComponent,
    FieldGroupComponent,
    FieldRowComponent,
    NoteComponent,
    RowMenuComponent,
    StatusTextComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    SelectFieldComponent,
    TabPageDirective,
    TabPagerComponent,
    TabsComponent,
    CostCentreSelectComponent,
    AttachmentsPanelComponent,
    AnswerViewComponent,
    HistoryComponent,
    ForceStatusDialogComponent,
    AgendaDialogComponent,
    DecisionDialogComponent,
    DecisionSectionComponent,
    TodoLinkedListComponent,
    PredecessorFieldComponent,
    SideSheetComponent,
  ],
  providers: [provideFormly(), ChatDrafts],
  templateUrl: './applications-detail.component.html',
  styleUrl: './applications-detail.component.scss',
})
export class ApplicationsDetailComponent {
  private readonly api = inject(ApiClient);
  private readonly apiBase = inject(API_BASE_URL);
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
  /** The route of the list pane: `/applications`, or `/tasks` on the tasks page. */
  readonly listPath = computed(() => this.page?.listPath() ?? ['/applications']);
  /** Phone: every header action goes into the menu. */
  readonly phone = mediaQuery(MEDIA.phone);

  readonly loading = signal(true);
  /**
   * Another application is loading while one is shown (a click on another row). The shown
   * one stays, dimmed and inert after 300ms, until the new one replaces it in one step, so
   * a switch shows no placeholder and nothing jumps.
   */
  readonly switching = signal(false);
  readonly notFound = signal(false);
  readonly error = signal(false);

  readonly app = signal<Application | null>(null);
  readonly versions = signal<ApplicationVersion[]>([]);
  readonly comments = signal<ApplicationComment[]>([]);
  /** The first read of the comments is out: the chat shows placeholder bubbles. */
  readonly commentsLoading = signal(false);
  /** The status changes of the application, oldest first. */
  readonly timeline = signal<TimelineEntry[]>([]);
  /** The Vorgänger, the Folgeanträge and the link history; null until they loaded. */
  readonly links = signal<ApplicationLinks | null>(null);
  /** The dialog that links, changes or removes the Vorgänger. */
  readonly predecessorOpen = signal(false);
  /** A change of the Vorgänger is out. */
  readonly linking = signal(false);
  /** The sections of the pinned form. Empty until it loaded, and on an error. */
  readonly sections = signal<readonly FormSection[]>([]);
  /** The form is on its way; the answers wait for it, so no raw keys flash. */
  readonly formLoading = signal(true);
  /** The type of the application has a budget: drives `visibleIf: has_budget`. */
  readonly hasBudget = signal(false);
  /** The variables of `visibleIf` and `compute` besides the answers. */
  readonly formContext = computed(() => ({ has_budget: this.hasBudget() }));
  /** Field definitions of the effective form for labels and typed values. Empty on error. */
  readonly formFields = computed<FormFieldDef[]>(() => this.sections().flatMap((s) => s.fields));
  /** The same field definitions by key. The data rows and the version diff both
   *  look a key up, so they share one map. */
  private readonly fieldByKey = computed(
    () => new Map(this.formFields().map((f) => [f.key, f])),
  );

  /** The composer offers the internal visibility only with `application.manage`. */
  readonly chatVisibilities = computed<ChatVisibility[]>(() =>
    this.canManage() ? ['public', 'internal'] : [],
  );
  /** Optimistic send: a new comment shows at once, the server answer replaces it. */
  private readonly outbox = new ChatOutbox<ApplicationComment>(
    (req) => this.api.addComment(this.id, req.body, req.visibility ?? 'public', req, req.mentions),
    (created) => this.comments.update((list) => appendOnce(list, created)),
    (err) => {
      if (filesRefused(err)) {
        NO_FILES.add(this.id);
        this.filesRefusedHere.set(true);
      }
      this.toast.error(this.i18n.translate(sendErrorKey(err, 'applications.comments.error')));
    },
    draftDropper(this.api),
  );
  /** The server refused the files of a comment on this application: it is anonymized. */
  private readonly filesRefusedHere = signal(false);
  /** The composer takes files unless the application is anonymized. */
  readonly canAttach = computed(
    () => !this.app()?.applicant?.anonymized && !this.filesRefusedHere(),
  );
  /** The "@" list of the composer: the people who read the internal comments. */
  readonly mentionables = signal<ChatPerson[]>([]);
  /** The application whose "@" list is loaded or on its way. */
  private mentionsFor: string | null = null;
  /** The comments as chat messages, the pending ones last. */
  readonly chatMessages = computed<ChatMessage[]>(() => [
    ...this.comments().map((c) => this.toChatMessage(c)),
    ...this.outbox.messages(),
  ]);

  /** The active tab of the narrow layout. */
  readonly tab = signal<DetailTab>('app');
  /** The sheet with the comments is open. */
  readonly commentsOpen = signal(false);
  /** The comment that a link names: the sheet scrolls to it once the thread is there. */
  private readonly linkedComment = signal<string | null>(null);
  private readonly injector = inject(Injector);
  /** The number of attachments, from the panel. `null` until it loaded them. */
  readonly attachmentCount = signal<number | null>(null);
  private readonly filesPanel = viewChild(AttachmentsPanelComponent);
  /**
   * Files dropped anywhere on the application become its attachments. Not while another
   * application loads, and not while the comments are open: the chat takes its own drop.
   */
  readonly takesDrop = computed(() => this.canUploadFiles() && !this.switching() && !this.commentsOpen());

  /** Upload attachments: as the server's `require_app_edit`, a manager, a holder of
   *  `application.edit_any` or the creator, in every state. */
  readonly canUploadFiles = computed(() => !!this.app()?.canEdit);
  /** Delete attachments: a manager and a holder of `application.edit_any` in every state,
   *  the creator only while the state allows the edit (else the server answers 409). */
  readonly canDeleteFiles = computed(() => {
    const app = this.app();
    if (!app?.canEdit) return false;
    return this.canManage() || app.canEditLocked || !!app.state?.editAllowed;
  });

  /** A drop on the page: the panel uploads it; in tabs, its tab opens to show the upload. */
  onFilesDropped(files: File[]): void {
    const panel = this.filesPanel();
    if (!panel) return;
    if (!this.split()) this.tab.set('files');
    panel.upload(files);
  }

  /** Manual transitions that the server guard allows, plus the fire in flight. */
  readonly transitions = signal<Transition[]>([]);
  /** The transitions are on their way: the header keeps the place of their buttons. */
  readonly transitionsLoading = signal(false);
  readonly firing = signal<Uuid | null>(null);
  /** The transition of the agenda dialog. */
  readonly agendaTransition = signal<Transition | null>(null);
  readonly agendaOpen = signal(false);
  /** The transition of the decision dialog (into an accepted state). */
  readonly decisionTransition = signal<Transition | null>(null);
  readonly decisionOpen = signal(false);
  readonly canTransition = computed(() => this.auth.can('application.transition'));

  protected readonly budgetTree = signal<BudgetTreeNode[]>([]);
  protected readonly budgetChoice = signal('');
  protected readonly assigningBudget = signal(false);
  protected readonly budgetDialogOpen = signal(false);
  /** Fiscal-year choice among the years of the top budget of the selected cost centre.
   *  An empty value means automatic. The server then derives the current year (the only
   *  active open one, else the active open one that holds today), or it answers 422. */
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
  /** Dropdown options: "automatic" plus every open fiscal year of the top budget.
   *  An inactive year carries a mark. A closed year takes no assignment, so it shows
   *  only while it is the current year of the application. */
  protected readonly fiscalOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('applications.budget.fiscalAuto') },
    ...this.fiscalYears()
      .filter((y) => !y.closedAt || y.id === this.app()?.fiscalYearId)
      .map((y) => ({
      value: y.id,
        label: y.closedAt
          ? this.i18n.translate('budget.fy.closedLabel', { year: y.display })
          : y.active
            ? y.display
            : `${y.display} (${this.i18n.translate('applications.budget.fiscalInactive')})`,
      })),
  ]);
  /** Find the top budget (root) whose subtree contains the cost centre. */
  private topLevelIdOf(budgetId: string): string | null {
    const contains = (n: BudgetTreeNode): boolean =>
      n.id === budgetId || (n.children?.some(contains) ?? false);
    return this.budgetTree().find(contains)?.id ?? null;
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

  /** Inline editing for the creator or a manager. */
  readonly editing = signal(false);
  /** The bar of the list/detail layout, present when the detail runs in it. */
  private readonly ldNav = inject(ListDetailNav, { optional: true });
  /**
   * One view at a time, the edit takes over the bar of the layout: an X in place of the
   * back arrow and "Antrag bearbeiten" as its title. The edit then has no bar of its own,
   * so the screen shows one bar, not two.
   */
  readonly editDocked = computed(() => this.editing() && !!this.ldNav?.active());
  readonly editFields = signal<FormlyFieldConfig[]>([]);
  readonly savingEdit = signal(false);
  /** A field of the edit form changed. Only then the page shows "Speichern". */
  readonly editDirty = signal(false);
  editForm = new FormGroup({});
  editModel: Record<string, unknown> = {};
  readonly confirmDelete = signal(false);
  readonly deleting = signal(false);
  readonly confirmErase = signal(false);
  readonly requestingErasure = signal(false);

  /**
   * Force status is a privileged override that needs `application.force_status`. The dialog
   * loads the flow states itself.
   */
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
  /**
   * The Vorgänger can change: the edit right on this Antrag. The server also needs the
   * edit right on the Vorgänger and answers 403 without it.
   */
  readonly canLink = computed(() => !!this.app()?.canEdit);
  /**
   * The Vorgänger and the Folgeanträge as rows of "Verknüpft". The server sends only the
   * Anträge the reader may open; an Antrag can have many Folgeanträge, so they show only
   * there, while the Vorgänger also has its row in the details.
   */
  readonly linkedRows = computed<readonly LinkedLead[]>(() => {
    const l = this.links();
    if (!l) return [];
    const t = (key: TranslationKey) => this.i18n.translate(key);
    const row = (a: LinkedApplication, kind: string): LinkedLead => ({
      icon: 'file',
      title: a.title || t('applications.list.untitled'),
      sub: kind,
      link: ['/applications', a.id],
    });
    return [
      ...(l.predecessor ? [row(l.predecessor, t('applications.predecessor.field'))] : []),
      ...l.successors.map((s) => row(s, t('applications.predecessor.successor'))),
    ];
  });
  readonly archiving = signal(false);

  /**
   * Move the application out of the working list, or bring it back.
   *
   * Reversible and destructive of nothing, so unlike the delete and the erasure request
   * it asks for no confirmation: the way back is one click on the same button.
   *
   * The archive answer carries no applicant block, so the one already shown stays.
   */
  toggleArchived(): void {
    const current = this.app();
    if (!current || this.archiving()) return;
    const next = current.archivedAt === null;
    this.archiving.set(true);
    this.api.setApplicationArchived(current.id, next).subscribe({
      next: (updated) => {
        const keep = !updated.applicant && current.applicant;
        this.app.set(keep ? { ...updated, applicant: current.applicant } : updated);
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
   * One value of the version diff on the change line, formatted the way the answers
   * show the field. Cost positions give their summary ("3 Kostenpositionen ·
   * 395,00 €"). A long text, a table or an object of an unknown key gives `null`: the
   * line names only the field, and `fmtBlock` gives the value.
   *
   * The diff carries a key, not a field definition, so the type comes from the key.
   * A key the form does not define (an answer of an older form version) keeps the
   * plain text for a scalar.
   */
  readonly fmt = (value: unknown, key?: string): string | null => {
    const field = key === undefined ? undefined : this.fieldByKey().get(key);
    if (field?.type === 'positions') return this.positionsSummary(value);
    if (field && BLOCK_DIFF.has(field.type)) return null;
    if (!field && value !== null && typeof value === 'object') return null;
    const text = field
      ? formatAnswer(field, value, {
          lang: this.i18n.uiLocale(),
          yes: this.i18n.translate('common.yes'),
          no: this.i18n.translate('common.no'),
        })
      : formatFieldValue(value);
    return text || '—';
  };

  /**
   * One value of the version diff as a block below the change line, or `null` when the
   * line holds it all. A text keeps its line breaks. The cost positions give one line
   * per position and one indented line per offer, so a changed offer shows too. A table
   * and an object of an unknown key give one line per row.
   */
  readonly fmtBlock = (value: unknown, key?: string): string | null => {
    const field = key === undefined ? undefined : this.fieldByKey().get(key);
    const block = field ? BLOCK_DIFF.has(field.type) : value !== null && typeof value === 'object';
    if (!block) return null;
    if (field?.type === 'positions') return this.positionsBlock(value) || '—';
    if (typeof value === 'string') return value.trim() ? value : '—';
    return rowLines(value) || '—';
  };

  /** "3 Kostenpositionen · 395,00 €"; the total counts the preferred offers. */
  private positionsSummary(value: unknown): string {
    const positions = normalizePositions(value);
    if (!positions.length) return '—';
    const t = this.i18n;
    const count = t.translate(
      positions.length === 1 ? 'apply.positions.countOne' : 'apply.positions.countOther',
      { count: positions.length },
    );
    return `${count} · ${this.money(positionsTotal(positions))}`;
  }

  /**
   * The cost positions, one line each ("Raummiete · 177,75 €"), with the offers below
   * ("– Studierendenwerk · 177,75 € · bevorzugt") and the reason of a position without
   * comparison offers.
   */
  private positionsBlock(value: unknown): string {
    const t = this.i18n;
    const lines = normalizePositions(value).flatMap((p) => {
      const name = p.label.trim() || t.translate('forms.positions.untitled');
      const reason = p.noOffersReason.trim();
      const short = t.translate('forms.positions.noOffersShort');
      const noOffers = p.noOffers ? [`   ${reason ? `${short}: ${reason}` : short}`] : [];
      const offers = p.offers.map((o) => {
        const preferred = o.preferred ? [t.translate('forms.positions.preferred')] : [];
        return `   – ${[o.label.trim() || '—', this.money(o.value), ...preferred].join(' · ')}`;
      });
      return [`${name} · ${this.money(positionValue(p))}`, ...noOffers, ...offers];
    });
    return lines.join('\n');
  }

  /** An amount in euro; a missing value counts as 0, as on the server. */
  private money(value: number | null): string {
    return formatMoney(value ?? 0, this.i18n.formatLocale());
  }

  /** The label of a field of the diff, or its key when the form does not define it. */
  private fieldLabel(key: string): string {
    const field = this.fieldByKey().get(key);
    return field ? resolveI18n(field.label, this.i18n.uiLocale()) : key;
  }

  /**
   * The changed fields of a version as lines of the history.
   *
   * The same summary on both sides says nothing, so the line names the field and the blocks show
   * it.
   */
  private versionChanges(version: ApplicationVersion): HistoryChange[] {
    const t = (key: TranslationKey) => this.i18n.translate(key);
    if (!version.diff) {
      return (version.changedKeys ?? []).map((key) => ({
        kind: 'warn',
        tag: t('applications.history.diff.changed'),
        label: this.fieldLabel(key),
      }));
    }
    const detail = (
      key: string,
      sides: { old?: unknown; new?: unknown },
    ): HistoryChange['detail'] => {
      const old = 'old' in sides ? this.fmtBlock(sides.old, key) : null;
      const neu = 'new' in sides ? this.fmtBlock(sides.new, key) : null;
      return old === null && neu === null ? null : { old, new: neu };
    };
    return [
      ...version.diff.changed.map((c) => {
        const more = detail(c.key, { old: c.old, new: c.new });
        const old = this.fmt(c.old, c.key);
        const neu = this.fmt(c.new, c.key);
        const same = more !== null && old === neu;
        return {
          kind: 'warn' as const,
          tag: t('applications.history.diff.changed'),
          label: this.fieldLabel(c.key),
          old: same ? null : old,
          new: same ? null : neu,
          detail: more,
        };
      }),
      ...version.diff.added.map((a) => ({
        kind: 'accent' as const,
        tag: t('applications.history.diff.added'),
        label: this.fieldLabel(a.key),
        new: this.fmt(a.value, a.key),
        detail: detail(a.key, { new: a.value }),
      })),
      ...version.diff.removed.map((r) => ({
        kind: 'error' as const,
        tag: t('applications.history.diff.removed'),
        label: this.fieldLabel(r.key),
        old: this.fmt(r.value, r.key),
        detail: detail(r.key, { old: r.value }),
      })),
    ];
  }

  /** The label of an actor: a name, "Antragsteller:in", "System · Fristen", …. */
  private actor(info: ActorInfo | null | undefined, legacy: string | null): string | null {
    return actorLabel(info, legacy, (key, params) => this.i18n.translate(key, params));
  }

  /**
   * "Verlauf": the status changes and the versions, by day (`app-history`).
   *
   * A status change shows the new state in its colour, the transition ("Übergang
   * „Prüfung beginnen“") and the note. The first status event is the submission and
   * carries "Version 1". Every later version shows its changed fields with the old and
   * the new value.
   *
   * A vote branch writes the machine note "vote:<result>", which stays hidden because the title and
   * the vote link already say the result.
   */
  readonly historyEntries = computed<HistoryEntry[]>(() => {
    const t = (key: TranslationKey, params?: Record<string, string | number>) =>
      this.i18n.translate(key, params);
    const events = [...this.timeline()].sort((a, b) => a.at.localeCompare(b.at));
    const versions = this.versions();
    const capture = this.app()?.capture ?? null;
    const firstVersion = versions.some((v) => v.version === 1);
    const statusEntries: HistoryEntry[] = events.map((e, i) => {
      const first = i === 0;
      const intake = capture?.intake
        ? [t('applications.history.intake', { intake: capture.intake })]
        : [];
      const decision = e.decision
        ? decisionHistoryLine(
            e.decision,
            this.i18n.formatLocale(),
            this.app()?.currency ?? 'EUR',
            t,
          )
        : null;
      const lines = [
        ...(first && firstVersion ? [t('applications.history.version', { version: 1 })] : []),
        ...(first && capture ? [t('applications.history.captured'), ...intake] : []),
        ...(e.transitionLabel
          ? [t('applications.history.transition', { label: e.transitionLabel })]
          : []),
        ...(e.note && !e.note.startsWith('vote:') ? [e.note] : []),
        ...(decision ? [decision] : []),
        ...(e.voteDeleted ? [t('applications.history.voteDeleted')] : []),
      ];
      return {
        at: e.at,
        icon: i === 0 ? 'send' : 'flow',
        title: e.toState?.label || e.label,
        kind: flowColorKind(e.toState?.color),
        actor: this.actor(e.actorInfo, e.actor),
        body: lines.join('\n') || null,
        link: e.voteId
          ? { label: t('applications.history.voteLink'), route: ['/voting', e.voteId] }
          : null,
      };
    });
    const versionEntries: HistoryEntry[] = versions
      .filter((v) => !(v.version === 1 && events.length))
      .map((v) => {
        const changes = v.version === 1 ? [] : this.versionChanges(v);
        return {
          at: v.at,
          icon: 'edit',
          title: t('applications.history.version', { version: v.version }),
          actor: this.actor(v.changedByInfo, v.changedBy),
          body:
            v.version === 1
              ? t('applications.history.initial')
              : changes.length
                ? null
                : t('applications.history.diff.none'),
          changes,
        };
      });
    const untitled = t('applications.list.untitled');
    const linkEntries: HistoryEntry[] = (this.links()?.events ?? []).map((e) => ({
      at: e.at,
      icon: 'link',
      title: t(
        e.action === 'set' ? 'applications.history.predecessorSet' : 'applications.history.predecessorRemoved',
      ),
      actor: this.actor(e.actorInfo, null),
      body: e.predecessor ? e.predecessor.title || untitled : t('applications.history.predecessorHidden'),
      link: e.predecessor
        ? { label: t('applications.predecessor.open'), route: ['/applications', e.predecessor.id] }
        : null,
    }));
    return [...statusEntries, ...versionEntries, ...linkEntries];
  });

  private id: Uuid = '';

  readonly title = computed(() =>
    applicationTitle(this.app()?.data, this.i18n.translate('applications.list.untitled')),
  );

  /** The application types, for "<Typ> · Version n". */
  private readonly types = signal<ApplicationType[]>([]);

  /** "<Typ> · Version n" above the title. */
  readonly typeName = computed(() => {
    const app = this.app();
    return app ? (this.types().find((t) => t.id === app.typeId)?.name ?? null) : null;
  });

  /** The status of the application as coloured text. */
  readonly stateKind = computed(() => flowColorKind(this.app()?.state?.color));

  /** The look of each transition button: main action, tonal, or danger (a rejection). */
  readonly looks = computed(() => transitionLooks(this.transitions()));

  /** The data can change: the edit button and the menu item. The edit form needs the
   *  fields of the form, so the button waits for them. `canEditLocked`
   *  (`application.edit_any`) lifts the edit lock of the state. */
  readonly canEditData = computed(() => {
    const app = this.app();
    const unlocked = !!app?.state?.editAllowed || !!app?.canEditLocked;
    return !!app?.canEdit && unlocked && this.sections().length > 0;
  });

  /** The owner may ask for the anonymization of their data (GDPR Art. 17). */
  readonly canRequestErasure = computed(() => {
    const app = this.app();
    return !!app?.isOwner && !app.applicant?.anonymized;
  });

  /**
   * The header menu. On a phone it also holds the actions that wider screens show as
   * icon buttons (edit, archive).
   */
  readonly menuSections = computed<RowMenuSection[]>(() => {
    const app = this.app();
    if (!app) return [];
    const t = (key: TranslationKey) => this.i18n.translate(key);
    const when = (shown: boolean, item: RowMenuItem): RowMenuItem[] => (shown ? [item] : []);
    const phone = this.phone();
    const quick = [
      ...when(phone && this.canEditData(), {
        id: 'edit',
        label: t('applications.detail.edit'),
        icon: 'edit',
      }),
      ...when(phone && this.canArchive(), {
        id: 'archive',
        label: t(app.archivedAt ? 'applications.row.unarchive' : 'applications.row.archive'),
        icon: 'archive',
      }),
    ];
    const more = [
      ...when(this.canForceStatus(), {
        id: 'force',
        label: t('applications.detail.forceStatus'),
        icon: 'flow',
      }),
      ...when(this.versions().length > 1, {
        id: 'versions',
        label: t('applications.detail.compareVersions'),
        icon: 'history',
      }),
    ];
    const danger = [
      ...when(this.canDelete(), {
        id: 'delete',
        label: t('applications.detail.delete'),
        icon: 'trash',
        danger: true,
      }),
      ...when(this.canRequestErasure(), {
        id: 'erase',
        label: t('applications.detail.eraseRequest'),
        icon: 'user',
        danger: true,
      }),
    ];
    return [{ items: quick }, { items: more }, { items: danger }].filter((sec) => sec.items.length);
  });

  /** The tabs of the narrow layout, with their counts. */
  readonly tabs = computed<TabItem[]>(() => [
    { id: 'app', label: this.i18n.translate('applications.detail.tab.app') },
    {
      id: 'history',
      label: this.i18n.translate('applications.detail.tab.history'),
      count: this.historyEntries().length,
    },
    {
      id: 'files',
      label: this.i18n.translate('applications.detail.tab.files'),
      count: this.attachmentCount(),
    },
  ]);

  /**
   * It subscribes to `paramMap`, not `snapshot`, because Angular reuses the component on a
   * detail-to-detail navigation and the constructor does not run again.
   */
  constructor() {
    pageItemTitle(() => (this.app() ? this.title() : null));
    this.dockEditInBar();
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.loadApplication(pm.get('id') ?? '');
    });
    this.route.fragment.pipe(takeUntilDestroyed()).subscribe((f) => this.openFromLink(f));
    effect(() => {
      const id = this.linkedComment();
      if (!id || !this.commentsOpen() || this.commentsLoading() || this.loading()) return;
      afterNextRender(
        () => {
          const el = document.querySelector(`[data-msg-id="${CSS.escape(id)}"]`);
          el?.scrollIntoView?.({ block: 'center' });
          this.linkedComment.set(null);
        },
        { injector: this.injector },
      );
    });
    effect(() => {
      if (this.commentsOpen() && !this.loading() && this.app() !== null)
        untracked(() => this.loadMentionables());
    });
    this.api.applicationTypes({ quiet: true }).subscribe({
      next: (types) => this.types.set(types),
      error: () => this.types.set([]),
    });
    this.page?.changes$.pipe(takeUntilDestroyed()).subscribe((change) => {
      if (change.source === 'list' && change.id === this.id && change.kind === 'updated') {
        this.refresh();
      }
    });
  }

  /** A tab of the narrow layout was chosen. */
  selectTab(id: string | null): void {
    if (id === 'app' || id === 'history' || id === 'files') this.tab.set(id);
  }

  /** The fragment of the URL: `#comments` or `#comment-<id>` opens the comments. */
  private openFromLink(fragment: string | null | undefined): void {
    const hit = COMMENTS_FRAGMENT.exec(fragment ?? '');
    if (!hit) return;
    this.commentsOpen.set(true);
    this.linkedComment.set(hit[1] ?? null);
  }

  /** An item of the header menu was chosen. */
  onMenu(item: RowMenuItem): void {
    const app = this.app();
    if (!app) return;
    switch (item.id) {
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

  /** Load sequence number that guards against a late response.
   *  A fast switch between detail pages can deliver a response of an earlier
   *  application. Such a response must not overwrite the current one. Each response
   *  checks that it still belongs to the latest load. */
  private loadSeq = 0;

  /** The comments of the shown application have been read once. */
  private commentsLoaded = false;

  /** Load the application again after a failed load. */
  protected retry(): void {
    this.loadApplication(this.id);
  }

  /**
   * The effective form comes from the pinned version of the application, not from the active one,
   * so the labels and the edit fields match the data that the server validates.
   */
  private loadApplication(id: Uuid): void {
    this.id = id;
    this.loadSeq = this.loadSeq + 1;
    const seq = this.loadSeq;
    this.commentsLoaded = false;
    this.mentionsFor = null;
    this.mentionables.set([]);
    this.editing.set(false);
    this.confirmDelete.set(false);
    this.outbox.clear();
    this.filesRefusedHere.set(NO_FILES.has(id));
    this.agendaOpen.set(false);
    this.commentsOpen.set(false);
    this.openFromLink(this.route.snapshot.fragment);
    if (id && this.app() !== null && !this.notFound() && !this.error()) {
      this.switching.set(true);
    } else {
      this.switching.set(false);
      this.resetShown();
      this.loading.set(Boolean(id));
    }
    if (!id) {
      this.notFound.set(true);
      return;
    }
    let shown = false;
    this.api.getApplication(id, { quiet: true, detail: true }).subscribe({
      next: (app) => {
        if (seq !== this.loadSeq) return;
        if (shown) {
          this.app.set(app);
          return;
        }
        shown = true;
        this.resetShown();
        this.switching.set(false);
        this.app.set(app);
        this.loading.set(false);
        this.loadAux(true);
        this.api.applicationForm(app.id, { detail: true }).subscribe({
          next: (eff) => {
            if (seq !== this.loadSeq) return;
            this.sections.set(eff.sections);
            this.hasBudget.set(eff.hasBudget);
            this.formLoading.set(false);
          },
          error: () => {
            if (seq !== this.loadSeq) return;
            this.sections.set([]);
            this.formLoading.set(false);
          },
        });
      },
      error: (err: { status?: number }) => {
        if (seq !== this.loadSeq) return;
        this.resetShown();
        this.switching.set(false);
        this.loading.set(false);
        if (err.status === 404) this.notFound.set(true);
        else this.error.set(true);
      },
    });
  }

  /** Clear everything that belongs to the shown application, so nothing of it stays. */
  private resetShown(): void {
    this.app.set(null);
    this.versions.set([]);
    this.comments.set([]);
    this.timeline.set([]);
    this.links.set(null);
    this.predecessorOpen.set(false);
    this.sections.set([]);
    this.formLoading.set(true);
    this.hasBudget.set(false);
    this.editing.set(false);
    this.confirmDelete.set(false);
    this.notFound.set(false);
    this.error.set(false);
    this.transitions.set([]);
    this.agendaOpen.set(false);
    this.attachmentCount.set(null);
    this.tab.set('app');
    this.transitionsLoading.set(false);
  }

  /**
   * A Vorgänger is picked in the dialog: the link changes at once, the answers stay. A
   * refusal gets its own text: no edit right on the Vorgänger, or a chain that would lead
   * back to this Antrag.
   */
  setPredecessor(item: ApplicationListItem): void {
    if (this.linking()) return;
    const seq = this.loadSeq;
    this.linking.set(true);
    this.api.setPredecessor(this.id, item.id).subscribe({
      next: (links) => {
        this.linking.set(false);
        if (seq !== this.loadSeq) return;
        this.links.set(links);
        this.predecessorOpen.set(false);
        this.toast.success(this.i18n.translate('applications.predecessor.linked'));
      },
      error: (err: { status?: number; error?: ProblemDetail | null }) => {
        this.linking.set(false);
        this.toast.error(this.i18n.translate(predecessorErrorKey(err.status, err.error?.code)));
      },
    });
  }

  /** "Vorgänger entfernen": only the link goes. */
  removePredecessor(): void {
    if (this.linking()) return;
    const seq = this.loadSeq;
    this.linking.set(true);
    this.api.removePredecessor(this.id).subscribe({
      next: () => {
        this.predecessorOpen.set(false);
        this.api.applicationLinks(this.id, { quiet: true }).subscribe({
          next: (links) => {
            this.linking.set(false);
            if (seq === this.loadSeq) this.links.set(links);
          },
          error: () => this.linking.set(false),
        });
        this.toast.success(this.i18n.translate('applications.predecessor.removed'));
      },
      error: (err: { status?: number; error?: ProblemDetail | null }) => {
        this.linking.set(false);
        this.toast.error(this.i18n.translate(predecessorErrorKey(err.status, err.error?.code)));
      },
    });
  }

  /**
   * Read the comments again in the background, for the scan state of their files. Only
   * the scan states change: the read can be older than a comment, an edit or a delete
   * that ended while it was in flight. A failure keeps the thread as it is.
   */
  protected refreshComments(): void {
    const seq = this.loadSeq;
    this.api.comments(this.id, { quiet: true }).subscribe({
      next: (c) => {
        if (seq === this.loadSeq) this.comments.update((list) => withScanStates(list, c));
      },
      error: () => {},
    });
  }

  /** Load the versions, the comments and the available transitions.
   *  An error degrades silently to an empty result. The transitions load only with
   *  the needed permission. The server filters them again. `detail`: the first read of
   *  an opened application, which takes what the list read ahead.
   *
   * Every reader loads the cost-centre tree (the server scopes it), so the row names the cost
   * centre also for a reader without `application.manage`; only the "Ändern" button needs that
   * right.
   */
  private loadAux(detail = false): void {
    const seq = this.loadSeq;
    this.api.versions(this.id, { detail }).subscribe({
      next: (v) => {
        if (seq === this.loadSeq) this.versions.set(v);
      },
      error: () => {},
    });
    if (!this.commentsLoaded) this.commentsLoading.set(true);
    this.api.comments(this.id, { quiet: true, detail }).subscribe({
      next: (c) => {
        if (seq !== this.loadSeq) return;
        this.comments.set(c);
        this.commentsLoaded = true;
        this.commentsLoading.set(false);
      },
      error: () => {
        if (seq === this.loadSeq) this.commentsLoading.set(false);
      },
    });
    this.api.timeline(this.id, { quiet: true, detail }).subscribe({
      next: (events) => {
        if (seq === this.loadSeq) this.timeline.set(events);
      },
      error: () => {},
    });
    this.api.applicationLinks(this.id, { detail }).subscribe({
      next: (links) => {
        if (seq === this.loadSeq) this.links.set(links);
      },
      error: () => {},
    });
    if (this.canTransition()) {
      this.transitionsLoading.set(true);
      this.api.transitions(this.id, { detail }).subscribe({
        next: (t) => {
          if (seq !== this.loadSeq) return;
          this.transitions.set(t);
          this.transitionsLoading.set(false);
        },
        error: () => {
          if (seq !== this.loadSeq) return;
          this.transitions.set([]);
          this.transitionsLoading.set(false);
        },
      });
    }
    if (this.canManage()) {
      this.budgetChoice.set(this.app()?.budgetId ?? '');
      this.fiscalChoice.set(this.app()?.fiscalYearId ?? '');
    }
    this.budgetApi.tree().subscribe({
      next: (tree) => {
        if (seq !== this.loadSeq) return;
        this.budgetTree.set(tree);
        this.loadFiscalYears(this.app()?.budgetId ?? null);
      },
      error: () => {
        if (seq === this.loadSeq) this.budgetTree.set([]);
      },
    });
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
            problemCode(err) === FISCAL_YEAR_CLOSED
              ? 'budget.fy.closedError'
              : err.status === 422
                ? 'applications.budget.invalid'
                : err.status === 403
                  ? 'applications.transitions.forbidden'
                  : 'applications.actions.error';
          this.toast.error(this.i18n.translate(key));
        },
      });
  }

  amount(app: Application): string {
    if (app.amount === null) return this.i18n.translate('applications.detail.notProvided');
    return formatMoney(app.amount, this.i18n.formatLocale(), { currency: app.currency }) || app.amount;
  }

  /**
   * The approved amount when it deviates from the requested one, else `''`. The
   * header and the cost centre then name it next to the struck requested amount.
   */
  approvedAmount(app: Application): string {
    if (app.approvedAmount === null || app.approvedAmount === undefined || app.amount === null) return '';
    if (Number(app.approvedAmount) === Number(app.amount)) return '';
    return formatMoney(app.approvedAmount, this.i18n.formatLocale(), { currency: app.currency });
  }

  /**
   * A reader without the PII right gets `data` without the isPII fields, and the server names them
   * in `hiddenKeys`. The form leaves them out, because the server keeps their stored values anyway;
   * a key that is only missing from `data` was never answered, so that field stays editable.
   */
  startEdit(app: Application): void {
    this.editFields.set(
      toFormlySections(this.sections(), this.i18n.uiLocale(), this.formContext(), {
        omitKeys: app.hiddenKeys ?? [],
      }),
    );
    this.editModel = structuredClone(app.data);
    this.editForm = new FormGroup({});
    this.editDirty.set(false);
    this.editing.set(true);
  }

  cancelEdit(): void {
    this.editing.set(false);
  }

  /** Hand the edit to the bar of the layout while it docks there (`editDocked`). */
  private dockEditInBar(): void {
    const nav = this.ldNav;
    if (!nav) return;
    let mine: ListDetailTask | null = null;
    const release = () => {
      if (mine && nav.task() === mine) nav.task.set(null);
      mine = null;
    };
    effect(() => {
      if (!this.editDocked()) {
        untracked(release);
        return;
      }
      const task: ListDetailTask = {
        title: this.i18n.translate('applications.edit.title'),
        cancelLabel: this.i18n.translate('action.cancel'),
        cancel: () => this.cancelEdit(),
      };
      untracked(() => {
        mine = task;
        nav.task.set(task);
      });
    });
    inject(DestroyRef).onDestroy(release);
  }

  /**
   * Save the edit as a new version (PATCH). An invalid form shows its errors and sends
   * nothing. A 422 of the server shows on the fields it names (for example a cost
   * position without an offer); a 409 means the state no longer allows an edit.
   */
  saveEdit(): void {
    if (this.savingEdit()) return;
    clearServerErrors(this.editFields());
    if (this.editForm.invalid) {
      this.editForm.markAllAsTouched();
      this.toast.error(this.i18n.translate('applications.edit.invalid'));
      this.revealError();
      return;
    }
    this.savingEdit.set(true);
    this.api.updateApplication(this.id, { ...this.editModel }).subscribe({
      next: (updated) => {
        this.savingEdit.set(false);
        this.editing.set(false);
        this.toast.success(
          this.i18n.translate('applications.edit.saved', { version: updated.version }),
        );
        this.changed();
      },
      error: (err: { status?: number; error?: ProblemDetail | null }) => {
        this.savingEdit.set(false);
        if (err.status === 422 && err.error?.errors?.length) {
          const placed = applyServerErrors(this.editFields(), err.error.errors, (key) =>
            this.i18n.translate(key),
          );
          if (placed) {
            this.toast.error(this.i18n.translate('applications.edit.invalid'));
            this.revealError();
            return;
          }
        }
        const key =
          err.status === 409 ? 'applications.detail.locked' : 'applications.detail.saveFailed';
        this.toast.error(this.i18n.translate(key));
      },
    });
  }

  /** Scroll the first field with an error into view, after the form drew it. */
  private revealError(): void {
    setTimeout(() => {
      const el = document.querySelector<HTMLElement>(
        '.ad__edit [aria-invalid="true"], .ad__edit [role="alert"]',
      );
      el?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
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
        void this.router.navigate([...this.listPath()], { queryParamsHandling: 'preserve' });
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
    const info =
      comment.authorInfo ?? (comment.authorKind === 'applicant' ? { kind: 'applicant' as const } : null);
    return (
      this.actor(info, comment.author) ??
      this.i18n.translate('applications.comments.author.committee')
    );
  }

  /** A comment as a chat message. The author keeps its avatar where the server sends
   *  the account id; the applicant and the Gremium show initials. */
  private toChatMessage(comment: ApplicationComment): ChatMessage {
    return {
      id: comment.id,
      author: {
        principalId: comment.authorInfo?.principalId ?? null,
        displayName: this.authorName(comment),
      },
      body: comment.body,
      at: comment.at,
      editedAt: comment.editedAt,
      own: comment.isOwn,
      canEdit: comment.isOwn || this.canManage(),
      visibility: comment.visibility,
      attachments: toChatAttachments(this.apiBase, comment.attachments),
      mentions: comment.mentions,
    };
  }

  /**
   * Load the "@" list once the comments open, once per application. Only a member reads
   * it; the creator who reads as the applicant gets 403 and no list.
   */
  private loadMentionables(): void {
    const id = this.id;
    if (this.mentionsFor === id) return;
    this.mentionsFor = id;
    this.api.mentionable(id).subscribe({
      next: (people) => {
        if (this.id === id) this.mentionables.set(chatPeople(people));
      },
      error: () => {
        if (this.id === id) this.mentionables.set([]);
      },
    });
  }

  /** Without `application.manage` the composer has no toggle, so the comment is public. */
  protected sendComment(req: ChatSend): void {
    const comment: ChatSend = this.canManage() ? { ...req } : withoutKey(req, 'visibility');
    this.outbox.send(comment);
  }

  protected retryComment(ref: ChatRef): void {
    this.outbox.retry(ref.id);
  }

  protected discardComment(ref: ChatRef): void {
    this.outbox.discard(ref.id);
  }

  /** Translation key for a failed comment change. 403 and 404 read as reasons. */
  private commentErrorKey(status: number | undefined): TranslationKey {
    if (status === 403) return 'applications.comments.forbidden';
    if (status === 404) return 'applications.comments.gone';
    return 'applications.comments.error';
  }

  /** PATCH the body of the comment. The visibility is not patchable. */
  protected editComment(change: ChatEdit): void {
    this.api.updateComment(this.id, change.id, change.body, change.mentions).subscribe({
      next: (updated) => {
        this.comments.update((list) => list.map((c) => (c.id === updated.id ? updated : c)));
      },
      error: (err: { status?: number }) => {
        change.restore?.();
        this.toast.error(this.i18n.translate(this.commentErrorKey(err.status)));
      },
    });
  }

  protected deleteComment(ref: ChatRef): void {
    this.api.deleteComment(this.id, ref.id).subscribe({
      next: () => {
        this.comments.update((list) => list.filter((c) => c.id !== ref.id));
      },
      error: (err: { status?: number }) => {
        this.toast.error(this.i18n.translate(this.commentErrorKey(err.status)));
      },
    });
  }

  /** Fire a manual transition with POST /transition, then reload the application.
   *  The server checks the guard again. A 403 or a 409 answer shows a toast and
   *  refreshes. */
  fire(t: Transition): void {
    if (this.firing() !== null) return;
    if (t.addsToAgenda) {
      this.agendaTransition.set(t);
      this.agendaOpen.set(true);
      return;
    }
    if (t.allowsDecision) {
      this.decisionTransition.set(t);
      this.decisionOpen.set(true);
      return;
    }
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

  /** The agenda dialog fired its transition. */
  onAgendaDone(): void {
    this.changed();
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

/**
 * A table answer, or an object of an unknown key, as lines: one row each, the cells as
 * "Spalte: Wert" joined by a dot. A scalar row keeps its text.
 */
function rowLines(value: unknown): string {
  const cell = (v: unknown): string =>
    v !== null && typeof v === 'object' ? JSON.stringify(v) : formatFieldValue(v);
  const row = (r: unknown): string =>
    r !== null && typeof r === 'object' && !Array.isArray(r)
      ? Object.entries(r as Record<string, unknown>)
          .map(([k, v]) => `${k}: ${cell(v)}`)
          .join(' · ')
      : cell(r);
  if (Array.isArray(value)) return value.map(row).join('\n');
  if (value !== null && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${cell(v)}`)
      .join('\n');
  }
  return formatFieldValue(value);
}

/** The text of a refused Vorgänger change, by the status and the problem code. */
export function predecessorErrorKey(status: number | undefined, code: string | null | undefined): TranslationKey {
  switch (code) {
    case 'predecessor_cycle':
      return 'applications.predecessor.errorCycle';
    case 'predecessor_type_mismatch':
      return 'applications.predecessor.errorType';
    default:
      return status === 403 ? 'applications.predecessor.errorForbidden' : 'applications.predecessor.error';
  }
}
