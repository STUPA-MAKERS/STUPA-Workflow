import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import type { Uuid } from '@core/api/models';
import type { BudgetTreeNode } from './budget-tree.api';
import { nodeColors, paletteColor } from './budget-color.util';

/**
 * Reusable cost-centre tree picker. It looks like the budget-to-year tree
 * (`app-budget-year-tree`): colour swatches at the roots and at every node with its own
 * colour, dotted connector lines in the colour of the branch, and the selection surface
 * of the design system. It recurses over the whole hierarchy. An optional "all" node with
 * the value ``''`` sits at the top.
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
  /** Full cost-center tree: the roots with their ``children``. */
  readonly nodes = input<BudgetTreeNode[]>([]);
  readonly selectedId = input<string>('');
  /** Label of the "all" node. An empty string hides that node. */
  readonly allLabel = input<string>('');
  readonly ariaLabel = input<string>('');
  readonly emptyLabel = input<string>('');

  /** Selected cost center. The value ``''`` means all. */
  readonly picked = output<Uuid | ''>();

  /** Display colour per node, by the same rule as the budget page (`nodeColors`). */
  private readonly colors = computed(() => nodeColors(this.nodes()));

  /** Colour of a root: the set colour, else a stable palette colour by position. A node
   *  that is not in the tree gets its own colour, else the last palette colour. */
  dotColor(node: BudgetTreeNode): string {
    return this.colors().get(node.id) ?? (node.color?.trim() || paletteColor(-1));
  }

  /** The own colour of a node below the roots, or `null`. Only a node with its own colour
   *  (for example a faculty) gets a swatch and passes its colour to its lines (O19). */
  ownColor(node: BudgetTreeNode): string | null {
    return node.color?.trim() || null;
  }
}
