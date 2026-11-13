import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Location, NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { type Observable, forkJoin, of } from 'rxjs';
import { catchError, finalize, tap } from 'rxjs/operators';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  ConfirmDialogComponent,
  downloadBlob,
  CurrencyInputComponent,
  DataTableComponent,
  DialogComponent,
  EmptyStateComponent,
  FabComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  IconComponent,
  type IconName,
  MEDIA,
  mediaQuery,
  NoteComponent,
  PageHeaderComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ScrollFadeDirective,
  SearchPillComponent,
  SectionComponent,
  SegmentedComponent,
  SelectFieldComponent,
  type SelectOption,
  SheetBarComponent,
  SheetBarTitleDirective,
  SideSheetComponent,
  SkeletonComponent,
  StatusTextComponent,
  type Step,
  StepperComponent,
  SwitchComponent,
  TextareaComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { FeatureService } from '@core/features/feature.service';
import { errorStatus, problemCode } from '@core/api/problem';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { SimplifyPathPipe } from '@shared/budget-path';
import { formatMoney } from '@shared/format-money';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import { pageItemTitle } from '../../../layout/page-title.service';
import { AdminApiService } from '../../admin/admin-api.service';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from '../budget-tree.api';
import { CostCentreCreateComponent, type CostCentreCreated } from '../cost-centre/cost-centre-create.component';
import { CostCentreSettingsComponent } from '../cost-centre/cost-centre-settings.component';
import { CostCentreSelectComponent } from '../cost-centre-select/cost-centre-select.component';
import { costCentreError, createKey, findNode, levelKey, withDescendants } from '../cost-centre/cost-centre.util';
import { defaultFiscalYearId } from '../fiscal-year.util';
import {
  BudgetPlanApi,
  type BudgetPlan,
  type ManualState,
  type PlanExportFormat,
  type PlanLineSet,
  type PlanState,
  type PlanStep,
  type PlanMeeting,
  type PlanVersion,
  type Side,
} from './budget-plan.api';
import {
  type PlanGroup,
  type PlanRow,
  addable,
  amountProblem,
  cents,
  currentVersion,
  groupOf,
  inForce,
  nextStep,
  planRows,
  planTree,
  sideSum,
  stepIndex,
  versionBefore,
  voteRuns,
  voteStep,
} from './budget-plan.util';

/** The plan of the selected year: not loaded yet, failed, absent or present. */
type PlanLoad =
  | { readonly kind: 'loading' }
  | { readonly kind: 'error' }
  | { readonly kind: 'none' }
  | { readonly kind: 'plan'; readonly plan: BudgetPlan };

/** The action of the detail head that moves the version on. */
interface PrimaryAction {
  readonly id: string;
  readonly label: string;
  readonly icon: IconName;
  /** Why the action cannot run now, or `null`. */
  readonly reason: string | null;
}

/** A step that waits for the confirmation of the person. */
type Ask =
  | { readonly kind: 'inForce' | 'backToDraft' | 'deleteDraft' }
  | { readonly kind: 'step'; readonly name: string }
  | { readonly kind: 'removeLine' | 'deleteNode'; readonly row: PlanRow };

/** The actions of the head, of the menus and of the floating button. */
const ACTIONS = [
  'createPlan',
  'inForce',
  'backToDraft',
  'deleteDraft',
  'step',
  'removeLine',
  'deleteNode',
  'nachtrag',
  'add',
  'new',
  'request',
  'openVote',
  'openMeeting',
  'setState',
  'exportPdf',
  'exportXlsx',
] as const;
type ActionId = (typeof ACTIONS)[number];

/** The texts of the confirmation dialog of an {@link Ask}. */
interface AskView {
  readonly title: string;
  readonly body: string;
  readonly confirmLabel: string;
  readonly danger: boolean;
}

/** The problem codes of a plan write that have their own message. */
const WRITE_ERRORS: Readonly<Record<string, TranslationKey>> = {
  plan_blocked_above_amount: 'budget.plan.error.blockedAbove',
  plan_line_has_children: 'budget.plan.error.hasChildren',
  plan_not_balanced: 'budget.plan.error.notBalanced',
  plan_version_locked: 'budget.plan.error.locked',
  plan_state_invalid: 'budget.plan.error.stateInvalid',
  plan_no_step_left: 'budget.plan.error.stateInvalid',
  plan_step_no_gremium: 'budget.plan.error.stepNoGremium',
  plan_step_vote_runs: 'budget.plan.error.stepVoteRuns',
  plan_step_waits: 'budget.plan.error.stepWaits',
  plan_step_has_vote: 'budget.plan.error.stepHasVote',
  plan_exists: 'budget.plan.error.exists',
  plan_draft_exists: 'budget.plan.error.draftExists',
  plan_not_in_force: 'budget.plan.error.notInForce',
  plan_marks_income: 'budget.plan.error.marksIncome',
  plan_not_enabled: 'budget.plan.error.notEnabled',
  plan_copy_source_invalid: 'budget.plan.error.copySource',
  plan_line_node_invalid: 'budget.plan.error.lineNode',
  plan_amount_too_large: 'budget.plan.error.amountTooLarge',
  plan_empty: 'budget.plan.error.empty',
  plan_side_missing: 'budget.plan.error.sideMissing',
  plan_step_invalid: 'budget.plan.error.stateInvalid',
  side_not_settable: 'budget.cc.error.sideNotSettable',
  plan_step_not_next: 'budget.plan.error.stepNotNext',
  plan_in_progress: 'budget.plan.error.inProgress',
  fiscal_year_closed: 'budget.fy.closedError',
};

/** From this width, a wide plan table shows the column "Änderung" beside the year before. */
const ROOMY = '(min-width: 1340px)';
const MONEY_COL = '6.75rem';
const FIELD_COL = '10rem';
/** The first Ansatz that the narrow amount field of a table cuts. */
const WIDE_FROM = 10_000_000;

/**
 * The view "Planung" of the Budget tab: the Haushaltsplan of a fiscal year in the list and
 * detail geometry of the tab. The list shows the Kostenstellen of the plan with their Ansatz,
 * the detail shows the plan or one line. A draft is edited in the tables, and each field saves
 * when the person leaves it.
 */
@Component({
  selector: 'app-budget-plan',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    FormsModule,
    TranslatePipe,
    SimplifyPathPipe,
    LoadErrorComponent,
    ButtonComponent,
    CellDirective,
    ConfirmDialogComponent,
    CostCentreCreateComponent,
    CostCentreSelectComponent,
    CostCentreSettingsComponent,
    CurrencyInputComponent,
    DataTableComponent,
    DialogComponent,
    EmptyStateComponent,
    FabComponent,
    FilterSelectComponent,
    IconComponent,
    NoteComponent,
    PageHeaderComponent,
    RowMenuComponent,
    ScrollFadeDirective,
    SearchPillComponent,
    SectionComponent,
    SegmentedComponent,
    SelectFieldComponent,
    SheetBarComponent,
    SheetBarTitleDirective,
    SideSheetComponent,
    SkeletonComponent,
    StatusTextComponent,
    StepperComponent,
    SwitchComponent,
    TextareaComponent,
  ],
  templateUrl: './budget-plan.component.html',
  styleUrls: ['../budget-dashboard.component.scss', './budget-plan.component.scss'],
  host: { '[class.pane-page]': 'wide()' },
})
export class BudgetPlanComponent {
  private readonly treeApi = inject(BudgetTreeApi);
  private readonly api = inject(BudgetPlanApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly features = inject(FeatureService);
  private readonly adminApi = inject(AdminApiService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly destroyRef = inject(DestroyRef);
  /** The component is destroyed: a late answer writes no URL. */
  private gone = false;
  private readonly location = inject(Location);

  readonly wide = mediaQuery(MEDIA.wide);
  readonly phone = mediaQuery(MEDIA.phone);
  /**
   * The window has room for every column of the tables. Between the wide breakpoint and
   * this width, the table of a plan with the two columns of the year before drops the
   * column "Änderung", because the name column else keeps about 110 px and a name or a
   * Vermerk of a deep Kostenstelle breaks into lines of one or two letters.
   */
  readonly roomy = mediaQuery(ROOMY);

  readonly loading = signal(true);
  readonly error = signal(false);
  private readonly tree = signal<readonly BudgetTreeNode[]>([]);
  private readonly years = signal<readonly FiscalYear[]>([]);
  readonly topId = signal('');
  readonly fyId = signal('');
  /** The chosen version; '' follows {@link currentVersion}. */
  private readonly versionId = signal('');
  /** The number of the version that the URL names, until the plan is loaded. */
  private wantedVersion: number | null = null;
  /** The bottom sheet is its own history entry, so "back" closes it. */
  private sheetPushed = false;
  /**
   * The selected Kostenstelle; '' is the top-level one, so the detail shows the plan.
   * Beside the list the detail shows it, on a narrow screen the bottom sheet does.
   */
  readonly selId = signal('');
  readonly query = signal('');
  readonly load = signal<PlanLoad>({ kind: 'loading' });
  /** The plan of the year before, for the columns of the year before. */
  private readonly prevPlan = signal<BudgetPlan | null>(null);
  readonly busy = signal(false);
  /** The step that waits for its confirmation. */
  readonly ask = signal<Ask | null>(null);
  readonly addOpen = signal(false);
  readonly addId = signal('');
  readonly createOpen = signal(false);
  readonly gremiumOptions = signal<readonly SelectOption[]>([]);
  /** The amounts and the Erläuterung a person typed and did not leave yet, by row id and field. */
  private readonly edits = signal<Readonly<Record<string, string>>>({});

  readonly modeOptions = computed(() => [
    { value: 'run', label: this.i18n.translate('budget.view.run') },
    { value: 'plan', label: this.i18n.translate('budget.view.plan') },
  ]);

  /** The top-level Kostenstellen with the plan switch on. */
  readonly tops = computed(() => this.tree().filter((n) => !n.parentId && n.planEnabled));
  readonly top = computed(() => this.tops().find((t) => t.id === this.topId()) ?? null);
  readonly topOptions = computed<readonly FilterSelectOption[]>(() =>
    this.tops().map((t) => ({ value: t.id, label: t.name })),
  );
  /** The budget chip: "Budget: VS-Mittel". */
  readonly topChip = computed(() => this.chip('budget.cc.budget', this.top()?.name));
  readonly year = computed(() => this.years().find((y) => y.id === this.fyId()) ?? null);
  /** The fiscal year before the selected one. */
  readonly prevYear = computed(() => {
    const year = this.year();
    return (year && this.years().find((y) => y.year === year.year - 1)) ?? null;
  });
  readonly yearOptions = computed<readonly FilterSelectOption[]>(() =>
    this.years().map((y) => ({
      value: y.id,
      label: this.i18n.translate(y.closedAt ? 'budget.dash.yearShortClosed' : 'budget.dash.yearShort', {
        year: y.display,
      }),
    })),
  );

  readonly plan = computed(() => {
    const load = this.load();
    return load.kind === 'plan' ? load.plan : null;
  });
  readonly versions = computed(() => this.plan()?.versions ?? []);
  readonly version = computed<PlanVersion | null>(
    () => this.versions().find((v) => v.id === this.versionId()) ?? currentVersion(this.versions()),
  );
  readonly versionOptions = computed<readonly FilterSelectOption[]>(() =>
    [...this.versions()].reverse().map((v) => ({ value: v.id, label: this.versionName(v) })),
  );
  /** The version chip: "Version: Stammplan". */
  readonly versionChip = computed(() => {
    const version = this.version();
    return this.chip('budget.plan.version.label', version ? this.versionName(version) : null);
  });
  /** The version before the shown one, when the shown version is a Nachtrag. */
  readonly base = computed(() => {
    const version = this.version();
    return version ? versionBefore(this.versions(), version) : null;
  });
  readonly nachtrag = computed(() => this.base() !== null);

  readonly canWrite = computed(() => this.auth.can('budget.structure'));
  readonly editable = computed(
    () => this.canWrite() && this.version()?.state === 'draft' && !this.year()?.closedAt,
  );
  /** The tables show amount fields only beside the list, so a phone edits in the sheet. */
  readonly tableFields = computed(() => this.editable() && this.wide());

  readonly rows = computed<readonly PlanRow[]>(() => {
    const top = this.top();
    const version = this.version();
    if (!top || !version) return [];
    return planRows({
      top,
      version,
      base: this.base(),
      prev: inForce(this.prevPlan()?.versions ?? []),
      prevFiscalYearId: this.prevYear()?.id ?? null,
    });
  });
  /** The rows of the tables. On a narrow screen the search of the page filters them. */
  private readonly tableRows = computed(() => (this.wide() ? this.rows() : this.listRows()));
  /** The rows of the table of a group: a side, or the Titel without one. */
  rowsOf(group: PlanGroup): readonly PlanRow[] {
    return this.tableRows().filter((r) => groupOf(r) === group);
  }
  readonly groupOf = groupOf;
  /** A Titel of the version has no side yet, so the version stays a draft. */
  private readonly unsided = computed(() => this.rows().some((r) => r.side === null));
  readonly incomeTotal = computed(() => sideSum(this.rows(), 'income'));
  readonly expenseTotal = computed(() => sideSum(this.rows(), 'expense'));
  readonly difference = computed(() => (cents(this.incomeTotal()) - cents(this.expenseTotal())) / 100);
  readonly balanced = computed(() => this.difference() === 0);
  /** The groups of the list and the tables. The Titel without a side stand first, and only while there is one. */
  readonly groups = computed<readonly { readonly side: PlanGroup; readonly heading: string; readonly total: number | null }[]>(() => [
    ...(this.unsided() ? [{ side: 'none' as const, heading: this.i18n.translate('budget.plan.side.none'), total: null }] : []),
    { side: 'income' as const, heading: this.i18n.translate('budget.plan.income'), total: this.incomeTotal() },
    { side: 'expense' as const, heading: this.i18n.translate('budget.plan.expense'), total: this.expenseTotal() },
  ]);
  readonly sideOptions = computed<SelectOption[]>(() => [
    { value: 'income', label: this.i18n.translate('budget.plan.side.income') },
    { value: 'expense', label: this.i18n.translate('budget.plan.side.expense') },
  ]);

  /** The rows of the list, filtered by the search text. */
  readonly listRows = computed(() => {
    const q = this.query().trim().toLowerCase();
    return q
      ? this.rows().filter((r) => r.name.toLowerCase().includes(q) || r.pathKey.toLowerCase().includes(q))
      : this.rows();
  });

  /** The selected row, whatever shows it. */
  private readonly picked = computed(() => this.rows().find((r) => r.id === this.selId()) ?? null);
  /** The row of the detail beside the list. */
  readonly sel = computed(() => (this.wide() ? this.picked() : null));
  /** The row of the bottom sheet on a narrow screen. */
  readonly sheetRow = computed(() => (this.wide() ? null : this.picked()));
  /** The direct child rows of the selected Kostenstelle. */
  readonly childRows = computed(() => this.rows().filter((r) => r.parentId === this.selId()));

  /** The step display: "Entwurf", each step of the version by its name, "In Kraft". */
  readonly steps = computed<Step[]>(() => {
    const version = this.version();
    return [
      { label: this.stateLabel('draft'), hint: null },
      ...(version?.steps ?? []).map((step) => ({ label: step.name, hint: this.stepHint(step, version) })),
      { label: this.stateLabel('in_force'), hint: version?.inForceAt ? this.date(version.inForceAt) : null },
    ];
  });
  readonly stepAt = computed(() => {
    const version = this.version();
    return version ? stepIndex(version) : 0;
  });
  /** The step the version passes next, while the version is not in force. */
  readonly next = computed<PlanStep | null>(() => {
    const version = this.version();
    return version && (version.state === 'draft' || version.state === 'in_progress') ? nextStep(version) : null;
  });

  /** The tree node of a row, for the settings of the Kostenstelle. */
  nodeOf(id: string): BudgetTreeNode | null {
    return findNode(this.tree(), id);
  }
  /** The heading of the section of a node: Titel directly below the Haushalt, else Kostenstelle. */
  levelKey(node: BudgetTreeNode): TranslationKey {
    return levelKey(node, this.top());
  }
  /** The parents of a new Kostenstelle: the budget with each Kostenstelle of the version. */
  readonly parentNodes = computed<readonly BudgetTreeNode[]>(() => {
    const top = this.top();
    const version = this.version();
    return top && version ? [planTree(top, version)] : [];
  });
  /**
   * The Ansatz that the first child of a Kostenstelle takes over, by the id of the parent:
   * a line without a child line gives its Ansatz to its first child.
   */
  readonly firstChildAmounts = computed<ReadonlyMap<string, string>>(
    () => new Map(this.rows().filter((r) => !r.hasChildren && r.amount > 0).map((r) => [r.id, r.amount.toFixed(2)])),
  );

  /** The Kostenstellen that can enter the draft. */
  private readonly addableNodes = computed<readonly BudgetTreeNode[]>(() => {
    const top = this.top();
    const version = this.version();
    return top && version ? addable(top, version) : [];
  });
  /** The Kostenstellen that can enter the draft, for the picker. The budget has no line. */
  readonly addNodes = computed<readonly BudgetTreeNode[]>(() =>
    this.addableNodes().map((n) => ({ ...n, children: [], byFiscalYear: [] })),
  );

  readonly columns = computed<ColumnDef[]>(() => {
    const money = (key: string, label: string, width = MONEY_COL): ColumnDef => ({ key, label, align: 'end', width });
    const prev = this.prevYear()?.display ?? '';
    const own = money('amount', this.amountLabel(), this.tableFields() ? FIELD_COL : MONEY_COL);
    const rest = this.nachtrag()
      ? [money('base', this.baseLabel())]
      : this.canCopy()
        ? [
            money('prev', this.i18n.translate('budget.plan.col.amount', { year: prev })),
            money('actual', this.i18n.translate('budget.plan.col.actual', { year: prev })),
          ]
        : [];
    const tight = this.wide() && !this.roomy() && rest.length > 1;
    return [
      { key: 'node', label: this.i18n.translate('budget.plan.col.title'), card: 'title' },
      own,
      ...rest,
      ...(tight ? [] : [money('change', this.i18n.translate('budget.plan.col.change'))]),
    ];
  });
  readonly rowId = (row: unknown): string => (row as PlanRow).id;

  /** The name of the Ansatz of the shown version: "Ansatz 2026" or "Ansatz 1. Nachtrag". */
  readonly amountLabel = computed(() => {
    const version = this.version();
    return this.i18n.translate('budget.plan.col.amount', {
      year: this.nachtrag() && version ? this.versionName(version) : (this.year()?.display ?? ''),
    });
  });
  /** The name of the Ansatz of the version before a Nachtrag: "Ansatz Stammplan". */
  readonly baseLabel = computed(() => {
    const base = this.base();
    return this.i18n.translate('budget.plan.col.amount', { year: base ? this.versionName(base) : '' });
  });

  /**
   * The action of the head: the step the version takes next. A reader cannot move the
   * version, so the head then shows the way to the vote of the step, when there is one.
   */
  readonly primary = computed<PrimaryAction | null>(() => {
    const version = this.version();
    const action = (id: string, label: string, icon: IconName, reason: string | null = null): PrimaryAction => ({
      id,
      label,
      icon,
      reason,
    });
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    if (!version) return null;
    if (!this.canWrite() || this.year()?.closedAt)
      return this.linkedVote() ? action('openVote', t('budget.plan.action.openVote'), 'vote') : null;
    switch (version.state) {
      case 'draft':
      case 'in_progress':
        return this.openAction(version, action, t);
      case 'in_force':
        return currentVersion(this.versions())?.id === version.id
          ? action('nachtrag', t('budget.plan.action.nachtrag'), 'fileplus')
          : null;
      case 'replaced':
        return null;
    }
  });

  /** Why the version cannot leave the draft or come into force: no line, a Titel without a side, or not balanced. */
  private readonly notReady = computed<string | null>(() => {
    if (!this.rows().length) return this.i18n.translate('budget.plan.error.empty');
    if (this.unsided()) return this.i18n.translate('budget.plan.error.sideMissing');
    return this.balanced() ? null : this.i18n.translate('budget.plan.error.notBalanced');
  });

  /**
   * The next action of a version that is not in force: "In Kraft setzen" after the last
   * step, the way to the open vote or to the meeting of a step that waits for its Gremium,
   * the request for the decision of a Gremium, or the step by hand.
   */
  private openAction(
    version: PlanVersion,
    action: (id: string, label: string, icon: IconName, reason?: string | null) => PrimaryAction,
    t: (key: TranslationKey) => string,
  ): PrimaryAction | null {
    const next = nextStep(version);
    const blocked = this.notReady();
    if (!next) return action('inForce', t('budget.plan.action.inForce'), 'check', blocked);
    if (this.voting() && next.voteStatus === 'open') return action('openVote', t('budget.plan.action.openVote'), 'vote');
    if (this.voting() && next.requestedAt) {
      const meeting = version.meetings?.[0];
      return meeting ? action(`openMeeting:${meeting.id}`, t('budget.plan.action.openMeeting'), 'users') : null;
    }
    if (this.voting() && next.gremiumId)
      return action('request', t('budget.plan.action.request'), 'vote', version.state === 'draft' ? blocked : null);
    return action(
      'step',
      this.i18n.translate('budget.plan.action.step', { name: next.name }),
      'check',
      version.state === 'draft' ? blocked : null,
    );
  }

  /**
   * The action in the head of the detail. The head of a Kostenstelle holds only the actions
   * on that Kostenstelle, so the step of the plan shows while the plan itself is selected.
   */
  readonly headPrimary = computed(() => (this.sel() ? null : this.primary()));

  /** The step whose vote the page links to. */
  private readonly linkedVote = computed(() => {
    const version = this.version();
    return version && this.voting() ? voteStep(version) : null;
  });

  readonly menu = computed<readonly RowMenuSection[]>(() => {
    const row = this.sel();
    if (row) return this.rowMenu(row);
    const primary = this.primary();
    const state = this.version()?.state;
    const blocked = this.notReady();
    const item = (
      id: string,
      key: TranslationKey,
      icon: RowMenuItem['icon'],
      show: boolean,
      disabledReason: string | null = null,
    ): RowMenuItem[] => (show && primary?.id !== id ? [{ id, label: this.i18n.translate(key), icon, disabledReason }] : []);
    const items: RowMenuItem[] = [
      ...(primary && this.phone()
        ? [{ id: primary.id, label: primary.label, icon: primary.icon, disabledReason: primary.reason }]
        : []),
      ...item('request', 'budget.plan.action.request', 'vote', this.canRequest(), state === 'draft' ? blocked : null),
      ...item('openVote', 'budget.plan.action.openVote', 'link', !!this.linkedVote()),
      ...this.meetingItems(primary?.id),
      ...item('backToDraft', 'budget.plan.action.backToDraft', 'undo', this.moves() && state === 'in_progress'),
      ...item('add', 'budget.plan.action.add', 'fileplus', this.editable() && this.addableNodes().length > 0),
      ...item('setState', 'budget.plan.action.setState', 'edit', this.canSetState()),
    ];
    const files: RowMenuItem[] = [
      ...item('exportPdf', 'budget.plan.action.exportPdf', 'download', !!this.version()),
      ...item('exportXlsx', 'budget.plan.action.exportXlsx', 'download', !!this.version()),
    ];
    const draft: RowMenuItem[] =
      this.editable() && this.versions().length > 0
        ? [{ id: 'deleteDraft', label: this.i18n.translate('budget.plan.action.deleteDraft'), icon: 'trash', danger: true }]
        : [];
    return [items, files, draft].filter((section) => section.length > 0).map((section) => ({ items: section }));
  });

  /** The ⋮ menu of the bottom sheet: the actions on its Kostenstelle. */
  readonly sheetMenu = computed<readonly RowMenuSection[]>(() => this.rowMenu(this.sheetRow()));

  /** The actions on one Kostenstelle: take its line out of the draft, or delete it. */
  private rowMenu(row: PlanRow | null): readonly RowMenuSection[] {
    if (!row || !this.canWrite()) return [];
    const items: RowMenuItem[] = [
      ...(this.editable()
        ? [{ id: 'removeLine', label: this.i18n.translate('budget.plan.action.remove'), icon: 'x' as const }]
        : []),
      { id: 'deleteNode', label: this.i18n.translate('budget.cc.delete'), icon: 'trash', danger: true },
    ];
    return [{ items }];
  }

  /**
   * The person can set the state of the shown version by hand: the own permission, an open
   * year and the newest version of the plan.
   */
  readonly canSetState = computed(() => {
    const version = this.version();
    return (
      this.auth.can('budget.plan.set_state') &&
      !this.year()?.closedAt &&
      !!version &&
      version.number === Math.max(...this.versions().map((v) => v.number))
    );
  });
  /** The dialog "Zustand setzen": the chosen state and the reason. */
  readonly stateOpen = signal(false);
  readonly stateTarget = signal('');
  readonly stateReason = signal('');
  /** The states the version can take by hand: the draft, each step, in force, without its own state. */
  readonly stateOptions = computed<SelectOption[]>(() => {
    const version = this.version();
    if (!version) return [];
    const count = version.steps.length;
    const passed = version.steps.filter((step) => !!step.passedAt).length;
    const own = version.state === 'draft' ? 0 : version.state === 'in_force' ? count + 1 : passed < count ? passed + 1 : -1;
    return [
      { value: 'draft', label: this.stateLabel('draft') },
      ...version.steps.map((step, i) => ({ value: `step:${i}`, label: step.name })),
      { value: 'in_force', label: this.stateLabel('in_force') },
    ].filter((_, i) => i !== own);
  });

  private readonly voting = computed(() => this.features.isOn('voting'));
  /** The next step names a Gremium, and nobody asked for its decision yet. */
  private readonly canRequest = computed(() => {
    const next = this.next();
    return this.moves() && this.voting() && !!next?.gremiumId && !next.requestedAt;
  });

  /** One menu entry per meeting that has the version on its agenda, without the one of the head. */
  private meetingItems(primaryId: string | undefined): RowMenuItem[] {
    const version = this.version();
    const waits = !!version && version.state === 'in_progress' && !!nextStep(version)?.requestedAt;
    return (waits ? (version.meetings ?? []) : [])
      .map((meeting) => ({
        id: `openMeeting:${meeting.id}`,
        label: this.i18n.translate('budget.plan.action.openMeetingNamed', { name: this.meetingName(meeting) }),
        icon: 'users' as const,
      }))
      .filter((entry) => entry.id !== primaryId);
  }

  /** A meeting as the page names it: its title and its date. */
  private meetingName(meeting: PlanMeeting): string {
    return meeting.date ? `${meeting.title}, ${this.date(meeting.date)}` : meeting.title;
  }

  /** The person can move the shown version: the write right, an open year and a version. */
  private readonly moves = computed(() => this.canWrite() && !this.year()?.closedAt && !!this.version());

  /** The vote of the next step is a draft or open, so "back to draft" ends it. */
  private readonly voteWaits = computed(() => {
    const next = this.next();
    return !!next && voteRuns(next);
  });

  /** The texts of the confirmation that is open. */
  readonly askView = computed<AskView | null>(() => {
    const ask = this.ask();
    if (!ask) return null;
    const t = (key: TranslationKey, params?: Record<string, string>): string => this.i18n.translate(key, params);
    switch (ask.kind) {
      case 'inForce':
        return {
          title: t('budget.plan.inForce.title'),
          body: t('budget.plan.inForce.body'),
          confirmLabel: t('budget.plan.action.inForce'),
          danger: false,
        };
      case 'step':
        return {
          title: t('budget.plan.step.title'),
          body: t('budget.plan.step.body', { name: ask.name }),
          confirmLabel: t('budget.plan.step.confirm'),
          danger: false,
        };
      case 'backToDraft':
        return {
          title: t('budget.plan.backToDraft.title'),
          body: t('budget.plan.backToDraft.body'),
          confirmLabel: t('budget.plan.action.backToDraft'),
          danger: this.voteWaits(),
        };
      case 'deleteDraft':
        return {
          title: t('budget.plan.deleteDraft.title'),
          body: t('budget.plan.deleteDraft.body'),
          confirmLabel: '',
          danger: true,
        };
      case 'removeLine':
        return {
          title: t('budget.plan.remove.title'),
          body: t('budget.plan.remove.body', { name: ask.row.name }),
          confirmLabel: t('budget.plan.remove.confirm'),
          danger: true,
        };
      case 'deleteNode':
        return {
          title: t('budget.tree.deleteTitle'),
          body: t('budget.tree.deleteConfirm', { name: ask.row.name, path: ask.row.pathKey }),
          confirmLabel: '',
          danger: true,
        };
    }
  });

  /** The floating button: a new Kostenstelle in a draft, the plan of a year without one. */
  readonly fab = computed<{ readonly id: 'new' | 'createPlan'; readonly label: string } | null>(() => {
    if (this.editable()) return { id: 'new', label: this.i18n.translate(createKey(this.selId(), this.top())) };
    return this.load().kind === 'none' && this.canWrite() && !!this.year() && !this.year()?.closedAt
      ? { id: 'createPlan', label: this.i18n.translate('budget.plan.none.create') }
      : null;
  });

  constructor() {
    this.treeApi.changed.pipe(takeUntilDestroyed()).subscribe(() => this.reloadTree());
    this.destroyRef.onDestroy(() => {
      this.gone = true;
    });
    const qp = this.route.snapshot.queryParamMap;
    this.selId.set(qp.get('costCentre') ?? '');
    const wanted = Number(qp.get('version') ?? '');
    this.wantedVersion = qp.get('version') !== null && Number.isInteger(wanted) ? wanted : null;
    pageItemTitle(() => this.picked()?.name ?? null);
    this.start();
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      const id = params.get('costCentre') ?? '';
      if (id === this.selId()) return;
      this.flushEdits();
      this.sheetPushed = false;
      this.selId.set(id);
    });
    if (this.canWrite())
      this.adminApi.listGremienOptions().subscribe({
        next: (list) => this.gremiumOptions.set(list.map((g) => ({ value: g.id, label: g.name }))),
        error: () => this.gremiumOptions.set([]),
      });
  }

  /** Load the page from its URL: the plan of a version, else the budget and the year. */
  private start(): void {
    const qp = this.route.snapshot.queryParamMap;
    const fromVote = qp.get('planVersion');
    if (fromVote) this.openVersion(fromVote as Uuid);
    else this.loadTree(qp.get('budget'), qp.get('fy'));
  }

  /**
   * The action of the load error: read the page again. A budget that the person chose
   * on the page stays the wanted one, because the URL still names the budget before it
   * until the fiscal years of the new one are read.
   */
  retry(): void {
    const wanted = this.topId();
    this.error.set(false);
    this.loading.set(true);
    this.topId.set('');
    if (wanted) this.loadTree(wanted, null);
    else this.start();
  }

  /** A link from the vote of a step names only the version: read its plan, then show it. */
  private openVersion(versionId: Uuid): void {
    this.api.planOfVersion(versionId).subscribe({
      next: (plan) => {
        this.wantedVersion = plan.versions.find((v) => v.id === versionId)?.number ?? null;
        this.loadTree(plan.budgetId, plan.fiscalYearId);
      },
      error: () => this.loadTree(null, null),
    });
  }

  /**
   * Read the tree, then select the wanted budget and year, else the first budget. This
   * first read has a number too: a read for a save of the page before can go out after it
   * and be answered first, and its tree is then the newer one.
   */
  private loadTree(wantedTop: string | null, wantedFy: string | null): void {
    this.treeSent += 1;
    const read = this.treeSent;
    this.treeApi.tree().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (tree) => {
        if (read >= this.treeShown) this.tree.set(tree);
        this.treeShown = Math.max(read, this.treeShown);
        const tops = this.tops();
        if (!tops.length) {
          void this.router.navigate(['/budget'], { replaceUrl: true });
          return;
        }
        if (!this.top()) this.pickTop((tops.find((t) => t.id === wantedTop) ?? tops[0]).id, wantedFy);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  /**
   * Select a top-level Kostenstelle and load its fiscal years. The plan and the years of the
   * budget before go off the page at once, so no action of the old plan stands under the name
   * of the new budget. The selected Kostenstelle of the budget before goes too, because the
   * URL would else name a Kostenstelle beside a budget and a year that are not its own. The years of a budget that the person left before the answer do not
   * come onto the page.
   */
  pickTop(id: string, wantedFy: string | null = null): void {
    if (this.topId() && this.topId() !== id) this.selId.set('');
    this.topId.set(id);
    this.years.set([]);
    this.fyId.set('');
    this.versionId.set('');
    this.load.set({ kind: 'loading' });
    this.treeApi.listFiscalYears(id as Uuid).subscribe({
      next: (years) => {
        if (this.topId() !== id) return;
        this.years.set(years);
        this.loading.set(false);
        this.pickYear(years.find((y) => y.id === wantedFy)?.id ?? defaultFiscalYearId(years));
      },
      error: () => {
        if (this.topId() !== id) return;
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  /**
   * Select a fiscal year and load its plan and the plan of the year before. A Kostenstelle
   * of the URL that is not in the tree of the budget goes off the page and off the URL,
   * because the page has nothing to open for it.
   */
  pickYear(id: string): void {
    const budget = this.top();
    if (this.selId() && budget && !withDescendants(budget).some((n) => n.id === this.selId())) this.selId.set('');
    this.fyId.set(id);
    this.versionId.set('');
    this.syncUrl();
    if (!id) {
      this.load.set({ kind: 'none' });
      return;
    }
    this.load.set({ kind: 'loading' });
    const top = this.topId() as Uuid;
    const prev = this.prevYear();
    const place = this.place();
    const sent = this.send();
    this.ended(
      forkJoin({
        plan: this.readPlan(top, id as Uuid),
        prev: prev ? this.readPlan(top, prev.id) : of(null),
      }),
      sent,
    ).subscribe({
      next: ({ plan, prev: before }) => {
        if (this.place() !== place) return;
        this.prevPlan.set(before);
        if (this.newest(sent)) this.load.set(plan ? { kind: 'plan', plan } : { kind: 'none' });
        const wanted = plan?.versions.find((v) => v.number === this.wantedVersion);
        this.wantedVersion = null;
        if (wanted) this.pickVersion(wanted.id);
      },
      error: () => {
        if (this.place() === place) this.load.set({ kind: 'error' });
      },
    });
  }

  /**
   * The budget and the year that the page names. An answer belongs to the place of its
   * request: a late answer for another year must not come onto the page, because the next
   * edit would then change a version that the page does not name.
   */
  private place(): string {
    return `${this.topId()}|${this.fyId()}`;
  }

  /** The number of the last request for a plan, and of the request whose plan the page shows. */
  private lastSent = 0;
  private lastShown = 0;
  /** The numbers of the requests without an answer. */
  private open: readonly number[] = [];
  /** An answer came in another order than its request went out. */
  private mixed = false;

  /** Number a request for a plan at the moment it goes out. */
  private send(): number {
    this.lastSent += 1;
    this.open = [...this.open, this.lastSent];
    return this.lastSent;
  }

  /**
   * A numbered request ended. The number of a request is the order in which the page sent
   * it, and the server can take two requests in the other order. So after answers that came
   * in another order than their requests, the page reads the plan once more when no request
   * is on its way: that read holds the saved plan. A page that loads another budget or
   * year reads its plan by itself.
   */
  private ended<T>(request: Observable<T>, sent: number): Observable<T> {
    return request.pipe(
      finalize(() => {
        this.open = this.open.filter((n) => n !== sent);
        if (this.open.length || !this.mixed) return;
        this.mixed = false;
        if (this.fyId() && this.load().kind !== 'loading') this.refreshPlan();
      }),
    );
  }

  /**
   * Report whether the answer of a request may come onto the page. An answer is older than
   * the plan on the page when a request that went out later is already answered, and it
   * would then show an amount that is no longer the saved one.
   */
  private newest(sent: number): boolean {
    this.mixed = this.mixed || sent < this.lastShown || this.open.some((n) => n < sent);
    if (sent < this.lastShown) return false;
    this.lastShown = sent;
    return true;
  }

  /**
   * Read the plan again without the loading state, so an open line stays open and keeps
   * its scroll position and its focus. A failed read starts the full read, which shows its
   * error with a retry, so the page never keeps a plan that it could not read again.
   */
  refreshPlan(): void {
    const place = this.place();
    const sent = this.send();
    this.ended(this.readPlan(this.topId() as Uuid, this.fyId() as Uuid), sent).subscribe({
      next: (plan) => {
        if (this.place() === place && this.newest(sent)) this.load.set(plan ? { kind: 'plan', plan } : { kind: 'none' });
      },
      error: () => {
        if (this.place() === place) this.reloadPlan();
      },
    });
  }

  /** The plan of a year, `null` when the year has none. */
  private readPlan(top: Uuid, fy: Uuid): Observable<BudgetPlan | null> {
    return this.api.plan(top, fy).pipe(
      catchError((err: unknown) => {
        if (errorStatus(err) === 404) return of(null);
        throw err;
      }),
    );
  }

  pickVersion(id: string): void {
    this.versionId.set(id);
    this.syncUrl();
  }

  /** The switch of the Budget tab: "Bewirtschaftung" opens the budget view of the same year. */
  setMode(mode: string | null): void {
    if (mode !== 'run') return;
    void this.router.navigate(['/budget'], {
      queryParams: { budget: this.topId() || null, fy: this.fyId() || null, costCentre: this.selId() || null },
    });
  }

  /** A press on a row: the detail beside the list, else the bottom sheet. */
  select(row: unknown): void {
    this.selectId((row as PlanRow).id);
  }

  /**
   * Select a Kostenstelle, '' for the plan. Beside the list the heading of the detail takes
   * the focus. On a narrow screen the bottom sheet is a history entry of its own, so "back"
   * closes the sheet and does not leave the page, and its close button goes back to the
   * entry before it.
   */
  selectId(id: string): void {
    if (!this.wide() && !id && this.sheetPushed) {
      this.location.back();
      return;
    }
    const opensSheet = !this.wide() && !!id && !this.selId();
    this.flushEdits();
    this.selId.set(id);
    this.syncUrl(!opensSheet);
    this.sheetPushed = opensSheet;
    if (this.wide()) setTimeout(() => this.host.nativeElement.querySelector<HTMLElement>('#bp-title')?.focus());
  }

  /** Save each amount and each Erläuterung that a person typed and did not leave yet, before its field goes. */
  private flushEdits(): void {
    for (const key of Object.keys(this.edits())) {
      const [id, field] = key.split(':');
      const row = this.rows().find((r) => r.id === id);
      if (row && field === 'note') this.saveNote(row);
      else if (row) this.saveAmount(row, field === 'blocked' ? 'blocked' : 'amount');
    }
  }

  /**
   * The person is on the way to another page, or already there. An answer that arrives
   * then must not write the URL of this page, because that would cancel the navigation
   * or pull the person back.
   */
  private leaving(): boolean {
    const path = (url: string): string => url.split(/[?#]/)[0];
    const next = this.router.getCurrentNavigation();
    return this.gone || (!!next && path(this.router.serializeUrl(next.extractedUrl)) !== path(this.router.url));
  }

  /** The URL names the budget, the year, the chosen version and the Kostenstelle. */
  private syncUrl(replaceUrl = true): void {
    if (this.leaving()) return;
    const chosen = this.versions().find((v) => v.id === this.versionId());
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        budget: this.topId() || null,
        fy: this.fyId() || null,
        version: chosen ? chosen.number : null,
        costCentre: this.selId() || null,
      },
      replaceUrl,
    });
  }

  /** Create the plan of the selected year, empty or as a copy of the year before. */
  createPlan(copy: boolean): void {
    const prev = this.prevYear();
    this.write(
      this.api.createPlan(this.topId() as Uuid, this.fyId() as Uuid, copy && prev ? prev.id : null),
      'budget.plan.toast.created',
    );
  }

  /** The year before has a plan in force: the new plan can start as its copy, and the page shows its Ansatz and its Ist. */
  readonly canCopy = computed(() => inForce(this.prevPlan()?.versions ?? []) !== null);

  /** Run an action of the head, of a menu or of the floating button. `row` is its Kostenstelle. */
  onAction(id: string, row: PlanRow | null = this.picked()): void {
    const version = this.version();
    const [name, target] = id.split(':');
    const action: ActionId | undefined = ACTIONS.find((a) => a === name);
    if (!action || this.busy()) return;
    switch (action) {
      case 'createPlan':
        this.createPlan(false);
        return;
      case 'inForce':
      case 'backToDraft':
      case 'deleteDraft':
        this.ask.set({ kind: action });
        return;
      case 'step':
        this.ask.set({ kind: 'step', name: this.next()?.name ?? '' });
        return;
      case 'removeLine':
      case 'deleteNode':
        if (row) this.ask.set({ kind: action, row });
        return;
      case 'nachtrag':
        this.write(this.api.createNachtrag(this.topId() as Uuid, this.fyId() as Uuid), 'budget.plan.toast.nachtrag');
        return;
      case 'add':
        this.addId.set('');
        this.addOpen.set(true);
        return;
      case 'new':
        this.createOpen.set(true);
        return;
      case 'request':
        if (version) this.write(this.api.requestStep(version.id), 'budget.plan.toast.request');
        return;
      case 'openMeeting':
        void this.router.navigate(['/meetings', target]);
        return;
      case 'openVote':
        void this.router.navigate(['/voting', this.linkedVote()?.voteId]);
        return;
      case 'setState':
        this.stateTarget.set('');
        this.stateReason.set('');
        this.stateOpen.set(true);
        return;
      case 'exportPdf':
        this.exportFile('pdf');
        return;
      case 'exportXlsx':
        this.exportFile('xlsx');
        return;
    }
  }

  /** Load the shown version as a file and hand it to the browser under the name of the server. */
  private exportFile(format: PlanExportFormat): void {
    const version = this.version();
    if (!version) return;
    this.busy.set(true);
    this.api.exportVersion(version.id, format).subscribe({
      next: (file) => {
        downloadBlob(file.blob, file.filename);
        this.busy.set(false);
      },
      error: () => {
        this.busy.set(false);
        this.toast.error(this.i18n.translate('budget.dash.exportError'));
      },
    });
  }

  /** Save the state of the dialog "Zustand setzen". A version in force sets the allocations, so the tree is read again. */
  setStateByHand(event: Event): void {
    event.preventDefault();
    const version = this.version();
    const target = this.stateTarget();
    const reason = this.stateReason().trim();
    if (!version || !target || !reason || this.busy()) return;
    const step = target.startsWith('step:') ? Number(target.slice(5)) : null;
    const state: ManualState = step === null ? (target as ManualState) : 'in_progress';
    this.stateOpen.set(false);
    this.write(this.api.setStateByHand(version.id, { state, step, reason }), 'budget.plan.toast.stateSet', () => this.readTree());
  }

  /** The person confirmed the open question: run its step. */
  confirmAsk(): void {
    const ask = this.ask();
    const version = this.version();
    this.ask.set(null);
    if (!ask || !version || this.busy()) return;
    switch (ask.kind) {
      case 'inForce':
        this.write(this.api.setState(version.id, 'in_force'), 'budget.plan.toast.inForce', () => this.readTree());
        return;
      case 'step':
        this.write(
          this.api.passNextStep(version.id, Math.max(version.steps.findIndex((s) => !s.passedAt), 0)),
          'budget.plan.toast.step',
        );
        return;
      case 'backToDraft':
        this.write(this.api.setState(version.id, 'draft'), 'budget.plan.toast.state');
        return;
      case 'deleteDraft':
        this.deleteDraft(version);
        return;
      case 'removeLine':
        this.write(this.api.deleteLine(version.id, ask.row.id), 'budget.plan.toast.removed', () =>
          this.selectId(this.wide() ? (ask.row.parentId ?? '') : ''),
        );
        return;
      case 'deleteNode':
        this.deleteNode(ask.row);
        return;
    }
  }

  /** Delete the draft version. The plan of the year goes with its only version. */
  private deleteDraft(version: PlanVersion): void {
    this.busy.set(true);
    this.api.deleteVersion(version.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.success(this.i18n.translate('budget.plan.toast.draftDeleted'));
        this.versionId.set('');
        this.selId.set('');
        this.pickYear(this.fyId());
      },
      error: (err: unknown) => this.fail(err),
    });
  }

  /** The dialog created a Kostenstelle with its line: read the tree, then show the plan. */
  onCreated(created: CostCentreCreated): void {
    this.createOpen.set(false);
    this.reloadTree(created.plan);
  }

  /**
   * A setting of a Kostenstelle changed: the names of the rows come from the tree.
   * A failed read reads the plan again, but not on a page that has not taken its budget from
   * the URL yet, because that would write the URL without its budget and year.
   */
  reloadTree(plan: BudgetPlan | null = null): void {
    const place = this.place();
    const sent = plan ? this.send() : 0;
    this.treeSent += 1;
    const read = this.treeSent;
    (plan ? this.ended(this.treeApi.tree(), sent) : this.treeApi.tree()).subscribe({
      next: (tree) => {
        if (read >= this.treeShown) this.tree.set(tree);
        this.treeShown = Math.max(read, this.treeShown);
        if (plan && this.place() === place && this.newest(sent)) this.load.set({ kind: 'plan', plan });
      },
      error: () => this.topId() && this.reloadPlan(),
    });
  }

  /** Read the tree again after a write that changed the allocations. */
  private readTree(): void {
    this.reloadTree();
  }

  /** The numbers of the tree reads: an answer that is older than the tree on the page is dropped. */
  private treeSent = 0;
  private treeShown = 0;

  /** Delete the Kostenstelle after the confirmation. A refusal shows its reason. */
  private deleteNode(row: PlanRow): void {
    this.busy.set(true);
    this.treeApi.deleteNode(row.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.success(this.i18n.translate('budget.tree.toast.deleted'));
        this.selectId(this.wide() ? (row.parentId ?? '') : '');
        this.reloadTree();
        this.reloadPlan();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.toast.error(this.i18n.translate(costCentreError(problemCode(err), 'budget.tree.toast.deleteFailed')));
      },
    });
  }

  /** Take the chosen Kostenstelle into the draft with an Ansatz of 0 €. */
  addLine(event: Event): void {
    event.preventDefault();
    const version = this.version();
    const id = this.addId();
    if (!version || !id || this.busy()) return;
    this.addOpen.set(false);
    this.write(this.api.setLine(version.id, id as Uuid, {}), 'budget.plan.toast.added');
  }

  /**
   * Save the changed fields of a line. The request holds only these fields, so two saves
   * of one line that follow each other do not overwrite each other. `ended` runs when the
   * save ended or was not needed, also when the person chose another year in the meantime.
   */
  saveLine(
    row: PlanRow,
    change: PlanLineSet,
    ended: (() => void) | null = null,
  ): void {
    const version = this.version();
    const key = `${version?.id}:${row.id}`;
    const known = { ...row, ...this.lineSent()[key] };
    const same =
      (change.side === undefined || change.side === known.side) &&
      (change.amount === undefined || Number(change.amount) === Number(known.amount)) &&
      (change.blocked === undefined || Number(change.blocked) === Number(known.blocked)) &&
      (change.note === undefined || (change.note ?? '') === (known.note ?? '')) &&
      (change.transferable === undefined || change.transferable === known.transferable) &&
      (change.coverable === undefined || change.coverable === known.coverable);
    if (!version || !this.editable() || same) return ended?.();
    const fields = Object.keys(change).map((field) => `${key}:${field}`);
    const count = (by: number) => (runs: Readonly<Record<string, number>>): Readonly<Record<string, number>> => ({
      ...runs,
      ...Object.fromEntries(fields.map((field) => [field, (runs[field] ?? 0) + by])),
    });
    this.lineSent.update((sent) => ({ ...sent, [key]: { ...sent[key], ...change } }));
    this.lineRuns = count(1)(this.lineRuns);
    const done = (): void => {
      this.lineRuns = count(-1)(this.lineRuns);
      const left = Object.fromEntries(Object.entries(this.lineSent()[key] ?? {}).filter(([field]) => this.lineRuns[`${key}:${field}`]));
      this.lineSent.update((sent) => ({ ...Object.fromEntries(Object.entries(sent).filter(([k]) => k !== key)), ...(Object.keys(left).length ? { [key]: left } : {}) }));
      this.lineRuns = Object.fromEntries(Object.entries(this.lineRuns).filter(([, n]) => n));
      ended?.();
    };
    const refused = (): void =>
      this.lineSent.update((sent) => ({
        ...sent,
        [key]: Object.fromEntries(
          Object.entries(sent[key] ?? {}).map(([field, value]) => [
            field,
            field in change && value === change[field as keyof PlanLineSet] ? known[field as keyof PlanLineSet] : value,
          ]),
        ),
      }));
    this.write(this.api.setLine(version.id, row.id, change).pipe(tap({ error: refused }), finalize(done)), null, null, false);
  }

  /**
   * The fields of the saves that run, by version and line. A change is compared with them
   * and then with the plan on the page, because the plan on the page is the plan before
   * these saves: a field that the person sets back while its save runs must be saved again.
   * An amount field shows its amount of these saves, because the answer of an earlier save
   * of the field holds the amount before. A refused save gives its fields the value of the
   * save before it again, when that save still runs.
   */
  private readonly lineSent = signal<Readonly<Record<string, PlanLineSet>>>({});
  /**
   * The number of the saves that run for a field of a line. A field leaves `lineSent` when
   * its last save ended, and not with the end of a save of another field of its line.
   */
  private lineRuns: Readonly<Record<string, number>> = {};

  /**
   * The key of a press or a typed text that the page keeps for a field of a line. It names
   * the version, because a Kostenstelle has the same id in each year of its budget, and the
   * line of another year must not show it.
   */
  private kept(row: PlanRow, field: 'transferable' | 'coverable' | 'note'): string {
    return `${row.id}:${field}:${this.version()?.id ?? ''}`;
  }

  /** The side a select shows: the choice whose save runs, else the saved side. */
  sideValue(row: PlanRow): Side | null {
    return this.lineSent()[`${this.version()?.id}:${row.id}`]?.side ?? row.side;
  }

  /** Save the side of the line of a Titel. The answer holds the lines without the Vermerke that an income side takes off. */
  saveSide(row: PlanRow, side: string | null): void {
    if (side === 'income' || side === 'expense') this.saveLine(row, { side });
  }

  /** The presses of the Vermerk switches whose save runs, by line and Vermerk. */
  private readonly marks = signal<Readonly<Record<string, boolean>>>({});

  /** The state a Vermerk switch shows: the press whose save runs, else the saved state. */
  mark(row: PlanRow, field: 'transferable' | 'coverable'): boolean {
    return this.marks()[this.kept(row, field)] ?? row[field];
  }

  /**
   * Save a Vermerk. The switch follows the press while the save runs and the saved state
   * after it. A switch that followed only the saved state would keep the press after a
   * refused save, because the saved state is then the same as before the press and writes
   * nothing into the switch.
   */
  saveMark(row: PlanRow, field: 'transferable' | 'coverable', value: boolean): void {
    const key = this.kept(row, field);
    const ended = (): void => {
      if (this.savesEnded(key)) this.marks.update((m) => Object.fromEntries(Object.entries(m).filter(([k]) => k !== key)));
    };
    this.marks.update((m) => ({ ...m, [key]: value }));
    this.saves = { ...this.saves, [key]: (this.saves[key] ?? 0) + 1 };
    this.saveLine(row, { [field]: value }, ended);
  }

  /**
   * The number of the saves that run for a kept press or text, by its key. The page keeps
   * the press or the text until the last of them ended, because the answer of an older save
   * holds an older value.
   */
  private saves: Readonly<Record<string, number>> = {};

  /** One save of a kept press or text ended. Say if it was the last one that ran. */
  private savesEnded(key: string): boolean {
    const left = (this.saves[key] ?? 1) - 1;
    this.saves = { ...Object.fromEntries(Object.entries(this.saves).filter(([k]) => k !== key)), ...(left ? { [key]: left } : {}) };
    return left === 0;
  }

  /**
   * The amount fields of the tables take the wide form: an Ansatz of the version has more
   * digits than the narrow field shows, or the person typed such an amount in this version.
   * The form stays for the version after the typed amount, because the field drops the
   * typed text when the person leaves it, and the table would else go narrow for the time
   * of the save and wide again with its answer.
   */
  readonly wideFields = computed(
    () => (this.version()?.lines ?? []).some((line) => Number(line.amount) >= WIDE_FROM) || this.wideFor() === (this.version()?.id ?? ''),
  );
  /** The version in which the person typed an amount that needs the wide form. */
  private readonly wideFor = signal<string | null>(null);

  /** The amount a field shows: the text a person types, else the amount of the save that runs, else the saved amount. */
  fieldValue(row: PlanRow, field: 'amount' | 'blocked'): string | number {
    return this.edits()[`${row.id}:${field}`] ?? this.lineSent()[`${this.version()?.id}:${row.id}`]?.[field] ?? row[field];
  }

  /** Keep the amount a person types, as the canonical decimal string of the field. */
  edit(row: PlanRow, field: 'amount' | 'blocked', value: string | null): void {
    this.edits.update((e) => ({ ...e, [`${row.id}:${field}`]: value ?? '' }));
    if (Number(value) >= WIDE_FROM) this.wideFor.set(this.version()?.id ?? null);
  }

  /**
   * An amount field lost the focus: save the typed amount. An empty field and an amount
   * that the plan cannot hold save nothing, and the field shows the saved amount again.
   */
  saveAmount(row: PlanRow, field: 'amount' | 'blocked' = 'amount'): void {
    const key = `${row.id}:${field}`;
    const value = this.edits()[key];
    if (value === undefined) return;
    this.edits.update((e) => Object.fromEntries(Object.entries(e).filter(([k]) => k !== key)));
    if (value === '') return;
    switch (amountProblem(value)) {
      case 'negative':
        this.toast.error(this.i18n.translate('budget.plan.error.amountNegative'));
        return;
      case 'tooLarge':
        this.toast.error(this.i18n.translate('budget.plan.error.amountTooLarge'));
        return;
      case null:
        this.saveLine(row, { [field]: value });
    }
  }

  /** Enter in an amount field of a table saves the amount and does not open the row. */
  onFieldEnter(event: Event, row: PlanRow): void {
    event.stopPropagation();
    this.saveAmount(row);
  }

  /**
   * The Erläuterung a field shows: the text a person types, else the saved text. A version
   * that takes no change shows only the saved text.
   */
  noteValue(row: PlanRow): string {
    return (this.editable() ? this.edits()[this.kept(row, 'note')] : undefined) ?? row.note;
  }

  /** Keep the Erläuterung a person types, so the answer of a save does not replace it. */
  editNote(row: PlanRow, event: Event): void {
    const text = (event.target as HTMLTextAreaElement).value;
    const key = this.kept(row, 'note');
    this.edits.update((e) => ({ ...e, [key]: text }));
  }

  /**
   * The Erläuterung lost the focus: save the typed text. The field keeps the typed text
   * until the save ends, and a text that the person typed in the meantime stays. A refused
   * save shows the saved text again.
   */
  saveNote(row: PlanRow): void {
    const key = this.kept(row, 'note');
    const text = this.edits()[key];
    if (text === undefined || this.noteSent[key] === text) return;
    const without = (texts: Readonly<Record<string, string>>, sent: string | undefined): Readonly<Record<string, string>> =>
      Object.fromEntries(Object.entries(texts).filter(([k, v]) => k !== key || v !== sent));
    const ended = (): void => {
      if (!this.savesEnded(key)) return;
      const last = this.noteSent[key];
      this.noteSent = without(this.noteSent, last);
      this.edits.update((e) => without(e, last));
    };
    this.noteSent = { ...this.noteSent, [key]: text };
    this.saves = { ...this.saves, [key]: (this.saves[key] ?? 0) + 1 };
    this.saveLine(row, { note: text.trim() || null }, ended);
  }

  /** The Erläuterung of the last save that runs, by line, so a second leave of the field sends no second request. */
  private noteSent: Readonly<Record<string, string>> = {};

  /**
   * Run a plan write and show the plan it answers. `after` runs after the answer. A failed
   * write reads the saved plan again. A write that `locks` takes no second action while it runs;
   * the save of a field does not lock, so a second field can save beside it.
   */
  private write(
    request: Observable<BudgetPlan>,
    toast: TranslationKey | null,
    after: (() => void) | null = null,
    locks = true,
  ): void {
    if (locks && this.busy()) return;
    if (locks) this.busy.set(true);
    const place = this.place();
    const shown = this.versionId();
    const sent = this.send();
    this.ended(request, sent).subscribe({
      next: (plan) => {
        if (locks) this.busy.set(false);
        if (this.place() !== place) return;
        if (this.versionId() === shown) this.versionId.set('');
        if (this.newest(sent)) this.load.set({ kind: 'plan', plan });
        if (toast) this.toast.success(this.i18n.translate(toast));
        after?.();
        this.syncUrl();
      },
      error: (err: unknown) => this.fail(err, !locks),
    });
  }

  /**
   * Show the cause of a failed write and the saved plan again. After the save of a field
   * the read is the quiet one: the line stays open, and the next field keeps its focus and
   * the text that the person types in it.
   */
  private fail(err: unknown, quiet = false): void {
    this.busy.set(false);
    this.toast.error(this.i18n.translate(WRITE_ERRORS[problemCode(err)] ?? 'budget.plan.error.failed'));
    if (quiet) this.refreshPlan();
    else this.reloadPlan();
  }

  reloadPlan(): void {
    const version = this.versionId();
    this.pickYear(this.fyId());
    this.versionId.set(version);
    this.syncUrl();
  }

  versionName(version: PlanVersion): string {
    return version.number === 0
      ? this.i18n.translate('budget.plan.version.base')
      : this.i18n.translate('budget.plan.version.nachtrag', { number: version.number });
  }

  stateLabel(state: PlanState): string {
    return this.i18n.translate(`budget.plan.state.${state}` as TranslationKey);
  }

  sideLabel(row: PlanRow): string {
    return this.i18n.translate(`budget.plan.side.${groupOf(row)}` as TranslationKey);
  }

  money(value: number | null): string {
    return value === null ? '–' : formatMoney(value, this.i18n.formatLocale(), { whole: Number.isInteger(value) });
  }

  /** "Budget: VS-Mittel": the name of a chip, a colon and its value. */
  private chip(label: TranslationKey, value: string | null | undefined): string {
    const name = this.i18n.translate(label);
    return value ? `${name}: ${value}` : name;
  }

  /** The Ansatz against the version before for a Nachtrag, else against the year before. */
  changeText(row: PlanRow): string {
    const against = this.nachtrag() ? (row.base ?? 0) : row.prev;
    const change = against === null ? 0 : cents(row.amount) - cents(against);
    if (change === 0) return '–';
    return (change > 0 ? '+' : '−') + this.money(Math.abs(change) / 100);
  }

  /**
   * Under a step: the date it was passed, else the open vote, else the meetings that have
   * the plan on their agenda, else that the step waits for a meeting of its Gremium.
   */
  private stepHint(step: PlanStep, version: PlanVersion | null): string | null {
    if (step.passedAt)
      return step.byHand
        ? `${this.date(step.passedAt)} · ${this.i18n.translate('budget.plan.step.byHand')}`
        : this.date(step.passedAt);
    if (step.voteStatus === 'open') return this.i18n.translate('budget.plan.vote.open');
    if (!step.requestedAt || version?.state !== 'in_progress') return null;
    const meetings = (version.meetings ?? []).map((meeting) => this.meetingName(meeting));
    return meetings.length
      ? this.i18n.translate('budget.plan.step.onAgenda', { meetings: meetings.join(' · ') })
      : this.i18n.translate('budget.plan.step.waits', { gremium: step.gremiumName ?? '' });
  }

  private date(iso: string | null | undefined): string {
    return iso ? new Intl.DateTimeFormat(this.i18n.formatLocale(), { dateStyle: 'medium' }).format(new Date(iso)) : '';
  }
}
