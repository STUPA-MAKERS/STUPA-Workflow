import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  output,
  signal,
} from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';
import type { BudgetTreeNode } from '../../budget/budget-tree.api';
import { CostCentreTreeComponent } from '../../budget/cost-centre-tree.component';

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
 * A field that picks a cost center from the tree. The whole field is the button; the
 * tree of the applications page opens below it. The field shows the path key and the
 * name of the pick, never its id. An id that the tree does not hold shows as
 * `unknownLabel`. With an `allLabel` the tree offers an extra top entry with the value
 * `''` (for example "no limit").
 */
@Component({
  selector: 'app-cost-centre-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, CostCentreTreeComponent],
  templateUrl: './cost-centre-picker.component.html',
  styleUrl: './cost-centre-picker.component.scss',
})
export class CostCentrePickerComponent {
  readonly nodes = input<BudgetTreeNode[]>([]);
  readonly value = input<string>('');
  readonly label = input<string>('');
  readonly placeholder = input<string>('');
  readonly allLabel = input<string>('');
  readonly unknownLabel = input<string>('');
  readonly emptyLabel = input<string>('');
  readonly picked = output<string>();

  protected readonly open = signal(false);
  protected readonly uid = `ccp-${nextId++}`;

  /** The text of the field: "path key · name", the unknown label, or nothing. */
  protected readonly display = computed<string>(() => {
    const id = this.value();
    if (!id) return '';
    const node = findCostCentre(this.nodes(), id);
    return node ? `${node.pathKey} · ${node.name}` : this.unknownLabel();
  });

  protected toggle(): void {
    this.open.update((o) => !o);
  }

  protected pick(id: string): void {
    this.picked.emit(id);
    this.open.set(false);
  }
}
