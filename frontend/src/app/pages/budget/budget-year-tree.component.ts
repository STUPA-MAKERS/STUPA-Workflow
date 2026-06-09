import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import type { BudgetTreeNode, FiscalYear } from './budget-tree.api';

/** Auswahl im linken Baum: Budget (Top) + Haushaltsjahr. */
export interface BudgetYearSelection {
  budgetId: Uuid;
  fiscalYearId: Uuid;
}

/**
 * Linker Navigations-Baum **Budget → Haushaltsjahr** (#budget-redesign). Zwei
 * Ebenen: jedes Top-Budget, darunter seine HHJ (klickbar → wählt Budget+Jahr).
 * Aktuelles ist hervorgehoben; gepunktete, hellgrüne, kompakte Linien. Zeigt „…"
 * wenn ein Budget mehr als 5 HHJ hat. Wiederverwendbar (Dashboard + Admin).
 */
@Component({
  selector: 'app-budget-year-tree',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  template: `
    <nav class="byt" [attr.aria-label]="'budget.tree.nav' | t">
      @for (b of tops(); track b.id) {
        <div class="byt__budget" [class.byt__budget--sel]="b.id === selectedBudgetId()">
          <button type="button" class="byt__node byt__node--top" (click)="pickBudget(b)">
            <span class="byt__dot" [style.background]="dotColor(b)"></span>
            <span class="byt__label">{{ b.name }}</span>
          </button>
          <ul class="byt__years">
            @for (fy of shownYears(b.id); track fy.id) {
              <li>
                <button
                  type="button"
                  class="byt__node byt__node--year"
                  [class.byt__node--active]="b.id === selectedBudgetId() && fy.id === selectedFyId()"
                  (click)="pickYear(b.id, fy.id)"
                >
                  {{ fy.label }}
                </button>
              </li>
            }
            @if (hiddenCount(b.id) > 0) {
              <li class="byt__more" [title]="moreTitle(b.id)">…</li>
            }
            @if (!years(b.id).length) {
              <li class="byt__empty">{{ 'budget.tree.noYears' | t }}</li>
            }
          </ul>
        </div>
      }
      @if (!tops().length) {
        <p class="byt__empty">{{ 'budget.tree.empty' | t }}</p>
      }
    </nav>
  `,
  styles: [
    `
      .byt {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        font-size: var(--fs-sm);
      }
      .byt__node {
        display: inline-flex;
        align-items: center;
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
      .byt__node:hover {
        background: var(--color-surface-sunken);
      }
      .byt__node--top {
        font-weight: var(--fw-semibold);
      }
      .byt__dot {
        width: 9px;
        height: 9px;
        border-radius: 999px;
        flex: 0 0 auto;
      }
      .byt__label {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      /* Gepunktete, hellgrüne, kompakte Verbindungslinien zu den Jahren. */
      .byt__years {
        list-style: none;
        margin: 0 0 var(--space-1) 0;
        padding: 0 0 0 calc(var(--space-2) + 4px);
        border-left: 1px dotted var(--color-success, #5fb37a);
        margin-left: calc(var(--space-2) + 4px);
      }
      .byt__node--year {
        color: var(--color-text-muted);
        font-size: var(--fs-xs);
        position: relative;
      }
      .byt__node--year::before {
        content: '';
        position: absolute;
        left: calc(-1 * (var(--space-2) + 4px));
        top: 50%;
        width: var(--space-2);
        border-top: 1px dotted var(--color-success, #5fb37a);
      }
      .byt__node--active {
        background: color-mix(in srgb, var(--color-success, #5fb37a) 22%, transparent);
        color: var(--color-text);
        font-weight: var(--fw-medium);
      }
      .byt__more,
      .byt__empty {
        color: var(--color-text-muted);
        font-size: var(--fs-xs);
        padding: 0 var(--space-2);
        margin-left: var(--space-2);
      }
    `,
  ],
})
export class BudgetYearTreeComponent {
  readonly tops = input<BudgetTreeNode[]>([]);
  /** HHJ je Top-Budget-Id. */
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
      .map((y) => y.label)
      .join(', ');
  }

  /** Knoten-Farbe (gesetzte Farbe oder stabile Palette nach Index). */
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

/** Fallback-Palette für Knoten ohne gesetzte Farbe (stabil nach Index). */
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
