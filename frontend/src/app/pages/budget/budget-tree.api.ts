import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { skipLoading } from '@stupa-makers/ui-kit';
import { cached, detailContext, listContext } from '@core/cache/cache.interceptor';
import { of, type Observable } from 'rxjs';
import { FeatureService } from '@core/features/feature.service';
import { map } from 'rxjs/operators';
import { API_BASE_URL } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';

/** Available, bound and requested amount of a node in a fiscal year. Money is a string. */
export interface BudgetAllocationView {
  readonly fiscalYearId: Uuid;
  readonly allocated: string;
  /** Accepted applications, reduced proportionally by committed expenses. */
  readonly bound: string;
  /** Actual expenses. */
  readonly expended: string;
  /** Income increases the available budget. */
  readonly income: string;
  /** Total consumption (bound + expended). Kept for backward compatibility. */
  readonly committed: string;
  /** Requested amount of in-flight applications that are neither accepted nor denied. */
  readonly requested: string;
  readonly available: string;
}

/** Booking kind of an actual movement. */
export type ExpenseKind = 'expense' | 'income';
export type PaymentMethod = 'ueberweisung' | 'bar' | 'lastschrift' | 'karte' | 'paypal';

/** Booked expense or income. Money is a string (Decimal). */
export interface Expense {
  readonly id: Uuid;
  readonly budgetId: Uuid;
  readonly pathKey: string | null;
  readonly fiscalYearId: Uuid;
  readonly kind: ExpenseKind;
  readonly amount: string;
  readonly currency: string;
  readonly description: string;
  readonly applicationId: Uuid | null;
  readonly applicationTitle: string | null;
  readonly transferId: Uuid | null;
  /** The raw principal `sub` (audit). The UI shows `actorName`, never the UUID. */
  readonly actor: string | null;
  /** The display name of `actor`, resolved by the server. */
  readonly actorName: string | null;
  /** Extra metadata from here on, all optional. Dates are ISO dates (YYYY-MM-DD). */
  readonly invoiceDate: string | null;
  readonly paymentDate: string | null;
  readonly correspondent: string | null;
  readonly note: string | null;
  readonly referenceNumber: string | null;
  readonly paymentMethod: PaymentMethod | null;
  readonly category: string | null;
  /** The linked invoice. One invoice can back many bookings. */
  readonly invoiceId: Uuid | null;
  readonly invoiceNumber: string | null;
  /** Set when this booking is a sub-booking. */
  readonly parentExpenseId: Uuid | null;
  /**
   * The number of sub-bookings. A booking with sub-bookings expands, and its `amount` is the
   * sum of the children and read-only.
   */
  readonly childCount: number;
  readonly createdAt: string;
}

/** Transfer from cost center to cost center inside the same fiscal year. */
export interface TransferCreate {
  readonly fromBudgetId: Uuid;
  readonly toBudgetId: Uuid;
  readonly fiscalYearId: Uuid;
  readonly amount: string;
  readonly description: string;
}

/**
 * One transfer as a single row (`TransferRowOut`).
 *
 * A transfer is two bookings, an expense on the source and an income on the
 * target. This row assembles both, so a transfer has one identity that can be
 * corrected or removed. `actorName` is the resolved display name. Never show
 * `actor`, it is the raw principal id.
 */
export interface BudgetTransfer {
  readonly transferId: Uuid;
  readonly expenseId: Uuid;
  readonly incomeId: Uuid;
  readonly fromBudgetId: Uuid;
  readonly fromPathKey: string | null;
  readonly toBudgetId: Uuid;
  readonly toPathKey: string | null;
  readonly fiscalYearId: Uuid;
  readonly amount: string;
  readonly currency: string;
  readonly description: string;
  readonly note: string | null;
  readonly invoiceDate: string | null;
  readonly paymentDate: string | null;
  readonly actor: string | null;
  readonly actorName: string | null;
  readonly createdAt: string;
}

/** Offset page of transfers. */
export interface TransferPage {
  readonly items: readonly BudgetTransfer[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

/** Query of `GET /budget-transfers`. `budget` matches either cost centre. */
export interface TransferQuery {
  readonly id?: Uuid;
  readonly budget?: Uuid;
  readonly fiscalYear?: Uuid;
  readonly q?: string;
  readonly amountMin?: number | string;
  readonly amountMax?: number | string;
  readonly createdFrom?: string;
  readonly createdTo?: string;
  readonly sort?: 'createdAt' | 'amount' | 'invoiceDate' | 'paymentDate';
  readonly order?: 'asc' | 'desc';
  readonly limit?: number;
  readonly offset?: number;
}

/**
 * Patch of a transfer. It writes both legs at once.
 *
 * The two cost centres are immutable. Sending a different pair answers 409, so
 * this body never carries them. The fiscal year is not patchable at all.
 */
export interface TransferUpdate {
  readonly amount?: string;
  readonly description?: string;
  readonly note?: string | null;
  readonly invoiceDate?: string | null;
  readonly paymentDate?: string | null;
}

/** Offset page of booked expenses/income. */
export interface ExpensePage {
  readonly items: readonly Expense[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

/** Extra metadata of a booking, used on create and on update. */
export interface ExpenseMetadata {
  readonly invoiceDate?: string | null;
  readonly paymentDate?: string | null;
  readonly correspondent?: string | null;
  readonly note?: string | null;
  readonly referenceNumber?: string | null;
  readonly paymentMethod?: PaymentMethod | null;
  readonly category?: string | null;
  /** Linked invoice. ``null`` removes the link. */
  readonly invoiceId?: Uuid | null;
}

/** Create a booking: standalone (``budgetId``) or bound to an application. */
export interface ExpenseCreate extends ExpenseMetadata {
  readonly amount: string;
  readonly description: string;
  readonly kind?: ExpenseKind;
  readonly budgetId?: Uuid | null;
  readonly fiscalYearId?: Uuid | null;
  readonly applicationId?: Uuid | null;
}

/** Update a booking: amount, description, cost center and extra metadata. */
export interface ExpenseUpdate extends ExpenseMetadata {
  readonly amount?: string;
  readonly description?: string;
  /** Rebook to another cost center. The fiscal year stays fixed. */
  readonly budgetId?: Uuid;
}

/** Manually create a sub-booking. It carries only its own fields. The parent gives the rest. */
export interface SubBookingBody extends ExpenseMetadata {
  readonly amount: string;
  readonly description: string;
}

export type InvoiceStatus = 'open' | 'paid';

/** Invoice as a standalone document. Money is a string (Decimal). */
export interface Invoice {
  readonly id: Uuid;
  readonly number: string | null;
  readonly issueDate: string | null;
  readonly dueDate: string | null;
  readonly supplier: string | null;
  readonly netAmount: string | null;
  readonly taxAmount: string | null;
  readonly grossAmount: string;
  readonly currency: string;
  readonly note: string | null;
  readonly status: InvoiceStatus;
  readonly fileName: string | null;
  readonly hasFile: boolean;
  readonly actor: string | null;
  readonly createdAt: string;
  /**
   * The bookings that reference this invoice, in booking order. The server sends
   * only the bookings on cost centres the reader may see. An older backend sends no
   * field at all: the list then hides its bookings column instead of asking for the
   * bookings of each invoice one by one.
   */
  readonly linkedBookings?: readonly InvoiceBooking[];
}

/** One booking on an invoice, as the invoice list shows it. */
export interface InvoiceBooking {
  readonly id: Uuid;
  readonly budgetId: Uuid;
  readonly pathKey: string;
  readonly budgetName: string;
  readonly fiscalYearId: Uuid;
  readonly kind: ExpenseKind;
  readonly amount: string;
  readonly description: string;
  readonly paymentDate: string | null;
  /** Set when the booking is a sub-booking of another booking. */
  readonly parentExpenseId: Uuid | null;
  readonly createdAt: string;
}

/** Create an invoice. ``grossAmount`` is required and the rest is optional. On
 *  import the parse supplies ``fileToken``, ``fileName`` and ``fileMime``. */
export interface InvoiceCreate {
  readonly number?: string | null;
  readonly issueDate?: string | null;
  readonly dueDate?: string | null;
  readonly supplier?: string | null;
  readonly netAmount?: string | null;
  readonly taxAmount?: string | null;
  readonly grossAmount: string;
  readonly note?: string | null;
  readonly status?: InvoiceStatus;
  readonly fileToken?: string | null;
  readonly fileName?: string | null;
  readonly fileMime?: string | null;
}

/** Update an invoice. It applies only the set fields and does no file handling. */
export interface InvoiceUpdate {
  readonly number?: string | null;
  readonly issueDate?: string | null;
  readonly dueDate?: string | null;
  readonly supplier?: string | null;
  readonly netAmount?: string | null;
  readonly taxAmount?: string | null;
  readonly grossAmount?: string;
  readonly note?: string | null;
  readonly status?: InvoiceStatus;
}

/** Result of ``POST /invoices/parse``: parsed fields + file handle. */
export interface InvoiceParseResult {
  readonly number: string | null;
  readonly issueDate: string | null;
  readonly dueDate: string | null;
  readonly supplier: string | null;
  readonly netAmount: string | null;
  readonly taxAmount: string | null;
  readonly grossAmount: string;
  readonly currency: string;
  readonly fileToken: string;
  readonly fileName: string;
  readonly fileMime: string;
  /** Possible duplicate: an invoice with the same number already exists. */
  readonly duplicate: boolean;
}

/** Handle to a stored document PDF: ``POST /invoices/file``. */
export interface InvoiceFileResult {
  readonly fileToken: string;
  readonly fileName: string;
  readonly fileMime: string;
}

/** Filter and paging of the invoice list. The server does the fuzzy match and the filter. */
export interface InvoiceQuery {
  /** The exact invoice, for a deep link such as a global-search hit. */
  readonly id?: string;
  readonly q?: string;
  readonly status?: InvoiceStatus;
  /**
   * With (`true`) or without (`false`) a booking the reader can see. With `status: 'open'`
   * this gives the list segments "Verbucht" and "Eingang".
   */
  readonly booked?: boolean;
  readonly grossMin?: number;
  readonly grossMax?: number;
  readonly issueFrom?: string;
  readonly issueTo?: string;
  readonly dueFrom?: string;
  readonly dueTo?: string;
  readonly limit?: number;
  readonly offset?: number;
}

/**
 * The size of each segment of the invoice list under the other filters of the request:
 * all, "Eingang" (open, no booking), "Verbucht" (open, with a booking) and "Bezahlt".
 */
export interface InvoiceSegmentCounts {
  readonly all: number;
  readonly inbox: number;
  readonly booked: number;
  readonly paid: number;
}

/** Offset page of invoices. */
export interface InvoicePage {
  readonly items: readonly Invoice[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
  /** The segment counts. An older backend sends none. */
  readonly counts?: InvoiceSegmentCounts;
}

/** Filter/paging of the bookings list. */
export interface ExpenseQuery {
  /** Exact booking (deep link). */
  readonly id?: Uuid;
  readonly budget?: Uuid;
  readonly fiscalYear?: Uuid;
  readonly kind?: ExpenseKind;
  readonly applicationId?: Uuid;
  readonly q?: string;
  readonly amountMin?: number;
  readonly amountMax?: number;
  readonly createdFrom?: string;
  readonly createdTo?: string;
  readonly sort?: 'createdAt' | 'amount' | 'invoiceDate' | 'paymentDate';
  readonly order?: 'asc' | 'desc';
  readonly limit?: number;
  readonly offset?: number;
}

/** Tree node (cost center) with the sums per fiscal year and the recursive children. */
export interface BudgetTreeNode {
  readonly id: Uuid;
  readonly parentId: Uuid | null;
  readonly gremiumId: Uuid | null;
  readonly key: string;
  readonly pathKey: string;
  readonly name: string;
  readonly currency: string;
  readonly active: boolean;
  /** Display color for the pie and the tree. `null` means automatic. */
  readonly color: string | null;
  /** Hide in the budget tab. This is display only and the rollups do not change. */
  readonly hiddenInBudget: boolean;
  /** Visibility gremium: its members see this subtree in the budget tab as a root.
   *  They need no global budget.* permissions. */
  readonly viewGremiumId: Uuid | null;
  /** The gremium that decides on spending from this node (its OWN value). */
  readonly decisionGremiumId?: Uuid | null;
  /** The own value, else the value of the nearest ancestor, else `null` (read only). */
  readonly effectiveDecisionGremiumId?: Uuid | null;
  /** The node that supplies the effective value: this node, an ancestor, or `null`. */
  readonly decisionGremiumSourceId?: Uuid | null;
  /** Fiscal-year cutoff: the day and month of the period start. Only the top level
   *  uses it. */
  readonly fiscalStartMonth: number;
  readonly fiscalStartDay: number;
  readonly byFiscalYear: readonly BudgetAllocationView[];
  readonly children: readonly BudgetTreeNode[];
}

export interface BudgetNode {
  readonly id: Uuid;
  readonly parentId: Uuid | null;
  readonly gremiumId: Uuid | null;
  readonly key: string;
  readonly pathKey: string;
  readonly name: string;
  readonly currency: string;
  readonly active: boolean;
  readonly color?: string | null;
  readonly hiddenInBudget?: boolean;
  readonly decisionGremiumId?: Uuid | null;
  readonly effectiveDecisionGremiumId?: Uuid | null;
  readonly decisionGremiumSourceId?: Uuid | null;
  readonly fiscalStartMonth?: number;
  readonly fiscalStartDay?: number;
}

/** The problem code of a money mutation on a closed fiscal year (409). */
export const FISCAL_YEAR_CLOSED = 'fiscal_year_closed';

export interface FiscalYear {
  readonly id: Uuid;
  readonly budgetId: Uuid;
  /** Start year. A fiscal year is unique by year and takes no free text. */
  readonly year: number;
  /** Display: ``YYYY`` (cutoff 01.01.) or ``YYYY/YY`` (otherwise). */
  readonly display: string;
  readonly startDate: string;
  readonly endDate: string;
  readonly active: boolean;
  /** Set while the year is closed ("abgeschlossen"): its money data is frozen, and
   *  every booking, transfer, limit or assignment on it answers 409. */
  readonly closedAt?: string | null;
}

export interface BudgetNodeCreate {
  readonly key: string;
  readonly name: string;
  readonly parentId?: Uuid | null;
  readonly gremiumId?: Uuid | null;
  readonly decisionGremiumId?: Uuid | null;
  readonly currency?: string;
  readonly color?: string | null;
  readonly fiscalStartMonth?: number;
  readonly fiscalStartDay?: number;
}

/** Partial update of a node. All fields are optional and ``color:""`` clears the color. */
export interface BudgetNodeUpdate {
  readonly key?: string;
  readonly name?: string;
  readonly active?: boolean;
  readonly color?: string | null;
  readonly hiddenInBudget?: boolean;
  /** Visibility gremium. `null` clears the assignment. */
  readonly viewGremiumId?: Uuid | null;
  /** Deciding gremium of the node. `null` clears it; the node then inherits. */
  readonly decisionGremiumId?: Uuid | null;
  readonly fiscalStartMonth?: number;
  readonly fiscalStartDay?: number;
}

export interface FiscalYearCreate {
  readonly year: number;
}

/** Partial update of a fiscal year. Only the year and the active flag are editable. */
export interface FiscalYearUpdate {
  readonly year?: number;
  readonly active?: boolean;
}

/** An application inside a cost center and its subtree. Used for budget statistics. */
export interface BudgetApplication {
  readonly applicationId: Uuid;
  readonly title: string | null;
  readonly budgetId: Uuid | null;
  readonly pathKey: string | null;
  readonly fiscalYearId: Uuid | null;
  readonly amount: string | null;
  readonly currency: string | null;
  readonly stateId: Uuid | null;
  /** Current flow state (i18n label map and color) for the status column. */
  readonly stateLabel?: Record<string, string> | null;
  readonly stateColor?: string | null;
  readonly createdAt: string;
}

/**
 * Client for the cost-center tree (P(`budget.view`/`manage`)). It calls the tree
 * endpoints `/api/budgets`, fiscal-years and allocations. Money stays a string
 * (Decimal). The UI formats it with `Number`.
 */
/** The tree changes only when a cost centre is edited, and that invalidates it. */
const TREE_TTL_MS = 5 * 60_000;

/** Whether a query value is set: `undefined`, `null` and the empty string are not. */
const isSet = (value: unknown): boolean => value !== undefined && value !== null && value !== '';

/** The set values of a list query as string params, in the order of the query's keys. */
function queryParams(query: object): Readonly<Record<string, string>> {
  return Object.fromEntries(
    Object.entries(query)
      .filter(([, value]) => isSet(value))
      .map(([key, value]) => [key, String(value)]),
  );
}

@Injectable({ providedIn: 'root' })
export class BudgetTreeApi {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);
  private readonly features = inject(FeatureService);

  /**
   * The budget and dashboard pages have their own loading indicator; every other call only fills
   * the nav or a dropdown, so it suppresses the global overlay. It is cached, because five pages
   * ask for the whole tree and a mutation under `/budgets` drops every entry there. While
   * `Budget` is off the tree is empty without a request (spec 000758), so a filter or a
   * choice of cost centres on another page has nothing to show.
   */
  tree(gremiumId?: string): Observable<BudgetTreeNode[]> {
    if (!this.features.isOn('budget')) return of([]);
    const params = gremiumId ? { gremium: gremiumId } : undefined;
    return this.http.get<BudgetTreeNode[]>(`${this.base}/budgets`, {
      params,
      context: cached(TREE_TTL_MS, skipLoading()),
    });
  }

  createNode(body: BudgetNodeCreate): Observable<BudgetNode> {
    return this.http.post<BudgetNode>(`${this.base}/budgets`, body);
  }

  updateNode(id: Uuid, body: BudgetNodeUpdate): Observable<BudgetNode> {
    return this.http.patch<BudgetNode>(`${this.base}/budgets/${id}`, body);
  }

  deleteNode(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/budgets/${id}`);
  }

  listFiscalYears(topId: Uuid): Observable<FiscalYear[]> {
    return this.http.get<FiscalYear[]>(`${this.base}/budgets/${topId}/fiscal-years`, {
      context: skipLoading(),
    });
  }

  /**
   * The fiscal years of a root, cached like {@link tree}. Every figure of the budget page
   * belongs to a year, so the page waits for this read before it shows an amount; the
   * prefetch warms it with the tree, so a visit paints the amounts at once. A cached read
   * emits twice when the fresh answer differs, so only a caller that takes a second
   * emission uses it. A write under `/budgets` drops the entry.
   */
  cachedFiscalYears(topId: Uuid): Observable<FiscalYear[]> {
    return this.http.get<FiscalYear[]>(`${this.base}/budgets/${topId}/fiscal-years`, {
      context: cached(TREE_TTL_MS, skipLoading()),
    });
  }

  createFiscalYear(topId: Uuid, body: FiscalYearCreate): Observable<FiscalYear> {
    return this.http.post<FiscalYear>(`${this.base}/budgets/${topId}/fiscal-years`, body);
  }

  /** Correct the year or the active flag. Needs P(`budget.structure`). A year that
   *  already exists in the same top budget answers 422. */
  updateFiscalYear(topId: Uuid, fyId: Uuid, body: FiscalYearUpdate): Observable<FiscalYear> {
    return this.http.patch<FiscalYear>(`${this.base}/budgets/${topId}/fiscal-years/${fyId}`, body);
  }

  /** Delete a fiscal year. Needs P(`budget.structure`). The route answers 409 while
   *  bookings, allocations or applications still reference the year. */
  deleteFiscalYear(topId: Uuid, fyId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/budgets/${topId}/fiscal-years/${fyId}`);
  }

  /** Close a fiscal year, or reopen it. Needs P(`budget.structure`). */
  setFiscalYearClosed(topId: Uuid, fyId: Uuid, closed: boolean): Observable<FiscalYear> {
    const action = closed ? 'close' : 'reopen';
    return this.http.post<FiscalYear>(`${this.base}/budgets/${topId}/fiscal-years/${fyId}/${action}`, {});
  }

  setAllocation(id: Uuid, fiscalYearId: Uuid, allocated: string): Observable<unknown> {
    return this.http.put(`${this.base}/budgets/${id}/allocations/${fiscalYearId}`, { allocated });
  }

  /** Applications of a cost center and its subtree, optionally filtered by fiscal year. */
  applications(budgetId: Uuid, fiscalYearId?: string): Observable<BudgetApplication[]> {
    const params = fiscalYearId ? { fiscalYear: fiscalYearId } : undefined;
    return this.http.get<BudgetApplication[]>(`${this.base}/budgets/${budgetId}/applications`, {
      params,
      context: skipLoading(),
    });
  }

  /** Booked expenses and income, filtered and offset-paginated. */
  listExpenses(query: ExpenseQuery = {}): Observable<ExpensePage> {
    const params = queryParams(query);
    return this.http.get<ExpensePage>(`${this.base}/expenses`, {
      params,
      context: listContext(query.offset),
    });
  }

  /** Create a booking: standalone or bound to an application. */
  bookExpense(body: ExpenseCreate): Observable<Expense> {
    return this.http.post<Expense>(`${this.base}/expenses`, body);
  }

  updateExpense(id: Uuid, body: ExpenseUpdate): Observable<Expense> {
    return this.http.patch<Expense>(`${this.base}/budget-expenses/${id}`, body);
  }

  /** Delete a booking. If it is part of a transfer, both bookings go. */
  deleteExpense(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/budget-expenses/${id}`);
  }

  /** Sub-bookings of a booking. The bookings tab expands them. */
  /** `detail` keeps the answer for the read ahead of the booking list (`prefetchDetails`). */
  listSubBookings(expenseId: Uuid, opts: { detail?: boolean } = {}): Observable<Expense[]> {
    return this.http.get<Expense[]>(`${this.base}/budget-expenses/${expenseId}/sub-bookings`, {
      context: opts.detail ? detailContext() : undefined,
    });
  }
  /** Manually create a sub-booking. It inherits the cost center, the fiscal year
   *  and the kind from the parent. */
  createSubBooking(expenseId: Uuid, body: SubBookingBody): Observable<Expense> {
    return this.http.post<Expense>(`${this.base}/budget-expenses/${expenseId}/sub-bookings`, body);
  }
  /** Transfer from cost center to cost center. It books an expense and an income in
   *  the same fiscal year. */
  createTransfer(body: TransferCreate): Observable<unknown> {
    return this.http.post(`${this.base}/budget-transfers`, body);
  }

  /** Transfers as their own paged list. Mirrors {@link listExpenses}. */
  listTransfers(query: TransferQuery = {}): Observable<TransferPage> {
    const params = queryParams(query);
    return this.http.get<TransferPage>(`${this.base}/budget-transfers`, {
      params,
      context: skipLoading(),
    });
  }

  /** Correct a transfer. Both legs change together. A different cost-centre
   *  pair answers 409, so the body never carries the pair. */
  updateTransfer(transferId: Uuid, body: TransferUpdate): Observable<BudgetTransfer> {
    return this.http.patch<BudgetTransfer>(`${this.base}/budget-transfers/${transferId}`, body);
  }

  /** Delete a transfer with both of its bookings. */
  deleteTransfer(transferId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/budget-transfers/${transferId}`);
  }

  /** Invoices, fuzzy-searched, filtered and offset-paginated. Mirrors
   *  {@link listExpenses}. */
  listInvoicesPaged(query: InvoiceQuery = {}): Observable<InvoicePage> {
    const params = queryParams(query);
    return this.http.get<InvoicePage>(`${this.base}/invoices`, {
      params,
      context: listContext(query.offset),
    });
  }

  /** Full invoice list, newest invoice date first. The booking link dropdown needs
   *  all invoices. */
  listInvoices(): Observable<readonly Invoice[]> {
    return this.listInvoicesPaged({ limit: 200 }).pipe(map((page) => page.items));
  }
  /** Single invoice by ID for the detail dialog. The linked invoice can sit outside
   *  the list cache, which is capped at 200. */
  /** `detail` keeps the answer for the read ahead of the booking list (`prefetchDetails`). */
  getInvoice(id: Uuid, opts: { detail?: boolean } = {}): Observable<Invoice> {
    return this.http.get<Invoice>(`${this.base}/invoices/${id}`, {
      context: opts.detail ? detailContext() : undefined,
    });
  }
  createInvoice(body: InvoiceCreate): Observable<Invoice> {
    return this.http.post<Invoice>(`${this.base}/invoices`, body);
  }
  updateInvoice(id: Uuid, body: InvoiceUpdate): Observable<Invoice> {
    return this.http.patch<Invoice>(`${this.base}/invoices/${id}`, body);
  }
  deleteInvoice(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/invoices/${id}`);
  }
  /** Parse a ZUGFeRD/Factur-X PDF: fields and a file handle for the dialog.
   *  On 422 ``invoice_not_zugferd`` the UI offers manual entry. */
  parseInvoice(file: File): Observable<InvoiceParseResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<InvoiceParseResult>(`${this.base}/invoices/parse`, form);
  }
  /** Store a document PDF without a ZUGFeRD parse. This serves manual invoices. */
  uploadInvoiceFile(file: File): Observable<InvoiceFileResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<InvoiceFileResult>(`${this.base}/invoices/file`, form);
  }
  /** Load the original document as a blob. The API streams the PDF because MinIO is
   *  reachable only internally, so a presigned URL would carry an internal host. */
  invoiceFileBlob(id: Uuid): Observable<Blob> {
    return this.http.get(`${this.base}/invoices/${id}/file`, { responseType: 'blob' });
  }

  /** Filtered bookings as ``.xlsx`` (P(``budget.export``)). The content matches the
   *  list. Optional ``ids`` exports exactly the selected bookings
   *  (#expenses-ux: bulk export). */
  exportExpensesXlsx(
    opts: {
      budget?: string;
      kind?: string;
      q?: string;
      amountMin?: string;
      amountMax?: string;
      createdFrom?: string;
      createdTo?: string;
      ids?: readonly string[];
    } = {},
  ): Observable<Blob> {
    const scalars = Object.entries(opts).filter(([k, v]) => k !== 'ids' && isSet(v));
    const withScalars = scalars.reduce((p, [k, v]) => p.set(k, String(v)), new HttpParams());
    const params = (opts.ids ?? []).reduce((p, id) => p.append('ids', id), withScalars);
    return this.http.get(`${this.base}/expenses/export.xlsx`, { params, responseType: 'blob' });
  }

  /** Budget tree as ``.xlsx`` (P(``budget.export``)), filtered like the dashboard. */
  exportXlsx(
    opts: { node?: string; fiscalYear?: string; gremium?: string } = {},
  ): Observable<Blob> {
    const params: Readonly<Record<string, string>> = {
      ...(opts.node ? { node: opts.node } : {}),
      ...(opts.fiscalYear ? { fiscalYear: opts.fiscalYear } : {}),
      ...(opts.gremium ? { gremium: opts.gremium } : {}),
    };
    return this.http.get(`${this.base}/budget/export.xlsx`, { params, responseType: 'blob' });
  }

  /** Assign an application to a cost center. ``budgetId=null`` removes the
   *  assignment. ``fiscalYearId`` is optional. If it is set, it names the fiscal
   *  year. If it is unset, the server derives the current fiscal year (the only
   *  active open one, else the active open one that holds today), else it answers 422. */
  assignBudget(
    applicationId: Uuid,
    budgetId: Uuid | null,
    fiscalYearId?: Uuid | null,
  ): Observable<{ applicationId: Uuid; budgetId: Uuid | null; fiscalYearId: Uuid | null }> {
    return this.http.post<{
      applicationId: Uuid;
      budgetId: Uuid | null;
      fiscalYearId: Uuid | null;
    }>(`${this.base}/applications/${applicationId}/assign-budget`, {
      budgetId,
      fiscalYearId: fiscalYearId ?? null,
    });
  }
}

import { simplifyPathKey } from '@shared/budget-path';
/** Re-exported from `@shared/budget-path`, so the imports from this file keep working. */
export { simplifyPathKey };

/** Tree (recursive) -> flat option list (pre-order, "pathKey - name", simplified). */
export function flattenBudgetOptions(
  nodes: readonly BudgetTreeNode[],
): readonly { readonly value: Uuid; readonly label: string }[] {
  return nodes.flatMap((n) => [
    { value: n.id, label: `${simplifyPathKey(n.pathKey)} – ${n.name}` },
    ...(n.children?.length ? flattenBudgetOptions(n.children) : []),
  ]);
}
