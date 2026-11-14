import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { SelectFieldComponent, type SelectOption } from '@stupa-makers/ui-kit';

import { TranslatePipe } from '@core/i18n/translate.pipe';

import { type BudgetYear, BudgetTreeApi } from '../budget-tree.api';
import { budgetYearLabel, defaultBudgetYear } from './budget-year-select.util';

const LAST_BUDGET = 'ap.budgetYear.lastBudget';

function readLast(): string {
  try {
    return localStorage.getItem(LAST_BUDGET) ?? '';
  } catch {
    return '';
  }
}

function writeLast(budgetId: string): void {
  try {
    localStorage.setItem(LAST_BUDGET, budgetId);
  } catch {
    /* The choice is a convenience, and a browser without storage works without it. */
  }
}

/**
 * The one field for a Haushalt and a Haushaltsjahr, which a form asks for before the
 * Kostenstelle (spec 000879).
 *
 * It loads the pairs that a new booking can take and starts with the current year. The
 * form holds the fiscal year; `picked` gives the pair, also for the first choice that
 * the field makes itself.
 *
 * ```html
 * <app-budget-year-select [fiscalYearId]="year()" (picked)="onPair($event)" />
 * ```
 */
@Component({
  selector: 'app-budget-year-select',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, SelectFieldComponent, TranslatePipe],
  templateUrl: './budget-year-select.component.html',
})
export class BudgetYearSelectComponent {
  private readonly api = inject(BudgetTreeApi);

  /** The fiscal year of the form, or ''. */
  readonly fiscalYearId = input('');
  /** The budget whose current year the field starts with, for a form with a Kostenstelle. */
  readonly preferBudgetId = input('');
  readonly required = input(true);

  readonly picked = output<BudgetYear>();

  protected readonly pairs = signal<readonly BudgetYear[] | null>(null);
  protected readonly options = computed<SelectOption[]>(() =>
    (this.pairs() ?? []).map((p) => ({ value: p.fiscalYearId, label: budgetYearLabel(p) })),
  );
  /** The pair of the form, or the pair the field starts with. */
  private readonly resolved = computed<BudgetYear | null>(() => {
    const pairs = this.pairs() ?? [];
    return (
      pairs.find((p) => p.fiscalYearId === this.fiscalYearId()) ??
      defaultBudgetYear(pairs, this.preferBudgetId(), readLast())
    );
  });
  private readonly told = signal('');

  constructor() {
    this.api.listBudgetYears().subscribe({
      next: (pairs) => this.pairs.set(pairs),
      error: () => this.pairs.set([]),
    });
    effect(() => {
      const pair = this.resolved();
      if (!pair || this.told() === pair.fiscalYearId) return;
      this.told.set(pair.fiscalYearId);
      this.picked.emit(pair);
    });
  }

  protected pick(fiscalYearId: string): void {
    const pair = (this.pairs() ?? []).find((p) => p.fiscalYearId === fiscalYearId);
    if (!pair) return;
    writeLast(pair.budgetId);
    this.told.set(pair.fiscalYearId);
    this.picked.emit(pair);
  }
}
