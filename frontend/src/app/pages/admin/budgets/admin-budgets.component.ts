import { ChangeDetectionStrategy, Component, ElementRef, computed, inject, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { type Observable, concat, defer, forkJoin, of } from 'rxjs';
import { catchError, last, map } from 'rxjs/operators';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  ConfirmDialogComponent,
  DataTableComponent,
  DialogComponent,
  EmptyStateComponent,
  FabComponent,
  IconComponent,
  InputComponent,
  MoveButtonsComponent,
  PageHeaderComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SectionComponent,
  SelectFieldComponent,
  type SelectOption,
  SkeletonComponent,
  StatusTextComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { errorStatus, problemCode } from '@core/api/problem';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { SimplifyPathPipe } from '@shared/budget-path';
import type { LoadState } from '@shared/forms/settings-form';
import { LoadStateComponent, loadStateOf } from '@shared/ui/load-state/load-state.component';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from '../../budget/budget-tree.api';
import { ColourFieldComponent, isColour } from '../../budget/cost-centre/colour-field.component';
import { costCentreError, keyProblem, NAME_MAX } from '../../budget/cost-centre/cost-centre.util';
import { BudgetPlanApi } from '../../budget/plan/budget-plan.api';
import { AdminApiService } from '../admin-api.service';
import {
  type StepDraft,
  cutoffProblem,
  cutoffValue,
  cutoffLabel,
  fyBlockerKey,
  movedStep,
  nextYear,
  stepsToSave,
  yearProblem,
} from './admin-budgets.util';

/** The fields of the edit form of a budget. */
interface EditForm {
  readonly key: string;
  readonly name: string;
  readonly colour: string;
  readonly active: boolean;
  readonly viewGremium: string;
  readonly decisionGremium: string;
  readonly day: number;
  readonly month: number;
  readonly plan: boolean;
  readonly steps: readonly StepDraft[];
}

/** The messages of the problem codes of a save of the edit form. */
const SAVE_ERRORS: Readonly<Record<string, TranslationKey>> = {
  plan_switch_has_plans: 'admin.budgets.error.switchHasPlans',
  plan_step_limit: 'admin.budgets.error.steps',
};

/** The largest number of steps of one budget, as the server takes them. */
const MAX_STEPS = 10;

/**
 * The page "Budgets" of Verwaltung: the top-level Kostenstellen, each with the start of its
 * fiscal year and with or without a Haushaltsplan. The Kostenstellen below a budget are no
 * setting of the platform: the Budget tab creates, edits and deletes them.
 *
 * A row opens the edit form of its budget. The form holds the key, the name, the colour,
 * the switch "Aktiv", the two Gremien, the start of the fiscal year, the switch
 * "Haushaltsplan führen" and, while that switch is on, the steps a plan version passes. The
 * switch asks for nothing: it gives each open fiscal year a draft and changes no allocation.
 * The menu of a row opens the fiscal years of the budget and deletes the budget.
 */
/** The longest name of a step that the server takes. */
const STEP_NAME_MAX = 120;

@Component({
  selector: 'app-admin-budgets',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    FormsModule,
    TranslatePipe,
    SimplifyPathPipe,
    BreadcrumbsComponent,
    ButtonComponent,
    CellDirective,
    ColourFieldComponent,
    ConfirmDialogComponent,
    DataTableComponent,
    DialogComponent,
    EmptyStateComponent,
    FabComponent,
    IconComponent,
    InputComponent,
    LoadStateComponent,
    MoveButtonsComponent,
    PageHeaderComponent,
    RowMenuComponent,
    SectionComponent,
    SelectFieldComponent,
    SkeletonComponent,
    StatusTextComponent,
    SwitchComponent,
  ],
  templateUrl: './admin-budgets.component.html',
  styleUrl: './admin-budgets.component.scss',
})
export class AdminBudgetsComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly planApi = inject(BudgetPlanApi);
  private readonly adminApi = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly auth = inject(AuthService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** The backend stays authoritative; the gate only hides what the reader cannot do. */
  readonly canStructure = computed(() => this.auth.can('budget.structure'));

  readonly budgets = signal<readonly BudgetTreeNode[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal(false);
  readonly loadState = loadStateOf(this.loading, this.loadError);
  readonly gremiumOptions = signal<SelectOption[]>([]);
  readonly busy = signal(false);

  /** The new budget: key, name and the start of its fiscal year (01.01. by default). */
  readonly newTop = signal({ key: '', name: '', day: 1, month: 1 });
  readonly topOpen = signal(false);

  /** The budget of the edit form, and the form. */
  readonly editNode = signal<BudgetTreeNode | null>(null);
  readonly form = signal<EditForm | null>(null);
  /** The steps as the server holds them, to send the list only after a change. */
  private savedSteps: readonly StepDraft[] = [];
  /** The read of the steps of the budget in the form: it runs, it failed, or the steps are there. */
  readonly stepsState = signal<LoadState>('ok');
  /** The person pressed "Speichern": the fields now show what is missing. */
  readonly showErrors = signal(false);
  readonly canAddStep = computed(() => (this.form()?.steps.length ?? 0) < MAX_STEPS);
  readonly keyError = computed(() => {
    const key = this.form()?.key.trim() ?? '';
    if (keyProblem(key)) return this.i18n.translate('budget.cc.error.keyInvalid');
    return this.showErrors() && !key ? this.i18n.translate('admin.budgets.error.required') : '';
  });
  readonly nameError = computed(() => {
    const name = this.form()?.name.trim() ?? '';
    if (name.length > NAME_MAX) return this.i18n.translate('budget.cc.error.nameLong');
    return this.showErrors() && !name ? this.i18n.translate('admin.budgets.error.required') : '';
  });
  /** The error of a field that must not be empty, once the person pressed "Speichern". */
  requiredError(value: string): string {
    return this.showErrors() && !value.trim() ? this.i18n.translate('admin.budgets.error.required') : '';
  }
  /** The error under the name of a step: it is missing, or longer than the server takes. */
  stepNameError(value: string): string {
    return value.trim().length > STEP_NAME_MAX
      ? this.i18n.translate('admin.budgets.error.stepNameLong')
      : this.requiredError(value);
  }
  readonly formValid = computed(() => {
    const form = this.form();
    return (
      !!form &&
      !!form.key.trim() &&
      !keyProblem(form.key.trim()) &&
      !!form.name.trim() &&
      form.name.trim().length <= NAME_MAX &&
      isColour(form.colour) &&
      !cutoffProblem('day', form.day) &&
      !cutoffProblem('month', form.month) &&
      (!form.plan ||
        form.steps.every((s) => !!s.name.trim() && s.name.trim().length <= STEP_NAME_MAX))
    );
  });

  readonly deleteTarget = signal<BudgetTreeNode | null>(null);
  readonly deleteBody = computed(() => {
    const node = this.deleteTarget();
    return node ? this.i18n.translate('budget.tree.deleteConfirm', { name: node.name, path: node.pathKey }) : '';
  });

  /** The budget whose fiscal years the dialogs show. */
  readonly fyBudget = signal<BudgetTreeNode | null>(null);
  readonly fiscalYears = signal<readonly FiscalYear[]>([]);
  readonly fyOpen = signal(false);
  /** The year of the new fiscal year, as the text of the field. */
  readonly newFyYear = signal('');
  readonly newFyError = computed(() => this.yearError(this.newFyYear()));
  readonly fyEdit = signal<FiscalYear | null>(null);
  readonly fyEditYear = signal('');
  readonly fyEditError = computed(() => this.yearError(this.fyEditYear()));
  readonly fyEditActive = signal(true);
  readonly fyDelete = signal<FiscalYear | null>(null);
  /**
   * The Haushaltsplan of each fiscal year of the list, by the id of the year: only a draft,
   * or with a version that left the draft. A year without a plan has no entry.
   */
  private readonly fyPlans = signal<ReadonlyMap<string, 'draft' | 'decided'>>(new Map());
  readonly fyDeleteBody = computed(() => {
    const fy = this.fyDelete();
    if (!fy) return '';
    return this.i18n.translate(
      this.fyPlans().get(fy.id) === 'draft' ? 'budget.tree.fyDeleteConfirmDraft' : 'budget.tree.fyDeleteConfirm',
      { year: fy.display },
    );
  });
  /** The fiscal year to close, or to reopen when it is closed. */
  readonly fyCloseTarget = signal<FiscalYear | null>(null);
  /** The texts of the dialog that closes or reopens a fiscal year. */
  readonly fyCloseView = computed(() => {
    const fy = this.fyCloseTarget();
    if (!fy) return null;
    const t = (key: TranslationKey): string => this.i18n.translate(key, { year: fy.display });
    return fy.closedAt
      ? { title: t('budget.tree.fyReopenTitle'), body: t('budget.tree.fyReopenConfirm'), confirm: t('budget.tree.fyReopen') }
      : { title: t('budget.tree.fyCloseTitle'), body: t('budget.tree.fyCloseConfirm'), confirm: t('budget.tree.fyClose') };
  });
  readonly fyTitle = computed(() =>
    this.i18n.translate('admin.budgets.fyTitle', { name: this.fyBudget()?.name ?? '' }),
  );

  readonly columns = computed<ColumnDef[]>(() => [
    { key: 'node', label: this.i18n.translate('admin.budgets.col.budget'), card: 'title', width: '16rem' },
    { key: 'start', label: this.i18n.translate('admin.budgets.col.start'), width: '14rem' },
    { key: 'plan', label: this.i18n.translate('admin.budgets.col.plan') },
    {
      key: 'actions',
      label: this.i18n.translate('budget.tree.col.actions'),
      align: 'end',
      width: '3.5rem',
      card: 'actions',
      sticky: 'end',
    },
  ]);
  readonly rowId = (row: unknown): string => (row as BudgetTreeNode).id;
  readonly start = cutoffLabel;

  readonly rowMenu = computed<RowMenuSection[]>(() => [
    { items: [{ id: 'years', label: this.i18n.translate('budget.tree.fyTitle'), icon: 'cal' }] },
    { items: [{ id: 'delete', label: this.i18n.translate('budget.tree.delete'), icon: 'trash', danger: true }] },
  ]);

  readonly fyColumns = computed<ColumnDef[]>(() => [
    { key: 'display', label: this.i18n.translate('budget.tree.fyYear'), card: 'title' },
    { key: 'active', label: this.i18n.translate('budget.tree.fyState') },
    ...(this.canStructure()
      ? [
          {
            key: 'actions',
            label: this.i18n.translate('budget.tree.col.actions'),
            align: 'end' as const,
            width: '3.5rem',
            card: 'actions' as const,
          },
        ]
      : []),
  ]);
  readonly fyRowId = (row: unknown): string => (row as FiscalYear).id;

  constructor() {
    this.reload();
    this.adminApi.listGremienOptions().subscribe({
      next: (list) => this.gremiumOptions.set(list.map((g) => ({ value: g.id, label: g.name }))),
      error: () => this.gremiumOptions.set([]),
    });
  }

  reload(): void {
    this.loadError.set(false);
    this.api.tree().subscribe({
      next: (tree) => {
        this.budgets.set(tree.filter((n) => n.parentId === null));
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  private fail(err: unknown, fallback: TranslationKey = 'budget.tree.toast.failed'): void {
    this.busy.set(false);
    this.toast.error(this.i18n.translate(costCentreError(problemCode(err), fallback)));
  }

  onRowMenu(budget: BudgetTreeNode, item: RowMenuItem): void {
    if (item.id === 'years') this.openFy(budget);
    else this.deleteTarget.set(budget);
  }

  openTop(): void {
    this.newTop.set({ key: '', name: '', day: 1, month: 1 });
    this.topOpen.set(true);
  }

  patchTop(field: 'key' | 'name', value: string): void {
    this.newTop.update((t) => ({ ...t, [field]: value }));
  }

  patchTopCutoff(field: 'day' | 'month', value: string): void {
    this.newTop.update((t) => ({ ...t, [field]: cutoffValue(value) }));
  }

  readonly topKeyError = computed(() =>
    keyProblem(this.newTop().key.trim()) ? this.i18n.translate('budget.cc.error.keyInvalid') : '',
  );
  readonly topValid = computed(() => {
    const t = this.newTop();
    return (
      !!t.key.trim() &&
      !keyProblem(t.key.trim()) &&
      !!t.name.trim() &&
      t.name.trim().length <= NAME_MAX &&
      !cutoffProblem('day', t.day) &&
      !cutoffProblem('month', t.month)
    );
  });

  /** The error under the day or the month of the start of the fiscal year. */
  cutoffError(field: 'day' | 'month', value: number): string {
    return cutoffProblem(field, value)
      ? this.i18n.translate(field === 'day' ? 'admin.budgets.error.day' : 'admin.budgets.error.month')
      : '';
  }

  createTop(event: Event): void {
    event.preventDefault();
    const t = this.newTop();
    if (!this.topValid() || this.busy()) return;
    this.busy.set(true);
    this.api
      .createNode({ key: t.key.trim(), name: t.name.trim(), fiscalStartDay: t.day, fiscalStartMonth: t.month })
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.toast.success(this.i18n.translate('admin.budgets.toast.created'));
          this.topOpen.set(false);
          this.reload();
        },
        error: (err: unknown) => this.fail(err),
      });
  }

  /** Open the edit form of a budget. The steps load with it when the budget has a plan. */
  openEdit(budget: BudgetTreeNode): void {
    this.savedSteps = [];
    this.showErrors.set(false);
    this.editNode.set(budget);
    this.form.set({
      key: budget.key,
      name: budget.name,
      colour: budget.color?.trim() ?? '',
      active: budget.active,
      viewGremium: budget.viewGremiumId ?? '',
      decisionGremium: budget.decisionGremiumId ?? '',
      day: budget.fiscalStartDay,
      month: budget.fiscalStartMonth,
      plan: !!budget.planEnabled,
      steps: [],
    });
    this.loadSteps();
  }

  /**
   * Read the steps of the budget in the form. A failed read shows the load error in place
   * of the steps, so the form never takes an unread list for an empty one and never
   * replaces the stored steps.
   */
  loadSteps(): void {
    const budget = this.editNode();
    if (!budget) return;
    this.stepsState.set('loading');
    this.planApi.steps(budget.id).subscribe({
      next: (out) => {
        if (this.editNode()?.id !== budget.id) return;
        this.savedSteps = out.steps.map((s) => ({ name: s.name, gremiumId: s.gremiumId ?? '' }));
        this.patch({ steps: this.savedSteps });
        this.stepsState.set('ok');
      },
      error: () => {
        if (this.editNode()?.id === budget.id) this.stepsState.set('error');
      },
    });
  }

  closeEdit(): void {
    this.editNode.set(null);
    this.form.set(null);
  }

  patch(change: Partial<EditForm>): void {
    this.form.update((f) => (f ? { ...f, ...change } : f));
  }

  patchCutoff(field: 'day' | 'month', value: string): void {
    this.patch({ [field]: cutoffValue(value) });
  }

  private steps(change: (steps: readonly StepDraft[]) => readonly StepDraft[]): void {
    this.form.update((f) => (f ? { ...f, steps: change(f.steps) } : f));
  }

  addStep(): void {
    this.steps((list) => [...list, { name: '', gremiumId: '' }]);
  }

  patchStep(index: number, change: Partial<StepDraft>): void {
    this.steps((list) => list.map((s, i) => (i === index ? { ...s, ...change } : s)));
  }

  moveStep(index: number, by: -1 | 1): void {
    this.steps((list) => movedStep(list, index, by));
  }

  removeStep(index: number): void {
    this.steps((list) => list.filter((_, i) => i !== index));
  }

  /**
   * Save the edit form. A form with a missing field saves nothing, shows what is missing and
   * brings the first such field into view. The order of the save is: the plan switch when it
   * changed, then the settings of the budget, then the steps when they changed. A request
   * goes out only after the one before it succeeded. The deciding Gremium goes out only on a
   * change, because each sent field is audited.
   */
  saveEdit(): void {
    const node = this.editNode();
    const form = this.form();
    if (!node || !form || this.busy()) return;
    this.showErrors.set(true);
    if (!this.formValid()) {
      setTimeout(() => this.host.nativeElement.ownerDocument.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus());
      return;
    }
    this.saveRest(node, form);
  }

  /** The requests of the save: the plan switch, the settings of the budget, the steps. */
  private saveRest(node: BudgetTreeNode, form: EditForm): void {
    const steps = stepsToSave(form.steps);
    const sameSteps = JSON.stringify(steps) === JSON.stringify(stepsToSave(this.savedSteps));
    const requests: Observable<unknown>[] = [
      ...(form.plan !== !!node.planEnabled ? [defer(() => this.planApi.setPlanSwitch(node.id, form.plan))] : []),
      defer(() =>
        this.api.updateNode(node.id, {
          key: form.key.trim(),
          name: form.name.trim(),
          color: form.colour,
          active: form.active,
          viewGremiumId: form.viewGremium || null,
          ...(form.decisionGremium !== (node.decisionGremiumId ?? '')
            ? { decisionGremiumId: form.decisionGremium || null }
            : {}),
          ...(form.day !== node.fiscalStartDay ? { fiscalStartDay: form.day } : {}),
          ...(form.month !== node.fiscalStartMonth ? { fiscalStartMonth: form.month } : {}),
        }),
      ),
      ...(form.plan && !sameSteps && this.stepsState() === 'ok' ? [defer(() => this.planApi.setSteps(node.id, steps))] : []),
    ];
    this.busy.set(true);
    concat(...requests)
      .pipe(last())
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.toast.success(this.i18n.translate('budget.tree.toast.saved'));
          this.closeEdit();
          this.reload();
        },
        error: (err: unknown) => this.saveFailed(err),
      });
  }

  /**
   * A request of the save failed: the toast names the reason, and the dialog stays open on
   * the budget as the server holds it now, so a second save sends only what is left.
   */
  private saveFailed(err: unknown): void {
    this.busy.set(false);
    const code = problemCode(err);
    this.toast.error(this.i18n.translate(SAVE_ERRORS[code] ?? costCentreError(code, 'admin.budgets.error.save')));
    const id = this.editNode()?.id;
    this.api.tree().subscribe({
      next: (tree) => {
        this.budgets.set(tree.filter((n) => n.parentId === null));
        const fresh = this.budgets().find((n) => n.id === id);
        if (fresh && this.editNode()?.id === id) this.editNode.set(fresh);
      },
      error: () => undefined,
    });
  }

  /** Delete the budget after the confirmation. A refusal closes the dialog and names its reason. */
  deleteBudget(): void {
    const node = this.deleteTarget();
    if (!node || this.busy()) return;
    this.busy.set(true);
    this.api.deleteNode(node.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.success(this.i18n.translate('admin.budgets.toast.deleted'));
        this.deleteTarget.set(null);
        this.reload();
      },
      error: (err: unknown) => {
        this.deleteTarget.set(null);
        this.fail(err, 'budget.tree.toast.deleteFailed');
      },
    });
  }

  /** Open the fiscal years of a budget. */
  openFy(budget: BudgetTreeNode): void {
    this.fyBudget.set(budget);
    this.fiscalYears.set([]);
    this.newFyYear.set('');
    this.fyOpen.set(true);
    this.loadFiscalYears();
  }

  private loadFiscalYears(): void {
    const budget = this.fyBudget();
    if (!budget) return;
    this.api.listFiscalYears(budget.id).subscribe({
      next: (years) => {
        if (this.fyBudget()?.id !== budget.id) return;
        this.fiscalYears.set([...years].sort((a, b) => b.year - a.year));
        this.newFyYear.set(String(nextYear(years, new Date().getFullYear())));
        this.loadFyPlans(budget, years);
      },
      error: () => this.fiscalYears.set([]),
    });
  }

  /**
   * Read the Haushaltsplan of each year, so the menu of a year knows before the press if
   * the delete takes a draft along or is refused. A failed read leaves the year without an
   * entry, and the server then decides.
   */
  private loadFyPlans(budget: BudgetTreeNode, years: readonly FiscalYear[]): void {
    this.fyPlans.set(new Map());
    if (!budget.planEnabled || !years.length) return;
    forkJoin(
      years.map((fy) =>
        this.planApi.plan(budget.id, fy.id).pipe(
          map((plan) => [fy.id, plan.versions.every((v) => v.state === 'draft') ? 'draft' : 'decided'] as const),
          catchError(() => of(null)),
        ),
      ),
    ).subscribe((entries) => {
      if (this.fyBudget()?.id === budget.id) this.fyPlans.set(new Map(entries.filter((e) => e !== null)));
    });
  }

  /** The error under a year field: the year is a whole number from 1900 to 2200. */
  private yearError(text: string): string {
    return yearProblem(text) ? this.i18n.translate('budget.tree.fyYearInvalid') : '';
  }

  /** The message of a refused fiscal-year write. */
  private fyError(err: unknown, fallback: TranslationKey): void {
    this.busy.set(false);
    const code = problemCode(err);
    this.toast.error(this.i18n.translate(code === 'fiscal_year_exists' ? 'budget.tree.toast.fyDuplicate' : fyBlockerKey(code, fallback)));
  }

  createFiscalYear(event: Event): void {
    event.preventDefault();
    const budget = this.fyBudget();
    if (!budget || yearProblem(this.newFyYear()) || this.busy()) return;
    this.busy.set(true);
    this.api.createFiscalYear(budget.id, { year: Number(this.newFyYear()) }).subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.success(this.i18n.translate('budget.tree.toast.fyCreated'));
        this.loadFiscalYears();
      },
      error: (err: unknown) => this.fyError(err, 'budget.tree.toast.fyFailed'),
    });
  }

  fyMenu(fy: FiscalYear): RowMenuSection[] {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    return [
      {
        items: [
          fy.closedAt
            ? { id: 'reopen', label: t('budget.tree.fyReopen'), icon: 'undo' }
            : { id: 'close', label: t('budget.tree.fyClose'), icon: 'lock' },
        ],
      },
      {
        items: [
          {
            id: 'delete',
            label: t('budget.tree.fyDelete'),
            icon: 'trash',
            danger: true,
            disabledReason: fy.closedAt
              ? t('budget.fy.closedError')
              : this.fyPlans().get(fy.id) === 'decided'
                ? t('budget.tree.fyBlocked.plan')
                : null,
          },
        ],
      },
    ];
  }

  /** Each dialog on a fiscal year closes the list first and opens it again afterwards, so no two dialogs stack. */
  onFyMenu(fy: FiscalYear, item: RowMenuItem): void {
    this.fyOpen.set(false);
    if (item.id !== 'delete') {
      this.fyCloseTarget.set(fy);
      return;
    }
    this.fyDelete.set(fy);
  }

  openFyEdit(fy: FiscalYear): void {
    this.fyOpen.set(false);
    this.fyEdit.set(fy);
    this.fyEditYear.set(String(fy.year));
    this.fyEditActive.set(fy.active);
  }

  /** Close a dialog on one fiscal year and show the list again. */
  backToYears(): void {
    this.fyEdit.set(null);
    this.fyCloseTarget.set(null);
    this.fyDelete.set(null);
    this.fyOpen.set(true);
  }

  /**
   * Run a write on one fiscal year. A success shows the list of years again. A refusal does
   * so too, except for a form (`keepOpen`): it stays open with what the person typed.
   */
  private fyWrite(request: Observable<unknown>, toast: string, fallback: TranslationKey, keepOpen = false): void {
    if (this.busy()) return;
    this.busy.set(true);
    request.subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.success(toast);
        this.backToYears();
        this.loadFiscalYears();
      },
      error: (err: unknown) => {
        this.fyError(err, errorStatus(err) === 409 ? 'budget.tree.fyBlocked.generic' : fallback);
        if (!keepOpen) this.backToYears();
      },
    });
  }

  saveFyEdit(): void {
    const fy = this.fyEdit();
    const budget = this.fyBudget();
    if (!fy || !budget || yearProblem(this.fyEditYear())) return;
    this.fyWrite(
      this.api.updateFiscalYear(budget.id, fy.id, { year: Number(this.fyEditYear()), active: this.fyEditActive() }),
      this.i18n.translate('budget.tree.toast.fySaved'),
      'budget.tree.toast.fyFailed',
      true,
    );
  }

  /** Close the target year, or reopen it when it is closed. */
  doFyClose(): void {
    const fy = this.fyCloseTarget();
    const budget = this.fyBudget();
    if (!fy || !budget) return;
    const close = !fy.closedAt;
    this.fyWrite(
      this.api.setFiscalYearClosed(budget.id, fy.id, close),
      this.i18n.translate(close ? 'budget.tree.toast.fyClosed' : 'budget.tree.toast.fyReopened', { year: fy.display }),
      'budget.tree.toast.failed',
    );
  }

  doFyDelete(): void {
    const fy = this.fyDelete();
    const budget = this.fyBudget();
    if (!fy || !budget) return;
    this.fyWrite(
      this.api.deleteFiscalYear(budget.id, fy.id),
      this.i18n.translate('budget.tree.toast.fyDeleted'),
      'budget.tree.toast.fyDeleteFailed',
    );
  }

  asBudget(row: unknown): BudgetTreeNode {
    return row as BudgetTreeNode;
  }

  asYear(row: unknown): FiscalYear {
    return row as FiscalYear;
  }
}
