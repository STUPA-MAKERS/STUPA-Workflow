import { computed, inject, signal } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService, type SelectOption } from '@stupa-makers/ui-kit';
import type { Uuid } from '@core/api/models';
import {
  BudgetTreeApi,
  type Expense,
  type StatementLine,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';
import { formatEur } from '../budget/expense-display.util';
import { fintsErrorKey } from './konten.util';
import type { KontenLinesState } from './konten-lines.state';

/**
 * Per-row reconcile actions. A user can import a line as a new booking, link it to an
 * existing unallocated booking with the typeahead, or unlink it again.
 */
export class KontenReconcileState {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  private readonly costOptionsSig = signal<SelectOption[]>([]);
  readonly costCentreOptions = computed<SelectOption[]>(() => this.costOptionsSig());
  readonly fiscalYearOptions = signal<SelectOption[]>([]);
  /** Node id to top-level budget id. The fiscal years live at the top. */
  private idToTopId = signal<Map<string, string>>(new Map());

  readonly importLine = signal<StatementLine | null>(null);
  readonly impBudgetId = signal('');
  readonly impFiscalYearId = signal('');
  readonly impDescription = signal('');
  readonly booking = signal(false);

  readonly linkLine = signal<StatementLine | null>(null);
  readonly linkQuery = signal('');
  readonly linkCandidates = signal<Expense[]>([]);
  readonly linkSelected = signal<Expense | null>(null);
  readonly linkLoading = signal(false);
  private linkTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly lines: KontenLinesState) {
    this.api.tree().subscribe({
      next: (tree) => {
        this.costOptionsSig.set(flattenBudgetOptions(tree));
        const map = new Map<string, string>();
        const walk = (node: { id: string; children: unknown[] }, topId: string): void => {
          map.set(node.id, topId);
          for (const c of node.children) walk(c as { id: string; children: unknown[] }, topId);
        };
        for (const top of tree) walk(top, top.id);
        this.idToTopId.set(map);
      },
      error: () => this.costOptionsSig.set([]),
    });
  }

  candidateLabel(e: Expense): string {
    const parts = [e.description, formatEur(Math.abs(Number(e.amount)), this.i18n.locale())];
    if (e.correspondent) parts.push(e.correspondent);
    if (e.pathKey) parts.push(e.pathKey);
    return parts.join(' · ');
  }

  openImport(line: StatementLine): void {
    this.importLine.set(line);
    this.impBudgetId.set(line.suggestedBudgetId ?? '');
    this.impDescription.set(line.purpose ?? '');
    this.impFiscalYearId.set('');
    if (line.suggestedBudgetId) this.loadFiscalYears(line.suggestedBudgetId);
    else this.fiscalYearOptions.set([]);
  }

  onPickImportBudget(id: string): void {
    this.impBudgetId.set(id);
    this.loadFiscalYears(id);
  }

  private loadFiscalYears(budgetId: string): void {
    const topId = this.idToTopId().get(budgetId);
    this.impFiscalYearId.set('');
    this.fiscalYearOptions.set([]);
    if (!topId) return;
    this.api.listFiscalYears(topId as Uuid).subscribe({
      next: (fys) => {
        this.fiscalYearOptions.set(fys.map((f) => ({ value: f.id, label: f.display })));
        if (fys.length === 1) this.impFiscalYearId.set(fys[0].id);
      },
      error: () => this.fiscalYearOptions.set([]),
    });
  }

  closeImport(): void {
    this.importLine.set(null);
  }

  confirmImport(): void {
    const line = this.importLine();
    if (!line || !this.impBudgetId() || this.booking()) return;
    this.booking.set(true);
    this.api
      .confirmStatementLine(line.id, {
        budgetId: this.impBudgetId() as Uuid,
        fiscalYearId: (this.impFiscalYearId() || undefined) as Uuid | undefined,
        description: this.impDescription().trim() || undefined,
      })
      .subscribe({
        next: () => {
          this.booking.set(false);
          this.closeImport();
          this.toast.success(this.i18n.translate('fints.booked'));
          this.lines.refresh();
        },
        error: (e) => {
          this.booking.set(false);
          this.toast.error(this.i18n.translate(fintsErrorKey(e)));
        },
      });
  }

  openLink(line: StatementLine): void {
    this.linkLine.set(line);
    this.linkQuery.set('');
    this.linkSelected.set(null);
    this.linkCandidates.set([]);
    // Seed the list with lines of the same amount and kind. This is the most common
    // match. A free search follows.
    this.searchLinkCandidates('', line, Math.abs(Number(line.amount)));
  }

  onLinkSearch(q: string): void {
    this.linkQuery.set(q);
    this.linkSelected.set(null);
    const line = this.linkLine();
    if (!line) return;
    if (this.linkTimer) clearTimeout(this.linkTimer);
    this.linkTimer = setTimeout(() => this.searchLinkCandidates(q.trim(), line), 300);
  }

  private searchLinkCandidates(q: string, line: StatementLine, amount?: number): void {
    this.linkLoading.set(true);
    this.api
      .listExpenses({
        account: this.lines.accountId() as Uuid,
        kind: line.kind,
        unallocated: true,
        q: q || undefined,
        // Without a query, bind to the exact amount so obvious matches come first.
        // With a query, search all open bookings of the account.
        amountMin: q ? undefined : amount,
        amountMax: q ? undefined : amount,
        limit: 10,
      })
      .subscribe({
        next: (page) => {
          this.linkCandidates.set(page.items);
          this.linkLoading.set(false);
        },
        error: () => {
          this.linkCandidates.set([]);
          this.linkLoading.set(false);
        },
      });
  }

  pickLinkCandidate(e: Expense): void {
    this.linkSelected.set(e);
    this.linkCandidates.set([]);
    this.linkQuery.set(this.candidateLabel(e));
  }

  closeLink(): void {
    this.linkLine.set(null);
    if (this.linkTimer) clearTimeout(this.linkTimer);
  }

  confirmLink(): void {
    const line = this.linkLine();
    const sel = this.linkSelected();
    if (!line || !sel || this.booking()) return;
    this.booking.set(true);
    this.api.confirmStatementLine(line.id, { matchExpenseId: sel.id as Uuid }).subscribe({
      next: () => {
        this.booking.set(false);
        this.closeLink();
        this.toast.success(this.i18n.translate('fints.linked'));
        this.lines.refresh();
      },
      error: (e) => {
        this.booking.set(false);
        this.toast.error(this.i18n.translate(fintsErrorKey(e)));
      },
    });
  }

  unlink(line: StatementLine): void {
    if (this.booking()) return;
    this.booking.set(true);
    this.api.unlinkStatementLine(line.id).subscribe({
      next: () => {
        this.booking.set(false);
        this.toast.success(this.i18n.translate('fints.unlinked'));
        this.lines.refresh();
      },
      error: () => {
        this.booking.set(false);
        this.toast.error(this.i18n.translate('fints.errBook'));
      },
    });
  }

  // The ignore action needs the budget.reconcile_ignore permission. It is
  // audit-sensitive.
  readonly ignoreLine = signal<StatementLine | null>(null);
  readonly ignoreReason = signal('');

  openIgnore(line: StatementLine): void {
    this.ignoreLine.set(line);
    this.ignoreReason.set('');
  }

  closeIgnore(): void {
    this.ignoreLine.set(null);
  }

  confirmIgnore(): void {
    const line = this.ignoreLine();
    if (!line || this.booking()) return;
    this.booking.set(true);
    this.api.ignoreStatementLine(line.id, this.ignoreReason().trim() || undefined).subscribe({
      next: () => {
        this.booking.set(false);
        this.closeIgnore();
        this.toast.success(this.i18n.translate('konten.ignored'));
        this.lines.refresh();
      },
      error: (e) => {
        this.booking.set(false);
        this.toast.error(this.i18n.translate(fintsErrorKey(e)));
      },
    });
  }

  /** Undo an ignore. The line returns to the open reconcile queue. */
  reactivate(line: StatementLine): void {
    if (this.booking()) return;
    this.booking.set(true);
    this.api.reactivateStatementLine(line.id).subscribe({
      next: () => {
        this.booking.set(false);
        this.toast.success(this.i18n.translate('konten.reactivated'));
        this.lines.refresh();
      },
      error: (e) => {
        this.booking.set(false);
        this.toast.error(this.i18n.translate(fintsErrorKey(e)));
      },
    });
  }

  dispose(): void {
    if (this.linkTimer) clearTimeout(this.linkTimer);
  }
}
