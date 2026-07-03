import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import type { BudgetTreeNode, FiscalYear } from './budget-tree.api';

/** Selection in the left tree: budget (top) + fiscal year. */
export interface BudgetYearSelection {
  budgetId: Uuid;
  fiscalYearId: Uuid;
}

/**
 * Left navigation tree **budget → fiscal year**. Two levels: each top budget,
 * below it its fiscal years (clickable → selects budget + year). The current one
 * is highlighted; dotted, light-green, compact lines. Shows "…" when a budget has
 * more than 5 fiscal years. Reusable (dashboard + admin).
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

  /** Node colour (set colour, or a stable palette by index). */
  dotColor(node: BudgetTreeNode): string {
    if (node.color) return node.color;
    const idx = this.palette().indexOf(node.id);
    return PALETTE[((idx % PALETTE.length) + PALETTE.length) % PALETTE.length];
  }

  pickBudget(b: BudgetTreeNode): void {
    this.budgetPicked.emit(b.id);
  }
  pickYear(budgetId: Uuid, fiscalYearId: Uuid): void {
    this.yearPicked.emit({ budgetId, fiscalYearId });
  }
}

/** Fallback palette for nodes without a set colour (stable by index). */
export const PALETTE: readonly string[] = [
  '#5fb37a',
  '#4a90d9',
  '#e0a458',
  '#c45c8a',
  '#8a6fc4',
  '#52a8a8',
  '#d97b5c',
  '#7aa84a',
];
