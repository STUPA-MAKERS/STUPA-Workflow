import { ChangeDetectionStrategy, Component, ElementRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { type Observable, forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  ConfirmDialogComponent,
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
import { costCentreError, findNode, hasSide } from '../cost-centre/cost-centre.util';
import { defaultFiscalYearId } from '../fiscal-year.util';
import {
  BudgetPlanApi,
  type BudgetPlan,
  type PlanLineSet,
  type PlanState,
  type PlanStep,
  type PlanVersion,
} from './budget-plan.api';
import {
  type PlanRow,
  addable,
  amountProblem,
  cents,
  currentVersion,
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
  plan_in_progress: 'budget.plan.error.inProgress',
  fiscal_year_closed: 'budget.fy.closedError',
};

const MONEY_COL = '6.75rem';
const FIELD_COL = '10rem';

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

  readonly wide = mediaQuery(MEDIA.wide);
  readonly phone = mediaQuery(MEDIA.phone);

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
  /** The amounts a person typed and did not leave yet, by row id and field. */
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
  readonly incomeRows = computed(() => this.tableRows().filter((r) => r.side === 'income'));
  readonly expenseRows = computed(() => this.tableRows().filter((r) => r.side === 'expense'));
  readonly incomeTotal = computed(() => sideSum(this.rows(), 'income'));
  readonly expenseTotal = computed(() => sideSum(this.rows(), 'expense'));
  readonly difference = computed(() => (cents(this.incomeTotal()) - cents(this.expenseTotal())) / 100);
  readonly balanced = computed(() => this.difference() === 0);
  readonly groups = computed(() => [
    { side: 'income' as const, heading: this.i18n.translate('budget.plan.income'), total: this.incomeTotal() },
    { side: 'expense' as const, heading: this.i18n.translate('budget.plan.expense'), total: this.expenseTotal() },
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
      ...(version?.steps ?? []).map((step) => ({ label: step.name, hint: this.stepHint(step) })),
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
  /** The row is a direct child of the budget, so it has a side. */
  sided(node: BudgetTreeNode): boolean {
    return hasSide(node, this.top());
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
  /** The budget with the Kostenstellen that can enter the draft, for the picker. */
  readonly addNodes = computed<readonly BudgetTreeNode[]>(() => {
    const top = this.top();
    return top ? [{ ...top, children: this.addableNodes().map((n) => ({ ...n, children: [] })) }] : [];
  });

  readonly columns = computed<ColumnDef[]>(() => {
    const money = (key: string, label: string, width = MONEY_COL): ColumnDef => ({ key, label, align: 'end', width });
    const prev = this.prevYear()?.display ?? '';
    const own = money('amount', this.amountLabel(), this.tableFields() ? FIELD_COL : MONEY_COL);
    const rest = this.nachtrag()
      ? [money('base', this.baseLabel())]
      : this.prevYear()
        ? [
            money('prev', this.i18n.translate('budget.plan.col.amount', { year: prev })),
            money('actual', this.i18n.translate('budget.plan.col.actual', { year: prev })),
          ]
        : [];
    return [
      { key: 'node', label: this.i18n.translate('budget.plan.col.node'), card: 'title' },
      own,
      ...rest,
      money('change', this.i18n.translate('budget.plan.col.change')),
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

  /** The step the head offers next, or `null` when the reader cannot move the version. */
  readonly primary = computed<PrimaryAction | null>(() => {
    const version = this.version();
    if (!version || !this.canWrite() || this.year()?.closedAt) return null;
    const action = (id: string, label: string, icon: IconName, reason: string | null = null): PrimaryAction => ({
      id,
      label,
      icon,
      reason,
    });
    const t = (key: TranslationKey): string => this.i18n.translate(key);
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

  /** Why the version cannot leave the draft or come into force: no line, or not balanced. */
  private readonly notReady = computed<string | null>(() =>
    !this.rows().length
      ? this.i18n.translate('budget.plan.error.empty')
      : this.balanced()
        ? null
        : this.i18n.translate('budget.plan.error.notBalanced'),
  );

  /**
   * The next action of a version that is not in force: the vote of the next step while it
   * waits for its result, a new vote after a refused one, the step by hand, or "In Kraft
   * setzen" after the last step.
   */
  private openAction(
    version: PlanVersion,
    action: (id: string, label: string, icon: IconName, reason?: string | null) => PrimaryAction,
    t: (key: TranslationKey) => string,
  ): PrimaryAction {
    const next = nextStep(version);
    const blocked = this.notReady();
    if (!next) return action('inForce', t('budget.plan.action.inForce'), 'check', blocked);
    if (this.voting() && voteRuns(next)) return action('openVote', t('budget.plan.action.openVote'), 'vote');
    if (this.voting() && next.voteStatus === 'closed')
      return action('vote', t('budget.plan.action.vote'), 'vote', blocked);
    return action(
      'step',
      this.i18n.translate('budget.plan.action.step', { name: next.name }),
      'check',
      version.state === 'draft' ? blocked : null,
    );
  }

  /** The step whose vote the page links to. */
  private readonly linkedVote = computed(() => {
    const version = this.version();
    return version && this.voting() ? voteStep(version) : null;
  });

  readonly menu = computed<readonly RowMenuSection[]>(() => {
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
      ...item('vote', 'budget.plan.action.vote', 'vote', this.canVote(), state === 'draft' ? blocked : null),
      ...item('openVote', 'budget.plan.action.openVote', 'link', !!this.linkedVote()),
      ...item('backToDraft', 'budget.plan.action.backToDraft', 'undo', !!primary && state === 'in_progress'),
      ...item('add', 'budget.plan.action.add', 'fileplus', this.editable() && this.addableNodes().length > 0),
    ];
    const draft: RowMenuItem[] =
      this.editable() && this.versions().length > 0
        ? [{ id: 'deleteDraft', label: this.i18n.translate('budget.plan.action.deleteDraft'), icon: 'trash', danger: true }]
        : [];
    return [
      ...(items.length ? [{ items }] : []),
      ...this.rowMenu(this.sel()),
      ...(draft.length ? [{ items: draft }] : []),
    ];
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

  private readonly voting = computed(() => this.features.isOn('voting'));
  /** The next step names a Gremium and has no vote that waits for its result. */
  private readonly canVote = computed(() => {
    const next = this.next();
    return !!this.primary() && this.voting() && !!next?.gremiumId && !voteRuns(next);
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
          danger: false,
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
    if (this.editable()) return { id: 'new', label: this.i18n.translate('budget.cc.create') };
    return this.load().kind === 'none' && this.canWrite() && !!this.year() && !this.year()?.closedAt
      ? { id: 'createPlan', label: this.i18n.translate('budget.plan.none.create') }
      : null;
  });

  constructor() {
    const qp = this.route.snapshot.queryParamMap;
    this.selId.set(qp.get('costCentre') ?? '');
    const wanted = Number(qp.get('version') ?? '');
    this.wantedVersion = qp.get('version') !== null && Number.isInteger(wanted) ? wanted : null;
    pageItemTitle(() => this.picked()?.name ?? null);
    const fromVote = qp.get('planVersion');
    if (fromVote) this.openVersion(fromVote as Uuid);
    else this.loadTree(qp.get('budget'), qp.get('fy'));
    if (this.canWrite())
      this.adminApi.listGremienOptions().subscribe({
        next: (list) => this.gremiumOptions.set(list.map((g) => ({ value: g.id, label: g.name }))),
        error: () => this.gremiumOptions.set([]),
      });
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

  /** Read the tree, then select the wanted budget and year, else the first budget. */
  private loadTree(wantedTop: string | null, wantedFy: string | null): void {
    this.treeApi.tree().pipe(takeUntilDestroyed()).subscribe({
      next: (tree) => {
        this.tree.set(tree);
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

  /** Select a top-level Kostenstelle and load its fiscal years. */
  pickTop(id: string, wantedFy: string | null = null): void {
    this.topId.set(id);
    this.treeApi.listFiscalYears(id as Uuid).subscribe({
      next: (years) => {
        this.years.set(years);
        this.loading.set(false);
        this.pickYear(years.find((y) => y.id === wantedFy)?.id ?? defaultFiscalYearId(years));
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Select a fiscal year and load its plan and the plan of the year before. */
  pickYear(id: string): void {
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
    forkJoin({
      plan: this.readPlan(top, id as Uuid),
      prev: prev ? this.readPlan(top, prev.id) : of(null),
    }).subscribe({
      next: ({ plan, prev: before }) => {
        this.prevPlan.set(before);
        this.load.set(plan ? { kind: 'plan', plan } : { kind: 'none' });
        const wanted = plan?.versions.find((v) => v.number === this.wantedVersion);
        this.wantedVersion = null;
        if (wanted) this.pickVersion(wanted.id);
      },
      error: () => this.load.set({ kind: 'error' }),
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

  /** Select a Kostenstelle, '' for the plan. Beside the list the heading of the detail takes the focus. */
  selectId(id: string): void {
    this.selId.set(id);
    this.syncUrl();
    if (this.wide()) setTimeout(() => this.host.nativeElement.querySelector<HTMLElement>('#bp-title')?.focus());
  }

  /** The URL names the budget, the year, the chosen version and the Kostenstelle. */
  private syncUrl(): void {
    const chosen = this.versions().find((v) => v.id === this.versionId());
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        budget: this.topId() || null,
        fy: this.fyId() || null,
        version: chosen ? chosen.number : null,
        costCentre: this.selId() || null,
      },
      replaceUrl: true,
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

  /** The year before has a plan in force, so the new plan can start as its copy. */
  readonly canCopy = computed(() => inForce(this.prevPlan()?.versions ?? []) !== null);

  /** Run an action of the head, of a menu or of the floating button. `row` is its Kostenstelle. */
  onAction(id: string, row: PlanRow | null = this.picked()): void {
    const version = this.version();
    if (this.busy()) return;
    switch (id) {
      case 'createPlan':
        this.createPlan(false);
        return;
      case 'inForce':
      case 'backToDraft':
      case 'deleteDraft':
        this.ask.set({ kind: id });
        return;
      case 'step':
        this.ask.set({ kind: 'step', name: this.next()?.name ?? '' });
        return;
      case 'removeLine':
      case 'deleteNode':
        if (row) this.ask.set({ kind: id, row });
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
      case 'vote':
        if (version) this.write(this.api.createStepVote(version.id), 'budget.plan.toast.vote');
        return;
      case 'openVote':
        void this.router.navigate(['/voting', this.linkedVote()?.voteId]);
        return;
      default:
        return;
    }
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
        this.write(this.api.passNextStep(version.id), 'budget.plan.toast.step');
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

  /** A setting of a Kostenstelle changed: the names and sides of the rows come from the tree. */
  reloadTree(plan: BudgetPlan | null = null): void {
    this.treeApi.tree().subscribe({
      next: (tree) => {
        this.tree.set(tree);
        if (plan) this.load.set({ kind: 'plan', plan });
      },
      error: () => this.reloadPlan(),
    });
  }

  /** Read the tree again after a write that changed the allocations. */
  private readTree(): void {
    this.treeApi.tree().subscribe((tree) => this.tree.set(tree));
  }

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

  /** The picker of "Kostenstelle aufnehmen" chose a Kostenstelle. The budget itself has no line. */
  pickAdd(id: string): void {
    this.addId.set(id === this.topId() ? '' : id);
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
   * of one line that follow each other do not overwrite each other.
   */
  saveLine(row: PlanRow, change: PlanLineSet): void {
    const version = this.version();
    const same =
      (change.amount === undefined || Number(change.amount) === row.amount) &&
      (change.blocked === undefined || Number(change.blocked) === row.blocked) &&
      (change.note === undefined || (change.note ?? '') === row.note) &&
      (change.transferable === undefined || change.transferable === row.transferable) &&
      (change.coverable === undefined || change.coverable === row.coverable);
    if (!version || !this.editable() || same) return;
    this.write(this.api.setLine(version.id, row.id, change), 'budget.tree.toast.saved', null, false);
  }

  /** The amount a field shows: the text a person types, else the saved amount. */
  fieldValue(row: PlanRow, field: 'amount' | 'blocked'): string | number {
    return this.edits()[`${row.id}:${field}`] ?? row[field];
  }

  /** Keep the amount a person types, as the canonical decimal string of the field. */
  edit(row: PlanRow, field: 'amount' | 'blocked', value: string | null): void {
    this.edits.update((e) => ({ ...e, [`${row.id}:${field}`]: value ?? '' }));
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

  saveNote(row: PlanRow, event: Event): void {
    this.saveLine(row, { note: (event.target as HTMLTextAreaElement).value.trim() || null });
  }

  /**
   * Run a plan write and show the plan it answers. `after` runs after the answer. A failed
   * write reloads the saved plan. A write that `locks` takes no second action while it runs;
   * the save of a field does not lock, so a second field can save beside it.
   */
  private write(
    request: Observable<BudgetPlan>,
    toast: TranslationKey,
    after: (() => void) | null = null,
    locks = true,
  ): void {
    if (locks) this.busy.set(true);
    request.subscribe({
      next: (plan) => {
        if (locks) this.busy.set(false);
        this.versionId.set('');
        this.load.set({ kind: 'plan', plan });
        this.toast.success(this.i18n.translate(toast));
        after?.();
        this.syncUrl();
      },
      error: (err: unknown) => this.fail(err),
    });
  }

  private fail(err: unknown): void {
    this.busy.set(false);
    this.toast.error(this.i18n.translate(WRITE_ERRORS[problemCode(err)] ?? 'budget.plan.error.failed'));
    this.reloadPlan();
  }

  reloadPlan(): void {
    const version = this.versionId();
    this.pickYear(this.fyId());
    this.versionId.set(version);
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
    return this.i18n.translate(row.side === 'income' ? 'budget.plan.side.income' : 'budget.plan.side.expense');
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

  /** Under a step: the date it was passed, else the state of the vote of its Gremium. */
  private stepHint(step: PlanStep): string | null {
    if (step.passedAt) return this.date(step.passedAt);
    switch (step.voteStatus) {
      case 'draft':
        return this.i18n.translate('budget.plan.vote.draft');
      case 'open':
        return this.i18n.translate('budget.plan.vote.open');
      case 'closed':
        return this.i18n.translate('budget.plan.vote.refused');
      default:
        return null;
    }
  }

  private date(iso: string | null | undefined): string {
    return iso ? new Intl.DateTimeFormat(this.i18n.formatLocale(), { dateStyle: 'medium' }).format(new Date(iso)) : '';
  }
}
