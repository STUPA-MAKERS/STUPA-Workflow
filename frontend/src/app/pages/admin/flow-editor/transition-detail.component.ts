import { ChangeDetectionStrategy, Component, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  IconComponent,
  InputComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import type { BudgetTreeNode } from '../../budget/budget-tree.api';
import {
  ACTION_TYPES,
  ASSIGN_BUDGET_ACTIONS,
  NOTIFY_RECIPIENT_KINDS,
  type ActionDef,
  type Guard,
  type NotifyRecipient,
  type TransitionDef,
} from '../admin.models';
import { CostCentrePickerComponent } from './cost-centre-picker.component';
import { GuardEditorComponent } from './guard-editor.component';
import { actionParamOf, recipientNeedsRef, recipientsOf } from './flow-guard.util';

/**
 * Guard and actions of the selected transition. They follow the transition settings in
 * the inspector: the guard builder, one card per action with its parameters, and
 * "Aktion hinzufügen" (choose the kind, then "Hinzufügen").
 */
@Component({
  selector: 'app-transition-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    InputComponent,
    SelectComponent,
    GuardEditorComponent,
    CostCentrePickerComponent,
  ],
  templateUrl: './transition-detail.component.html',
  styleUrl: './transition-detail.component.scss',
})
export class TransitionDetailComponent {
  private readonly i18n = inject(I18nService);

  readonly transition = input.required<TransitionDef>();
  readonly roleOptions = input.required<SelectOption[]>();
  readonly gremiumOptions = input.required<SelectOption[]>();
  readonly webhookOptions = input.required<SelectOption[]>();
  /** The cost-center tree for the cost-center pickers of the budget actions. */
  readonly budgetTree = input<BudgetTreeNode[]>([]);
  /** The target is a vote state that takes its gremium from the cost center. The
   *  cost-center actions are then not on offer (the backend refuses them there). */
  readonly targetBudgetVote = input<boolean>(false);

  readonly guardChange = output<Guard | null>();
  readonly actionAdd = output<string>();
  readonly actionRemove = output<number>();
  readonly actionParamChange = output<{ ai: number; key: string; value: string }>();
  readonly actionMapChange = output<{ ai: number; map: Record<string, string> }>();
  readonly recipientAdd = output<number>();
  readonly recipientRemove = output<{ ai: number; ri: number }>();
  readonly recipientKindChange = output<{ ai: number; ri: number; kind: string }>();
  readonly recipientRefChange = output<{ ai: number; ri: number; ref: string }>();

  /** The action kind chosen in "Aktion hinzufügen", until "Hinzufügen" adds it. */
  protected readonly pendingAction = signal('');

  /** Add the chosen action kind and clear the choice. */
  protected addPending(): void {
    const type = this.pendingAction();
    if (!type) return;
    this.actionAdd.emit(type);
    this.pendingAction.set('');
  }

  protected actionOptions(): SelectOption[] {
    const blocked: readonly string[] = this.targetBudgetVote() ? ASSIGN_BUDGET_ACTIONS : [];
    return ACTION_TYPES.filter((a) => !blocked.includes(a)).map((a) => ({
      value: a,
      label: this.i18n.translate(`admin.flow.actionType.${a}` as TranslationKey),
    }));
  }

  protected actionLabel(type: string): string {
    return this.i18n.translate(`admin.flow.actionType.${type}` as TranslationKey);
  }

  protected recipientKindOptions(): SelectOption[] {
    return NOTIFY_RECIPIENT_KINDS.map((k) => ({
      value: k,
      label: this.i18n.translate(`admin.flow.recipientKind.${k}` as TranslationKey),
    }));
  }

  /** The value → cost center rows of an `assignBudgetFromMap` action, in map order. */
  protected mapRows(act: ActionDef): { value: string; budgetId: string }[] {
    return Object.entries(mapOf(act)).map(([value, budgetId]) => ({ value, budgetId }));
  }

  /** A row with an empty value exists: add one more only after it got a value. */
  protected hasBlankMapRow(act: ActionDef): boolean {
    return '' in mapOf(act);
  }

  protected addMapRow(ai: number, act: ActionDef): void {
    if (this.hasBlankMapRow(act)) return;
    this.actionMapChange.emit({ ai, map: { ...mapOf(act), '': '' } });
  }

  protected removeMapRow(ai: number, act: ActionDef, index: number): void {
    const rows = this.mapRows(act).filter((_, i) => i !== index);
    this.actionMapChange.emit({ ai, map: fromRows(rows) });
  }

  protected setMapValue(ai: number, act: ActionDef, index: number, value: string): void {
    const rows = this.mapRows(act).map((r, i) => (i === index ? { ...r, value } : r));
    this.actionMapChange.emit({ ai, map: fromRows(rows) });
  }

  protected setMapBudget(ai: number, act: ActionDef, index: number, budgetId: string): void {
    const rows = this.mapRows(act).map((r, i) => (i === index ? { ...r, budgetId } : r));
    this.actionMapChange.emit({ ai, map: fromRows(rows) });
  }

  protected recipientsOf(act: ActionDef): NotifyRecipient[] {
    return recipientsOf(act);
  }

  protected actionParam(act: ActionDef, key: string): string {
    return actionParamOf(act, key);
  }

  protected recipientNeedsRef(kind: string): boolean {
    return recipientNeedsRef(kind);
  }
}

/** The `map` of an `assignBudgetFromMap` action; anything else reads as empty. */
function mapOf(act: ActionDef): Record<string, string> {
  const m = act['map'];
  return typeof m === 'object' && m !== null && !Array.isArray(m)
    ? (m as Record<string, string>)
    : {};
}

/** Rows back to a map. Two rows with the same value keep the later cost center. */
function fromRows(rows: readonly { value: string; budgetId: string }[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rows) out[r.value] = r.budgetId;
  return out;
}
