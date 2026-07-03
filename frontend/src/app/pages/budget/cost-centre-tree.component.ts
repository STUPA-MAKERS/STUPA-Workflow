import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import type { Uuid } from '@core/api/models';
import type { BudgetTreeNode } from './budget-tree.api';
import { PALETTE } from './budget-year-tree.component';

/**
 * Reusable cost-centre tree picker. Same look as the budget→year tree
 * (`app-budget-year-tree`): coloured dots at the roots, dotted light-green
 * connector lines to sub-nodes, compact selection highlight. Recursive over the
 * whole hierarchy. Optional "all" node (value ``''``) at the top.
 */
@Component({
  selector: 'app-cost-centre-tree',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet],
  templateUrl: './cost-centre-tree.component.html',
  styleUrl: './cost-centre-tree.component.scss',
})
export class CostCentreTreeComponent {
  /** Full cost-centre tree (roots with ``children``). */
  readonly nodes = input<BudgetTreeNode[]>([]);
  readonly selectedId = input<string>('');
  /** Label of the "all" node; empty = none. */
  readonly allLabel = input<string>('');
  readonly ariaLabel = input<string>('');
  readonly emptyLabel = input<string>('');

  /** Selected cost centre (``''`` = all). */
  readonly picked = output<Uuid | ''>();

  private readonly rootIds = computed(() => this.nodes().map((n) => n.id));

  dotColor(node: BudgetTreeNode): string {
    if (node.color) return node.color;
    const idx = this.rootIds().indexOf(node.id);
    return PALETTE[((idx % PALETTE.length) + PALETTE.length) % PALETTE.length];
  }
}
