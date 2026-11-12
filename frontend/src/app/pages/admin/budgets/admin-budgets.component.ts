import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { type Observable, concat, of } from 'rxjs';
import { last } from 'rxjs/operators';
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
  NoteComponent,
  PageHeaderComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SectionComponent,
  SelectFieldComponent,
  type SelectOption,
  StatusTextComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { problemCode } from '@core/api/problem';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from '../../budget/budget-tree.api';
import { ColourFieldComponent, isColour } from '../../budget/cost-centre/colour-field.component';
import { costCentreError } from '../../budget/cost-centre/cost-centre.util';
import { BudgetPlanApi } from '../../budget/plan/budget-plan.api';
import { AdminApiService } from '../admin-api.service';
import { type StepDraft, clampCutoff, cutoffLabel, fyBlockerKey, movedStep, stepsToSave } from './admin-budgets.util';

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
 * menu of a row opens the fiscal years of the budget and deletes the budget.
 */
@Component({
  selector: 'app-admin-budgets',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    FormsModule,
    TranslatePipe,
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
    MoveButtonsComponent,
    NoteComponent,
    PageHeaderComponent,
    RowMenuComponent,
    SectionComponent,
    SelectFieldComponent,
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

  /** The backend stays authoritative; the gate only hides what the reader cannot do. */
  readonly canStructure = computed(() => this.auth.can('budget.structure'));

  readonly budgets = signal<readonly BudgetTreeNode[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal(false);
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
  readonly canAddStep = computed(() => (this.form()?.steps.length ?? 0) < MAX_STEPS);
  readonly formValid = computed(() => {
    const form = this.form();
    return (
      !!form &&
      !!form.key.trim() &&
      !!form.name.trim() &&
      isColour(form.colour) &&
      (!form.plan || form.steps.every((s) => !!s.name.trim()))
    );
  });

  readonly deleteTarget = signal<BudgetTreeNode | null>(null);
  /** The reason why the delete was refused, else `null`. */
  readonly deleteBlocked = signal<string | null>(null);

  /** The budget whose fiscal years the dialogs show. */
  readonly fyBudget = signal<BudgetTreeNode | null>(null);
  readonly fiscalYears = signal<readonly FiscalYear[]>([]);
  readonly fyOpen = signal(false);
  readonly newFyYear = signal(new Date().getFullYear());
  readonly fyEdit = signal<FiscalYear | null>(null);
  readonly fyEditYear = signal(new Date().getFullYear());
  readonly fyEditActive = signal(true);
  readonly fyDelete = signal<FiscalYear | null>(null);
  readonly fyDeleteBlocked = signal<string | null>(null);
  /** The fiscal year to close, or to reopen when it is closed. */
  readonly fyCloseTarget = signal<FiscalYear | null>(null);
  readonly fyBudgetLabel = computed(() => {
    const b = this.fyBudget();
    return b ? `${b.key} – ${b.name}` : '';
  });

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

  private reload(): void {
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
    else {
      this.deleteBlocked.set(null);
      this.deleteTarget.set(budget);
    }
  }

  openTop(): void {
    this.newTop.set({ key: '', name: '', day: 1, month: 1 });
    this.topOpen.set(true);
  }

  patchTop(field: 'key' | 'name', value: string): void {
    this.newTop.update((t) => ({ ...t, [field]: value }));
  }

  patchTopCutoff(field: 'day' | 'month', value: string): void {
    this.newTop.update((t) => ({ ...t, [field]: clampCutoff(field, value) }));
  }

  createTop(event: Event): void {
    event.preventDefault();
    const t = this.newTop();
    if (!t.key.trim() || !t.name.trim()) return;
    this.api
      .createNode({ key: t.key.trim(), name: t.name.trim(), fiscalStartDay: t.day, fiscalStartMonth: t.month })
      .subscribe({
        next: () => {
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
    this.planApi.steps(budget.id).subscribe({
      next: (out) => {
        if (this.editNode()?.id !== budget.id) return;
        this.savedSteps = out.steps.map((s) => ({ name: s.name, gremiumId: s.gremiumId ?? '' }));
        this.patch({ steps: this.savedSteps });
      },
      error: () => undefined,
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
    this.patch({ [field]: clampCutoff(field, value) });
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
   * Save the edit form: the settings of the budget, then the plan switch when it changed,
   * then the steps when they changed. The deciding Gremium goes out only on a change,
   * because each sent field is audited.
   */
  saveEdit(): void {
    const node = this.editNode();
    const form = this.form();
    if (!node || !form || !this.formValid() || this.busy()) return;
    const steps = stepsToSave(form.steps);
    const sameSteps = JSON.stringify(steps) === JSON.stringify(stepsToSave(this.savedSteps));
    const requests: Observable<unknown>[] = [
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
      ...(form.plan !== !!node.planEnabled ? [this.planApi.setPlanSwitch(node.id, form.plan)] : []),
      ...(form.plan && !sameSteps ? [this.planApi.setSteps(node.id, steps)] : []),
    ];
    this.busy.set(true);
    concat(...requests, of(null))
      .pipe(last())
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.toast.success(this.i18n.translate('budget.tree.toast.saved'));
          this.closeEdit();
          this.reload();
        },
        error: (err: unknown) => {
          this.fail(err, 'admin.budgets.error.save');
          this.reload();
        },
      });
  }

  closeDelete(): void {
    this.deleteTarget.set(null);
    this.deleteBlocked.set(null);
  }

  /** Delete the budget after the confirmation. A refusal names its reason in the dialog. */
  deleteBudget(): void {
    const node = this.deleteTarget();
    if (!node) return;
    this.api.deleteNode(node.id).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('admin.budgets.toast.deleted'));
        this.closeDelete();
        this.reload();
      },
      error: (err: unknown) =>
        this.deleteBlocked.set(this.i18n.translate(costCentreError(problemCode(err), 'budget.tree.toast.deleteFailed'))),
    });
  }

  /** Open the fiscal years of a budget. */
  openFy(budget: BudgetTreeNode): void {
    this.fyBudget.set(budget);
    this.fiscalYears.set([]);
    this.newFyYear.set(new Date().getFullYear());
    this.fyOpen.set(true);
    this.loadFiscalYears();
  }

  private loadFiscalYears(): void {
    const budget = this.fyBudget();
    if (!budget) return;
    this.api.listFiscalYears(budget.id).subscribe({
      next: (years) => {
        if (this.fyBudget()?.id === budget.id) this.fiscalYears.set([...years].sort((a, b) => b.year - a.year));
      },
      error: () => this.fiscalYears.set([]),
    });
  }

  patchFyYear(value: string): void {
    this.newFyYear.set(Math.trunc(Number(value)) || new Date().getFullYear());
  }

  createFiscalYear(event: Event): void {
    event.preventDefault();
    const budget = this.fyBudget();
    if (!budget) return;
    this.api.createFiscalYear(budget.id, { year: this.newFyYear() }).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.fyCreated'));
        this.loadFiscalYears();
      },
      error: () => this.toast.error(this.i18n.translate('budget.tree.toast.fyFailed')),
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
            disabledReason: fy.closedAt ? t('budget.fy.closedError') : null,
          },
        ],
      },
    ];
  }

  /** Each dialog on a fiscal year closes the list first and opens it again afterwards, so no two dialogs stack. */
  onFyMenu(fy: FiscalYear, item: RowMenuItem): void {
    this.fyOpen.set(false);
    if (item.id === 'delete') {
      this.fyDeleteBlocked.set(null);
      this.fyDelete.set(fy);
    } else this.fyCloseTarget.set(fy);
  }

  openFyEdit(fy: FiscalYear): void {
    this.fyOpen.set(false);
    this.fyEdit.set(fy);
    this.fyEditYear.set(fy.year);
    this.fyEditActive.set(fy.active);
  }

  patchFyEditYear(value: string): void {
    this.fyEditYear.set(Math.trunc(Number(value)) || new Date().getFullYear());
  }

  /** Close a dialog on one fiscal year and show the list again. */
  backToYears(): void {
    this.fyEdit.set(null);
    this.fyCloseTarget.set(null);
    this.fyDelete.set(null);
    this.fyDeleteBlocked.set(null);
    this.fyOpen.set(true);
  }

  private fyWrite(request: Observable<unknown>, toast: string, failed: (err: unknown) => void): void {
    request.subscribe({
      next: () => {
        this.toast.success(toast);
        this.backToYears();
        this.loadFiscalYears();
      },
      error: failed,
    });
  }

  saveFyEdit(): void {
    const fy = this.fyEdit();
    const budget = this.fyBudget();
    if (!fy || !budget) return;
    this.fyWrite(
      this.api.updateFiscalYear(budget.id, fy.id, { year: this.fyEditYear(), active: this.fyEditActive() }),
      this.i18n.translate('budget.tree.toast.fySaved'),
      (err) =>
        this.toast.error(
          this.i18n.translate(
            (err as { status?: number })?.status === 422 ? 'budget.tree.toast.fyDuplicate' : 'budget.tree.toast.fyFailed',
          ),
        ),
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
      () => this.toast.error(this.i18n.translate('budget.tree.toast.failed')),
    );
  }

  doFyDelete(): void {
    const fy = this.fyDelete();
    const budget = this.fyBudget();
    if (!fy || !budget) return;
    this.fyWrite(this.api.deleteFiscalYear(budget.id, fy.id), this.i18n.translate('budget.tree.toast.fyDeleted'), (err) => {
      const refused = err as { status?: number; error?: { detail?: string } };
      if (refused?.status === 409) this.fyDeleteBlocked.set(this.i18n.translate(fyBlockerKey(refused.error?.detail)));
      else this.toast.error(this.i18n.translate('budget.tree.toast.fyDeleteFailed'));
    });
  }

  asBudget(row: unknown): BudgetTreeNode {
    return row as BudgetTreeNode;
  }

  asYear(row: unknown): FiscalYear {
    return row as FiscalYear;
  }
}
