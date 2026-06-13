import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import type { Uuid } from '@core/api/models';
import type { BudgetTreeNode } from './budget-tree.api';
import { PALETTE } from './budget-year-tree.component';

/**
 * Wiederverwendbarer Kostenstellen-Baum-Picker (#applications-tree). Gleiche Optik
 * wie der Budget→Jahr-Baum (`app-budget-year-tree`): farbige Punkte an den
 * Wurzeln, gepunktete hellgrüne Verbindungslinien zu Unterknoten, kompaktes
 * Hervorheben der Auswahl. Rekursiv über die gesamte Hierarchie. Optionaler
 * „Alle"-Knoten (Wert ``''``) ganz oben.
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
  /** Voller Kostenstellen-Baum (Wurzeln mit ``children``). */
  readonly nodes = input<BudgetTreeNode[]>([]);
  readonly selectedId = input<string>('');
  /** Label des „Alle"-Knotens; leer = keiner. */
  readonly allLabel = input<string>('');
  readonly ariaLabel = input<string>('');
  readonly emptyLabel = input<string>('');

  /** Gewählte Kostenstelle (``''`` = Alle). */
  readonly picked = output<Uuid | ''>();

  private readonly rootIds = computed(() => this.nodes().map((n) => n.id));

  dotColor(node: BudgetTreeNode): string {
    if (node.color) return node.color;
    const idx = this.rootIds().indexOf(node.id);
    return PALETTE[((idx % PALETTE.length) + PALETTE.length) % PALETTE.length];
  }
}
