import type { BudgetApplication, Expense } from '../budget-tree.api';

/** An application of a cost centre for a spec. */
export function itemApp(over: Partial<BudgetApplication> & { applicationId: string }): BudgetApplication {
  return {
    applicationId: over.applicationId,
    title: 'title' in over ? (over.title ?? null) : `Antrag ${over.applicationId}`,
    budgetId: 'budgetId' in over ? (over.budgetId ?? null) : 'b-800',
    pathKey: 'pathKey' in over ? (over.pathKey ?? null) : 'VS-800',
    fiscalYearId: over.fiscalYearId ?? 'fy-1',
    amount: over.amount === undefined ? '120.00' : over.amount,
    currency: 'currency' in over ? (over.currency ?? null) : 'EUR',
    stateId: over.stateId ?? null,
    stateLabel: 'stateLabel' in over ? over.stateLabel : { de: 'In Prüfung', en: 'In review' },
    stateColor: over.stateColor ?? '#d9a400',
    createdAt: over.createdAt ?? '2026-05-01T10:00:00Z',
  };
}

/** A top-level booking for a spec. */
export function itemBooking(over: Partial<Expense> & { id: string }): Expense {
  return {
    budgetId: 'b-800',
    pathKey: 'VS-800',
    fiscalYearId: 'fy-1',
    kind: 'expense',
    amount: '20.00',
    currency: 'EUR',
    description: `Buchung ${over.id}`,
    applicationId: null,
    applicationTitle: null,
    transferId: null,
    actor: null,
    actorName: null,
    invoiceDate: null,
    paymentDate: null,
    correspondent: null,
    note: null,
    referenceNumber: null,
    paymentMethod: null,
    category: null,
    invoiceId: null,
    invoiceNumber: null,
    parentExpenseId: null,
    childCount: 0,
    createdAt: '2026-05-01T10:00:00Z',
    ...over,
  };
}
