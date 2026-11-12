import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DialogComponent,
  InputComponent,
  SegmentedComponent,
  SelectFieldComponent,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import { problemCode } from '@core/api/problem';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { BudgetTreeApi, type BudgetTreeNode } from '../budget-tree.api';
import { BudgetPlanApi, type BudgetPlan, type Side } from '../plan/budget-plan.api';
import { costCentreError } from './cost-centre.util';

/** What the dialog created: the id of the Kostenstelle, or the plan that now holds its line. */
export interface CostCentreCreated {
  readonly id: Uuid | null;
  readonly plan: BudgetPlan | null;
}

/**
 * The dialog "Kostenstelle anlegen" of the Budget tab. It takes the parent, the key and the
 * name, and the side for a direct child of a budget with a Haushaltsplan. With `versionId`
 * it creates the Kostenstelle in that draft version together with its Ansatz.
 */
@Component({
  selector: 'app-cost-centre-create',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    CurrencyInputComponent,
    DialogComponent,
    InputComponent,
    SegmentedComponent,
    SelectFieldComponent,
  ],
  templateUrl: './cost-centre-create.component.html',
  styleUrl: './cost-centre-create.component.scss',
})
export class CostCentreCreateComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly planApi = inject(BudgetPlanApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = input(false);
  /** The budget that gets the Kostenstelle. */
  readonly top = input<BudgetTreeNode | null>(null);
  readonly parents = input<readonly SelectOption[]>([]);
  /** The parent the form starts with; '' is the budget. */
  readonly parent = input('');
  /** The draft version that gets the line, or `null` to create only the Kostenstelle. */
  readonly versionId = input<string | null>(null);
  readonly amountLabel = input('');
  readonly closed = output<void>();
  readonly created = output<CostCentreCreated>();

  readonly parentId = signal('');
  readonly key = signal('');
  readonly name = signal('');
  readonly side = signal<Side | null>(null);
  readonly amount = signal('0');
  readonly busy = signal(false);

  readonly parentOptions = computed<SelectOption[]>(() => [...this.parents()]);
  readonly sides = computed(() => [
    { value: 'income', label: this.i18n.translate('budget.plan.side.income') },
    { value: 'expense', label: this.i18n.translate('budget.plan.side.expense') },
  ]);
  /** A direct child of a budget with a Haushaltsplan needs a side. */
  readonly sided = computed(() => {
    const top = this.top();
    return !!top?.planEnabled && this.parentId() === top.id;
  });
  readonly valid = computed(
    () => !!this.key().trim() && !!this.name().trim() && !!this.parentId() && (!this.sided() || !!this.side()),
  );

  /** Each opening starts with an empty form under the given parent. */
  constructor() {
    effect(() => {
      if (!this.open()) return;
      this.parentId.set(this.parent() || (this.top()?.id ?? ''));
      this.key.set('');
      this.name.set('');
      this.side.set(null);
      this.amount.set('0');
    });
  }

  submit(event: Event): void {
    event.preventDefault();
    const top = this.top();
    const version = this.versionId();
    if (!top || !this.valid() || this.busy()) return;
    const body = {
      parentId: this.parentId() as Uuid,
      key: this.key().trim(),
      name: this.name().trim(),
      side: this.sided() ? this.side() : null,
    };
    this.busy.set(true);
    const done = (result: CostCentreCreated): void => {
      this.busy.set(false);
      this.toast.success(this.i18n.translate('budget.cc.toast.created'));
      this.created.emit(result);
    };
    const failed = (err: unknown): void => {
      this.busy.set(false);
      this.toast.error(this.i18n.translate(costCentreError(problemCode(err))));
    };
    if (version)
      this.planApi
        .createNode(version as Uuid, { ...body, amount: this.amount() || '0' })
        .subscribe({ next: (plan) => done({ id: null, plan }), error: failed });
    else
      this.api
        .createNode({ ...body, currency: top.currency })
        .subscribe({ next: (node) => done({ id: node.id, plan: null }), error: failed });
  }
}
