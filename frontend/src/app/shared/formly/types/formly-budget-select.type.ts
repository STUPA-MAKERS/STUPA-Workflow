import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CostCentreSelectComponent } from '../../../pages/budget/cost-centre-select/cost-centre-select.component';
import type { BudgetTreeNode } from '../../../pages/budget/budget-tree.api';

/**
 * Formly field type `budget_select`: the cost centre of an application, in the apply
 * wizard, the edit form of the detail and the status page.
 *
 * It renders the cost-centre picker of the budget forms (`app-cost-centre-select`): the
 * search and the tree of cost centres with their colour swatches and keys, a popover on
 * a wide screen and the bottom sheet on a phone. `props.nodes` is the tree that the
 * mapper builds from the options of the server (`budgetOptionTree`). The hint and the
 * error text show below the field, as with `app-select`.
 */
@Component({
  selector: 'app-formly-budget-select',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CostCentreSelectComponent, TranslatePipe],
  template: `
    <div class="fbs">
      <app-cost-centre-select
        [id]="controlId"
        [nodes]="nodes"
        [value]="value"
        [label]="props.label ?? ''"
        [required]="!!props.required"
        [invalid]="showError"
        [placeholder]="props.placeholder || ('formly.select.placeholder' | t)"
        [emptyLabel]="'expenses.field.noCostCentres' | t"
        (picked)="pick($event)"
      />
      @if (showError) {
        <p class="fbs__msg fbs__msg--error" role="alert">
          {{ props['errorText'] ?? ('formly.select.error' | t) }}
        </p>
      } @else if (props.description) {
        <p class="fbs__msg fbs__msg--hint">{{ props.description }}</p>
      }
    </div>
  `,
  styles: [
    `
      .fbs {
        display: flex;
        flex-direction: column;
        gap: 6px;
        min-width: 0;
      }
      .fbs__msg {
        margin: 0;
        padding-inline: var(--space-4);
        font-size: var(--fs-small);
        line-height: var(--lh-small);
      }
      .fbs__msg--hint {
        color: var(--color-text-muted);
      }
      .fbs__msg--error {
        color: var(--color-danger);
      }
    `,
  ],
})
export class FormlyBudgetSelectType extends FieldType<FieldTypeConfig> {
  get controlId(): string {
    return `${this.field.id ?? 'app-budget-select'}`;
  }

  get nodes(): readonly BudgetTreeNode[] {
    return (this.props['nodes'] as BudgetTreeNode[] | undefined) ?? [];
  }

  get value(): string {
    const v: unknown = this.formControl.value;
    return typeof v === 'string' ? v : '';
  }

  pick(id: string): void {
    this.formControl.setValue(id);
    this.formControl.markAsDirty();
    this.formControl.markAsTouched();
  }
}
