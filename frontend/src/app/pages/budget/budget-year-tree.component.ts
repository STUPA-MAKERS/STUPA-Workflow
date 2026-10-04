import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import type { BudgetTreeNode, FiscalYear } from './budget-tree.api';
import { paletteColor } from './budget-color.util';

/** Selection in the left tree: a top budget and a fiscal year. */
export interface BudgetYearSelection {
  budgetId: Uuid;
  fiscalYearId: Uuid;
}

/**
 * Left navigation tree from budget to fiscal year. It has two levels. Each top
 * budget shows its fiscal years below it. A click on a year selects the budget and
 * the year. The tree highlights the current selection and draws dotted connector lines
 * in the colour of the budget. It shows "…" when a budget has more than 5 fiscal years.
 * The admin cost-centre page uses it.
 */
@Component({
  selector: 'app-budget-year-tree',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  templateUrl: './budget-year-tree.component.html',
  styleUrl: './budget-year-tree.component.scss',
})
export class BudgetYearTreeComponent {
  readonly tops = input<BudgetTreeNode[]>([]);
  /** Fiscal years per top-budget id. */
  readonly fiscalYears = input<Record<Uuid, FiscalYear[]>>({});
  readonly selectedBudgetId = input<string>('');
  readonly selectedFyId = input<string>('');

  readonly budgetPicked = output<Uuid>();
  readonly yearPicked = output<BudgetYearSelection>();

  private readonly MAX = 5;

  readonly palette = computed(() => this.tops().map((t) => t.id));

  years(budgetId: Uuid): FiscalYear[] {
    return this.fiscalYears()[budgetId] ?? [];
  }
  shownYears(budgetId: Uuid): FiscalYear[] {
    return this.years(budgetId).slice(0, this.MAX);
  }
  hiddenCount(budgetId: Uuid): number {
    return Math.max(0, this.years(budgetId).length - this.MAX);
  }
  moreTitle(budgetId: Uuid): string {
    return this.years(budgetId)
      .slice(this.MAX)
      .map((y) => y.display)
      .join(', ');
  }

  /** Colour of a node. It uses the set colour, else a stable palette colour by index. */
  dotColor(node: BudgetTreeNode): string {
    if (node.color) return node.color;
    return paletteColor(this.palette().indexOf(node.id));
  }

  pickBudget(b: BudgetTreeNode): void {
    this.budgetPicked.emit(b.id);
  }
  pickYear(budgetId: Uuid, fiscalYearId: Uuid): void {
    this.yearPicked.emit({ budgetId, fiscalYearId });
  }
}
