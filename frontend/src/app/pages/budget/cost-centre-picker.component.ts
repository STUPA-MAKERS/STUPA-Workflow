import {
  ChangeDetectionStrategy,
  Component,
  booleanAttribute,
  computed,
  input,
  output,
  signal,
} from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';
import { simplifyPathKey } from '@shared/budget-path';
import { nodeColors } from './budget-color.util';
import type { BudgetTreeNode } from './budget-tree.api';
import { CostCentreTreeComponent } from './cost-centre-tree.component';

let nextId = 0;

/** Find a node by id anywhere in the tree. */
export function findCostCentre(
  nodes: readonly BudgetTreeNode[],
  id: string,
): BudgetTreeNode | null {
  for (const n of nodes) {
    if (n.id === id) return n;
    const hit = findCostCentre(n.children ?? [], id);
    if (hit) return hit;
  }
  return null;
}

/**
 * How the field names the pick: `pathName` "VSM-8 · Kind" (the flow editor), `name` the
 * name only (a booking), `namePath` the name with the short path after it in mono (a
 * transfer, where both ends must be told apart).
 */
export type CostCentrePickerText = 'pathName' | 'name' | 'namePath';

/**
 * A field that picks a cost center from the tree. The whole field is the button; the
 * tree of the applications page opens below it. The field shows the pick by `text`, never
 * its id. An id that the tree does not hold shows as `unknownLabel`. With an `allLabel`
 * the tree offers an extra top entry with the value `''` (for example "no limit").
 *
 * - `swatch` puts the display colour of the pick (the budget page's colour) before it.
 * - `required` marks the label with the red asterisk of the kit fields.
 * - `inGrid`: the field is one cell of a grid (`.ff__grid`). The tree then opens below
 *   the whole row: the host takes no box of its own, the tree spans every column, and
 *   the grid needs `grid-auto-flow: row dense`, so the cells after the field stay in its
 *   row.
 *
 * The tree takes `--ccp-tree-bg` (default: the sunken surface), so a form on a raised
 * surface or in a sheet steps it up.
 */
@Component({
  selector: 'app-cost-centre-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, CostCentreTreeComponent],
  templateUrl: './cost-centre-picker.component.html',
  styleUrl: './cost-centre-picker.component.scss',
  host: { '[class.ccp--grid]': 'inGrid()' },
})
export class CostCentrePickerComponent {
  readonly nodes = input<BudgetTreeNode[]>([]);
  readonly value = input<string>('');
  readonly label = input<string>('');
  readonly placeholder = input<string>('');
  readonly allLabel = input<string>('');
  readonly unknownLabel = input<string>('');
  readonly emptyLabel = input<string>('');
  readonly text = input<CostCentrePickerText>('pathName');
  readonly swatch = input(false, { transform: booleanAttribute });
  readonly required = input(false, { transform: booleanAttribute });
  readonly inGrid = input(false, { transform: booleanAttribute });
  readonly picked = output<string>();

  protected readonly open = signal(false);
  protected readonly uid = `ccp-${nextId++}`;

  private readonly node = computed(() => {
    const id = this.value();
    return id ? findCostCentre(this.nodes(), id) : null;
  });

  /** The text of the field, the unknown label, or nothing. */
  protected readonly display = computed<string>(() => {
    if (!this.value()) return '';
    const node = this.node();
    if (!node) return this.unknownLabel();
    return this.text() === 'pathName' ? `${node.pathKey} · ${node.name}` : node.name;
  });

  /** The short path after the name (`namePath`). */
  protected readonly path = computed(() => {
    const node = this.node();
    return node && this.text() === 'namePath' ? simplifyPathKey(node.pathKey) : '';
  });

  /** The display colour of the pick, with `swatch`. */
  protected readonly color = computed<string | null>(() => {
    const node = this.node();
    if (!this.swatch() || !node) return null;
    return nodeColors(this.nodes()).get(node.id) ?? null;
  });

  protected toggle(): void {
    this.open.update((o) => !o);
  }

  protected pick(id: string): void {
    this.picked.emit(id);
    this.open.set(false);
  }
}
