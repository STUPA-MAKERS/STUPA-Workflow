import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DialogComponent,
  InputComponent,
  SelectFieldComponent,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import { problemCode } from '@core/api/problem';
import { closeOnBack } from '@shared/util/close-on-back';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { BudgetTreeApi, type BudgetTreeNode } from '../budget-tree.api';
import { BudgetPlanApi, type BudgetPlan, type Side } from '../plan/budget-plan.api';
import { amountProblem } from '../plan/budget-plan.util';
import { CostCentreSelectComponent } from '../cost-centre-select/cost-centre-select.component';
import { costCentreError, createKey, keyProblem, NAME_MAX } from './cost-centre.util';

/** What the dialog created: the id of the Kostenstelle, or the plan that now holds its line. */
export interface CostCentreCreated {
  readonly id: Uuid | null;
  readonly plan: BudgetPlan | null;
}

/**
 * The dialog "Kostenstelle anlegen" of the Budget tab. It takes the parent, the key and the
 * name. With `versionId` it creates the Kostenstelle in that draft version together with its
 * Ansatz, and a Titel then also takes its side, because the plan line of a Titel holds it.
 */
@Component({
  selector: 'app-cost-centre-create',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    CostCentreSelectComponent,
    CurrencyInputComponent,
    DialogComponent,
    InputComponent,
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
  /** The budget with the Kostenstellen that can be the parent, as a forest for the picker. */
  readonly parentNodes = input<readonly BudgetTreeNode[]>([]);
  /** The parent the form starts with; '' is the budget. */
  readonly parent = input('');
  /** The draft version that gets the line, or `null` to create only the Kostenstelle. */
  readonly versionId = input<string | null>(null);
  readonly amountLabel = input('');
  /**
   * The Ansatz that the first child of a parent takes over, by the id of the parent. The
   * amount field starts with it, so the person sees that the Ansatz moves to the child.
   */
  readonly firstChildAmounts = input<ReadonlyMap<string, string>>(new Map());
  readonly closed = output<void>();
  readonly created = output<CostCentreCreated>();

  readonly parentId = signal('');
  readonly key = signal('');
  readonly name = signal('');
  readonly side = signal<Side | null>(null);
  readonly amount = signal('0');
  /** The text of the amount field is not an amount. */
  readonly amountInvalid = signal(false);
  readonly busy = signal(false);
  private readonly amountField = viewChild(CurrencyInputComponent);

  readonly sides = computed<SelectOption[]>(() => [
    { value: 'income', label: this.i18n.translate('budget.plan.side.income') },
    { value: 'expense', label: this.i18n.translate('budget.plan.side.expense') },
  ]);
  /** The new node is a Titel: it goes directly below the Haushalt. */
  readonly titled = computed(() => this.parentId() === this.top()?.id);
  readonly titleKey = computed(() => createKey(this.parentId(), this.top()));
  /** A Titel that is created in a draft needs the side of its line. */
  readonly sided = computed(() => !!this.versionId() && this.titled());
  /** The error under the key: only letters and digits, at most 64 characters. */
  readonly keyError = computed(() =>
    keyProblem(this.key().trim()) ? this.i18n.translate('budget.cc.error.keyInvalid') : '',
  );
  readonly nameError = computed(() =>
    this.name().trim().length > NAME_MAX ? this.i18n.translate('budget.cc.error.nameLong') : '',
  );
  readonly valid = computed(
    () =>
      !!this.key().trim() &&
      !this.keyError() &&
      !!this.name().trim() &&
      !this.nameError() &&
      !!this.parentId() &&
      (!this.sided() || !!this.side()) &&
      !this.amountInvalid() &&
      !this.amountError(),
  );
  /** The error under the Ansatz: an Ansatz is not negative and not above the largest amount. */
  readonly amountError = computed(() => {
    const problem = amountProblem(this.amount() || '0');
    if (!problem) return '';
    return this.i18n.translate(
      problem === 'negative' ? 'budget.plan.error.amountNegative' : 'budget.plan.error.amountTooLarge',
    );
  });

  /** Each opening starts with an empty form under the given parent. */
  constructor() {
    closeOnBack(this.open, () => this.closed.emit());
    effect(() => {
      if (!this.open()) return;
      untracked(() => {
        this.key.set('');
        this.name.set('');
        this.side.set(null);
        this.pickParent(this.parent() || (this.top()?.id ?? ''));
      });
    });
  }

  /** Choose the parent. The amount starts with the Ansatz that the first child takes over. */
  pickParent(id: string): void {
    this.parentId.set(id);
    this.amount.set(this.firstChildAmounts().get(id) ?? '0');
    this.amountInvalid.set(false);
  }

  /** Keep the typed amount. Text that is no amount gives an empty value and blocks the button. */
  setAmount(value: string | null): void {
    this.amount.set(value ?? '');
    this.amountInvalid.set(!!this.amountField()?.validate());
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
    };
    this.busy.set(true);
    const done = (result: CostCentreCreated): void => {
      this.busy.set(false);
      this.toast.success(this.i18n.translate(this.titled() ? 'budget.cc.toast.createdTitle' : 'budget.cc.toast.created'));
      this.created.emit(result);
    };
    const failed = (err: unknown): void => {
      this.busy.set(false);
      this.toast.error(this.i18n.translate(costCentreError(problemCode(err))));
    };
    if (version)
      this.planApi
        .createNode(version as Uuid, { ...body, side: this.sided() ? this.side() : null, amount: this.amount() || '0' })
        .subscribe({ next: (plan) => done({ id: null, plan }), error: failed });
    else
      this.api
        .createNode({ ...body, currency: top.currency })
        .subscribe({ next: (node) => done({ id: node.id, plan: null }), error: failed });
  }
}
