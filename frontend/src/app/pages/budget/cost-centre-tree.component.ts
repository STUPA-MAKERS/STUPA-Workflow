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
  template: `
    <nav class="cct" [attr.aria-label]="ariaLabel()">
      @if (allLabel(); as label) {
        <button
          type="button"
          class="cct__node cct__node--top cct__node--all"
          [class.cct__node--active]="!selectedId()"
          (click)="picked.emit('')"
        >{{ label }}</button>
      }
      <ng-container
        *ngTemplateOutlet="branch; context: { $implicit: nodes(), depth: 0 }"
      ></ng-container>
      @if (!nodes().length && !allLabel()) {
        <p class="cct__empty">{{ emptyLabel() }}</p>
      }
    </nav>

    <ng-template #branch let-list let-depth="depth">
      @for (n of list; track n.id) {
        <div class="cct__branch">
          <button
            type="button"
            class="cct__node"
            [class.cct__node--top]="depth === 0"
            [class.cct__node--child]="depth > 0"
            [class.cct__node--active]="selectedId() === n.id"
            (click)="picked.emit(n.id)"
          >
            @if (depth === 0) {
              <span class="cct__dot" [style.background]="dotColor(n)"></span>
            }
            <span class="cct__key">{{ n.key }}</span>
            <span class="cct__label">{{ n.name }}</span>
          </button>
          @if (n.children?.length) {
            <div class="cct__children">
              <ng-container
                *ngTemplateOutlet="branch; context: { $implicit: n.children, depth: depth + 1 }"
              ></ng-container>
            </div>
          }
        </div>
      }
    </ng-template>
  `,
  styles: [
    `
      .cct {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        font-size: var(--fs-sm);
      }
      .cct__node {
        display: inline-flex;
        align-items: baseline;
        gap: var(--space-2);
        width: 100%;
        text-align: start;
        background: transparent;
        border: 0;
        padding: 2px var(--space-2);
        border-radius: var(--radius-sm);
        color: var(--color-text);
        font: inherit;
        cursor: pointer;
      }
      .cct__node:hover {
        background: var(--color-surface-sunken);
      }
      .cct__node--top {
        font-weight: var(--fw-semibold);
      }
      .cct__node--child {
        color: var(--color-text-muted);
        font-size: var(--fs-xs);
      }
      .cct__dot {
        width: 9px;
        height: 9px;
        border-radius: 999px;
        flex: 0 0 auto;
        align-self: center;
      }
      .cct__key {
        font-variant-numeric: tabular-nums;
        color: var(--color-text-muted);
        flex: 0 0 auto;
      }
      .cct__node--active .cct__key {
        color: inherit;
      }
      .cct__label {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      /* Gepunktete, hellgrüne Verbindungslinien (echter Baum: letzte Zeile ohne
         durchlaufende Linie nach unten). */
      .cct__children {
        padding-left: calc(var(--space-3) + 4px);
      }
      .cct__children > .cct__branch {
        position: relative;
      }
      /* Senkrechte Linie: durchgehend, bei der letzten Verzweigung nur bis zum
         Querstrich (kein Stray-Down-Line). */
      .cct__children > .cct__branch::before {
        content: '';
        position: absolute;
        left: calc(-1 * (var(--space-2) + 1px));
        top: 0;
        bottom: 0;
        border-left: 1px dotted var(--color-success, #5fb37a);
      }
      .cct__children > .cct__branch:last-child::before {
        bottom: auto;
        height: 0.8em;
      }
      /* Querstrich zum Knoten. */
      .cct__children > .cct__branch::after {
        content: '';
        position: absolute;
        left: calc(-1 * (var(--space-2) + 1px));
        top: 0.8em;
        width: var(--space-2);
        border-top: 1px dotted var(--color-success, #5fb37a);
      }
      .cct__node--active {
        background: color-mix(in srgb, var(--color-success, #5fb37a) 22%, transparent);
        color: var(--color-text);
        font-weight: var(--fw-medium);
      }
      .cct__empty {
        color: var(--color-text-muted);
        font-size: var(--fs-xs);
        padding: 0 var(--space-2);
      }
    `,
  ],
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
