import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { type Observable, forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  ConfirmDialogComponent,
  CurrencyInputComponent,
  DataTableComponent,
  DialogComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  IconComponent,
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
  type Step,
  StepperComponent,
  SwitchComponent,
  TextareaComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { errorStatus, problemCode } from '@core/api/problem';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { SimplifyPathPipe } from '@shared/budget-path';
import { formatMoney } from '@shared/format-money';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from '../budget-tree.api';
import {
  BudgetPlanApi,
  type BudgetPlan,
  type PlanLineSet,
  type PlanState,
  type PlanVersion,
} from './budget-plan.api';
import {
  PLAN_STEPS,
  type PlanRow,
  addable,
  cents,
  currentVersion,
  inForce,
  planRows,
  sideSum,
  stepIndex,
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
  readonly icon: 'check' | 'fileplus';
  readonly disabled: boolean;
}

/** The problem codes of a plan write that have their own message. */
const WRITE_ERRORS: Readonly<Record<string, TranslationKey>> = {
  plan_line_below_children: 'budget.plan.error.belowChildren',
  plan_blocked_above_amount: 'budget.plan.error.blockedAbove',
  plan_line_has_children: 'budget.plan.error.hasChildren',
  plan_not_balanced: 'budget.plan.error.notBalanced',
  plan_version_locked: 'budget.plan.error.locked',
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
    BadgeComponent,
    ButtonComponent,
    CellDirective,
    ConfirmDialogComponent,
    CurrencyInputComponent,
    DataTableComponent,
    DialogComponent,
    EmptyStateComponent,
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
  /** The selected Kostenstelle; '' is the top-level one, so the detail shows the plan. */
  readonly selId = signal('');
  /** The Kostenstelle of the bottom sheet on a narrow screen. */
  readonly sheetId = signal('');
  readonly query = signal('');
  readonly load = signal<PlanLoad>({ kind: 'loading' });
  /** The plan of the year before, for the columns of the year before. */
  private readonly prevPlan = signal<BudgetPlan | null>(null);
  readonly busy = signal(false);
  readonly confirmInForce = signal(false);
  readonly addOpen = signal(false);
  readonly addId = signal('');
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
  /** The version in force, when the shown version is a Nachtrag that is not in force yet. */
  private readonly base = computed(() => {
    const version = this.version();
    const current = inForce(this.versions());
    return version && current && version.number > current.number ? current : null;
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
  readonly incomeRows = computed(() => this.rows().filter((r) => r.side === 'income'));
  readonly expenseRows = computed(() => this.rows().filter((r) => r.side === 'expense'));
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

  readonly sel = computed(() => this.rows().find((r) => r.id === this.selId()) ?? null);
  readonly sheetRow = computed(() => this.rows().find((r) => r.id === this.sheetId()) ?? null);
  /** The direct child rows of the selected Kostenstelle. */
  readonly childRows = computed(() => this.rows().filter((r) => r.parentId === this.selId()));

  readonly steps = computed<Step[]>(() => {
    const version = this.version();
    const dates = [null, version?.resolvedAt, version?.approvedAt, version?.inForceAt];
    return PLAN_STEPS.map((state, i) => ({
      label: this.stateLabel(state),
      hint: dates[i] ? this.date(dates[i]) : null,
    }));
  });
  readonly stepAt = computed(() => stepIndex(this.version()?.state ?? 'draft'));

  /** The Kostenstellen that can enter the draft. */
  readonly addOptions = computed<SelectOption[]>(() => {
    const top = this.top();
    const version = this.version();
    return top && version ? addable(top, version).map((n) => ({ value: n.id, label: `${n.name} (${n.pathKey})` })) : [];
  });

  readonly columns = computed<ColumnDef[]>(() => {
    const money = (key: string, label: string, width = MONEY_COL): ColumnDef => ({ key, label, align: 'end', width });
    const year = this.year()?.display ?? '';
    const prev = this.prevYear()?.display ?? '';
    const version = this.version();
    const own = money(
      'amount',
      this.nachtrag() && version ? this.versionName(version) : this.i18n.translate('budget.plan.col.amount', { year }),
      this.tableFields() ? FIELD_COL : MONEY_COL,
    );
    const rest = this.nachtrag()
      ? [money('base', this.i18n.translate('budget.plan.col.base'))]
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

  /** The step the head offers next, or `null` when the reader cannot move the version. */
  readonly primary = computed<PrimaryAction | null>(() => {
    const version = this.version();
    if (!version || !this.canWrite() || this.year()?.closedAt) return null;
    const action = (id: string, key: TranslationKey, disabled = false, icon: 'check' | 'fileplus' = 'check') => ({
      id,
      label: this.i18n.translate(key),
      icon,
      disabled,
    });
    switch (version.state) {
      case 'draft':
        return action('resolved', 'budget.plan.action.resolve', !this.balanced());
      case 'resolved':
        return action('approved', 'budget.plan.action.approve');
      case 'approved':
        return action('in_force', 'budget.plan.action.inForce');
      case 'in_force':
        return currentVersion(this.versions())?.id === version.id
          ? action('nachtrag', 'budget.plan.action.nachtrag', false, 'fileplus')
          : null;
      case 'replaced':
        return null;
    }
  });

  readonly menu = computed<readonly RowMenuSection[]>(() => {
    const primary = this.primary();
    const state = this.version()?.state;
    const item = (id: string, key: TranslationKey, icon: RowMenuItem['icon'], show: boolean): RowMenuItem[] =>
      show ? [{ id, label: this.i18n.translate(key), icon }] : [];
    const items: RowMenuItem[] = [
      ...(primary && this.phone()
        ? [
            {
              id: primary.id,
              label: primary.label,
              icon: primary.icon,
              disabledReason: primary.disabled ? this.i18n.translate('budget.plan.error.notBalanced') : null,
            },
          ]
        : []),
      ...item('draft', 'budget.plan.action.backToDraft', 'undo', this.canWrite() && state === 'resolved'),
      ...item('add', 'budget.plan.action.add', 'plus', this.editable() && this.addOptions().length > 0),
      ...item('remove', 'budget.plan.action.remove', 'trash', this.editable() && !!this.sel()),
    ];
    return items.length ? [{ items }] : [];
  });

  constructor() {
    const qp = this.route.snapshot.queryParamMap;
    this.selId.set(qp.get('costCentre') ?? '');
    this.treeApi.tree().pipe(takeUntilDestroyed()).subscribe({
      next: (tree) => {
        this.tree.set(tree);
        const tops = this.tops();
        if (!tops.length) {
          void this.router.navigate(['/budget'], { replaceUrl: true });
          return;
        }
        if (!this.top()) this.pickTop((tops.find((t) => t.id === qp.get('budget')) ?? tops[0]).id, qp.get('fy'));
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
        const newest = years.reduce<FiscalYear | null>((n, y) => (!n || y.year > n.year ? y : n), null);
        this.pickYear(years.find((y) => y.id === wantedFy)?.id ?? newest?.id ?? '');
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
    const id = (row as PlanRow).id;
    if (this.wide()) this.selectId(id);
    else this.sheetId.set(id);
  }

  selectId(id: string): void {
    this.selId.set(id);
    this.syncUrl();
  }

  private syncUrl(): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { budget: this.topId() || null, fy: this.fyId() || null, costCentre: this.selId() || null },
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

  onAction(id: string): void {
    const version = this.version();
    if (!version) return;
    switch (id) {
      case 'in_force':
        this.confirmInForce.set(true);
        return;
      case 'nachtrag':
        this.write(this.api.createNachtrag(this.topId() as Uuid, this.fyId() as Uuid), 'budget.plan.toast.nachtrag');
        return;
      case 'add':
        this.addId.set('');
        this.addOpen.set(true);
        return;
      case 'remove':
        this.removeLine();
        return;
      default:
        this.write(this.api.setState(version.id, id as PlanState), 'budget.plan.toast.state');
    }
  }

  setInForce(): void {
    const version = this.version();
    this.confirmInForce.set(false);
    if (version) this.write(this.api.setState(version.id, 'in_force'), 'budget.plan.toast.inForce', true);
  }

  /** Take the chosen Kostenstelle into the draft with an Ansatz of 0 €. */
  addLine(event: Event): void {
    event.preventDefault();
    const version = this.version();
    const id = this.addId();
    if (!version || !id) return;
    this.addOpen.set(false);
    this.write(
      this.api.setLine(version.id, id as Uuid, { amount: '0', note: null, transferable: false, coverable: false, blocked: '0' }),
      'budget.plan.toast.added',
    );
  }

  private removeLine(): void {
    const version = this.version();
    const row = this.sel();
    if (!version || !row) return;
    this.selId.set(row.parentId ?? '');
    this.write(this.api.deleteLine(version.id, row.id), 'budget.plan.toast.removed');
  }

  /** Save one field of a line. A value that did not change sends nothing. */
  saveLine(row: PlanRow, change: Partial<PlanLineSet>): void {
    const version = this.version();
    const current: PlanLineSet = {
      amount: row.amount.toFixed(2),
      note: row.note || null,
      transferable: row.transferable,
      coverable: row.coverable,
      blocked: row.blocked.toFixed(2),
    };
    const next: PlanLineSet = { ...current, ...change };
    const same =
      Number(next.amount) === Number(current.amount) &&
      Number(next.blocked) === Number(current.blocked) &&
      (next.note ?? '') === (current.note ?? '') &&
      next.transferable === current.transferable &&
      next.coverable === current.coverable;
    if (!version || !this.editable() || same) return;
    this.write(this.api.setLine(version.id, row.id, next));
  }

  /** Keep the amount a person types, as the canonical decimal string of the field. */
  edit(row: PlanRow, field: 'amount' | 'blocked', value: string): void {
    this.edits.update((e) => ({ ...e, [`${row.id}:${field}`]: value }));
  }

  /** An amount field lost the focus: save the typed amount. An invalid text saves nothing. */
  saveAmount(row: PlanRow, field: 'amount' | 'blocked' = 'amount'): void {
    const key = `${row.id}:${field}`;
    const value = this.edits()[key];
    if (value === undefined) return;
    this.edits.update((e) => Object.fromEntries(Object.entries(e).filter(([k]) => k !== key)));
    if (value !== '') this.saveLine(row, { [field]: value });
  }

  saveNote(row: PlanRow, event: Event): void {
    this.saveLine(row, { note: (event.target as HTMLTextAreaElement).value.trim() || null });
  }

  /** Run a plan write and show the plan it answers. A failed write reloads the saved plan. */
  private write(request: Observable<BudgetPlan>, toast?: TranslationKey, allocations = false): void {
    this.busy.set(true);
    request.subscribe({
      next: (plan) => {
        this.busy.set(false);
            this.versionId.set('');
        this.load.set({ kind: 'plan', plan });
        if (toast) this.toast.success(this.i18n.translate(toast));
        if (allocations) this.treeApi.tree().subscribe((tree) => this.tree.set(tree));
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

  /** The Ansatz against the version in force for a Nachtrag, else against the year before. */
  changeText(row: PlanRow): string {
    const against = this.nachtrag() ? (row.base ?? 0) : row.prev;
    const change = against === null ? 0 : cents(row.amount) - cents(against);
    if (change === 0) return '–';
    return (change > 0 ? '+' : '−') + this.money(Math.abs(change) / 100);
  }

  private date(iso: string | null | undefined): string {
    return iso ? new Intl.DateTimeFormat(this.i18n.formatLocale(), { dateStyle: 'medium' }).format(new Date(iso)) : '';
  }
}
