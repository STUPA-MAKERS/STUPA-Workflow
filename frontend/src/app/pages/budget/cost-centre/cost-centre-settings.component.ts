import { ChangeDetectionStrategy, Component, computed, inject, input, linkedSignal, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Observable } from 'rxjs';
import {
  InputComponent,
  SelectFieldComponent,
  type SelectOption,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { problemCode } from '@core/api/problem';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { BudgetTreeApi, type BudgetNodeUpdate, type BudgetTreeNode } from '../budget-tree.api';
import { BudgetPlanApi, type Side } from '../plan/budget-plan.api';
import { ColourFieldComponent } from './colour-field.component';
import { costCentreError, keyProblem, NAME_MAX } from './cost-centre.util';

/**
 * The settings of one Kostenstelle in the Budget tab: key, name, side, colour, the switch
 * "Aktiv" and its two Gremien. Each field saves when the person leaves it; `saved` then
 * tells the page to read the tree again and a toast says that the change is saved. A failed
 * save shows its reason and the field takes the saved value again.
 */
@Component({
  selector: 'app-cost-centre-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ColourFieldComponent,
    InputComponent,
    SelectFieldComponent,
    SwitchComponent,
  ],
  templateUrl: './cost-centre-settings.component.html',
  styleUrl: './cost-centre-settings.component.scss',
})
export class CostCentreSettingsComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly planApi = inject(BudgetPlanApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly node = input.required<BudgetTreeNode>();
  /** The Kostenstelle is a direct child of a budget with a Haushaltsplan, so it has a side. */
  readonly sided = input(false);
  readonly gremiumOptions = input<readonly SelectOption[]>([]);
  readonly saved = output<void>();

  readonly key = linkedSignal(() => this.node().key);
  readonly name = linkedSignal(() => this.node().name);
  readonly colour = linkedSignal(() => this.node().color?.trim() ?? '');
  readonly side = linkedSignal<Side | null>(() => this.node().side ?? null);
  readonly gremien = computed<SelectOption[]>(() => [...this.gremiumOptions()]);
  /** The error under the key: only letters and digits, at most 64 characters. */
  readonly keyError = computed(() =>
    keyProblem(this.key().trim()) ? this.i18n.translate('budget.cc.error.keyInvalid') : '',
  );
  readonly nameError = computed(() =>
    this.name().trim().length > NAME_MAX ? this.i18n.translate('budget.cc.error.nameLong') : '',
  );
  readonly sides = computed<SelectOption[]>(() => [
    { value: 'income', label: this.i18n.translate('budget.plan.side.income') },
    { value: 'expense', label: this.i18n.translate('budget.plan.side.expense') },
  ]);

  /**
   * Save the key or the name when the person leaves the field. An empty text is not saved:
   * the field shows the saved text again. A text with an error stays for the correction.
   *
   * The saved text comes back one turn later, because a field that is emptied and left in
   * the same turn has not rendered the empty text yet, and a model that goes from the saved
   * text to the saved text writes nothing into the field.
   */
  saveText(field: 'key' | 'name'): void {
    const value = this[field]().trim();
    const error = field === 'key' ? this.keyError() : this.nameError();
    if (!value) setTimeout(() => this[field].set(this.node()[field]));
    else if (!error && value !== this.node()[field]) this.save({ [field]: value });
  }

  saveColour(colour: string): void {
    if (colour !== (this.node().color?.trim() ?? '')) this.save({ color: colour });
  }

  saveGremium(field: 'viewGremiumId' | 'decisionGremiumId', value: string | null): void {
    if ((value || null) !== (this.node()[field] ?? null)) this.save({ [field]: value || null });
  }

  /** Save the side. A refused change shows the saved side again. */
  saveSide(side: string | null): void {
    if (!side || side === this.node().side) return;
    this.side.set(side as Side);
    this.run(this.planApi.setSide(this.node().id, side as Side));
  }

  save(patch: BudgetNodeUpdate): void {
    this.run(this.api.updateNode(this.node().id, patch));
  }

  private run(request: Observable<unknown>): void {
    request.subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.saved'));
        this.saved.emit();
      },
      error: (err: unknown) => {
        this.toast.error(this.i18n.translate(costCentreError(problemCode(err))));
        this.key.set(this.node().key);
        this.name.set(this.node().name);
        this.colour.set(this.node().color?.trim() ?? '');
        this.side.set(this.node().side ?? null);
        this.saved.emit();
      },
    });
  }
}
