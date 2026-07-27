import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { skipLoading } from '@core/loading/loading.interceptor';
import type { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { API_BASE_URL } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';

/** Available, bound and requested amount of a node in a fiscal year. Money is a string. */
export interface BudgetAllocationView {
  fiscalYearId: Uuid;
  allocated: string;
  /** Accepted applications, reduced proportionally by committed expenses. */
  bound: string;
  /** Actual expenses. */
  expended: string;
  /** Income increases the available budget. */
  income: string;
  /** Total consumption (bound + expended). Kept for backward compatibility. */
  committed: string;
  /** Requested amount of in-flight applications that are neither accepted nor denied. */
  requested: string;
  available: string;
}

/** Booking kind of an actual movement. */
export type ExpenseKind = 'expense' | 'income';
export type PaymentMethod = 'ueberweisung' | 'bar' | 'lastschrift' | 'karte' | 'paypal';

/** Booked expense or income. Money is a string (Decimal). */
export interface Expense {
  id: Uuid;
  budgetId: Uuid;
  pathKey: string | null;
  fiscalYearId: Uuid;
  kind: ExpenseKind;
  amount: string;
  currency: string;
  description: string;
  applicationId: Uuid | null;
  applicationTitle: string | null;
  accountId: Uuid | null;
  accountName: string | null;
  transferId: Uuid | null;
  // `actor` = raw principal `sub` (audit). `actorName` = server-resolved display
  // name. Always show `actorName` in the UI, never the UUID.
  actor: string | null;
  actorName: string | null;
  // Extra metadata, all optional. Dates as ISO date (YYYY-MM-DD).
  invoiceDate: string | null;
  paymentDate: string | null;
  correspondent: string | null;
  note: string | null;
  referenceNumber: string | null;
  paymentMethod: PaymentMethod | null;
  category: string | null;
  // Linked invoice: 1 invoice : N bookings.
  invoiceId: Uuid | null;
  invoiceNumber: string | null;
  // Sub-bookings: `parentExpenseId` set -> this booking IS a sub-booking.
  // `childCount` > 0 -> it HAS sub-bookings. Such a booking expands, `amount` is
  // the sum of the children, and `amount` is then read-only.
  parentExpenseId: Uuid | null;
  childCount: number;
  createdAt: string;
}

/** Account (name and free-text IBAN). It is not bound to cost centers. */
export interface Account {
  id: Uuid;
  name: string;
  iban: string;
  active: boolean;
  // FinTS bank connection: only endpoint and BLZ. They are the same for all bookers
  // and the admin sets them. `fintsConfigured` = both set -> the account is
  // FinTS-capable. Each booker keeps a personal login and PIN that never appear here.
  fintsEndpoint: string | null;
  fintsBlz: string | null;
  fintsConfigured: boolean;
}

export interface AccountBody {
  name: string;
  iban?: string;
  active?: boolean;
  // FinTS bank connection: `null` or `""` clears it. The login and the PIN are not
  // part of the account master data. Each booker sets them in the bookings tab.
  fintsEndpoint?: string | null;
  fintsBlz?: string | null;
}

/** Personal FinTS credentials of a booker. `fintsPin` is write-only. */
export interface FintsCredentialBody {
  fintsLogin: string;
  fintsPin: string;
}

/** Connection status of a booker for an account. */
export interface FintsCredentialStatus {
  /** Account is FinTS-capable (endpoint + BLZ set on the account). */
  configured: boolean;
  /** The requesting booker has stored their own credentials. */
  hasCredential: boolean;
  /** Login name of the booker. It is not a secret. `null` means no credential. */
  fintsLogin: string | null;
  fintsLastSyncAt: string | null;
  /**
   * Lock cooldown as an ISO timestamp. The server rejects every sync until this
   * time after a bank lock or a signature rejection. `null` means not locked. Until
   * then the frontend disables the fetch button and warns NOT to retry. A retry
   * risks a full bank lock.
   */
  fintsLockedUntil: string | null;
}

/** Staged account statement line. `amount` is signed and a value >0 means incoming. */
export interface StatementLine {
  id: Uuid;
  accountId: Uuid;
  amount: string;
  kind: ExpenseKind;
  currency: string;
  bookingDate: string | null;
  valueDate: string | null;
  purpose: string | null;
  counterpartyName: string | null;
  counterpartyIban: string | null;
  endToEndId: string | null;
  reference: string | null;
  matchState: 'unmatched' | 'suggested' | 'matched' | 'ignored';
  suggestedBudgetId: Uuid | null;
  suggestedPathKey: string | null;
  suggestedExpenseId: Uuid | null;
  /** Booking of a `matched` line — deep-link target for "view booking". */
  matchedExpenseId: Uuid | null;
  createdAt: string;
}

/** Result of a FinTS sync step: done or TAN required. */
export interface BankSyncResult {
  status: 'done' | 'needs_tan';
  accountId: Uuid;
  imported: number;
  duplicates: number;
  sessionToken: Uuid | null;
  challenge: string | null;
  challengeHtml: string | null;
  /** Visual challenge (photoTAN/QR-TAN) as a data URL for direct display. */
  challengeImage: string | null;
  decoupled: boolean;
}

/** Result of the CAMT.053/MT940 file import (option D). */
export interface BankImportResult {
  accountId: Uuid;
  imported: number;
  duplicates: number;
}

/** Confirm a statement line: new booking against `budgetId` OR to `matchExpenseId`. */
export interface ConfirmLineBody {
  budgetId?: Uuid | null;
  fiscalYearId?: Uuid | null;
  matchExpenseId?: Uuid | null;
  description?: string | null;
}

/** Minimal account choice (id + name, no IBAN) for booking dropdowns. */
export interface AccountOption {
  id: Uuid;
  name: string;
  /** Account is FinTS-capable (endpoint + BLZ set). It is not a secret and stays
   *  visible without account.manage. */
  fintsConfigured: boolean;
  /** The requesting booker has already stored their own credentials. */
  fintsHasCredential: boolean;
  fintsLastSyncAt: string | null;
  /** Last bank balance and its as-of date. `null` means never synced. */
  fintsLastBalance: string | null;
  fintsBalanceAt: string | null;
}

/** Transfer from cost center to cost center inside the same fiscal year. */
export interface TransferCreate {
  fromBudgetId: Uuid;
  toBudgetId: Uuid;
  fiscalYearId: Uuid;
  amount: string;
  description: string;
}

/** Offset page of booked expenses/income. */
export interface ExpensePage {
  items: Expense[];
  total: number;
  limit: number;
  offset: number;
}

/** Page of staged account statement lines. */
export interface StatementLinePage {
  items: StatementLine[];
  total: number;
  limit: number;
  offset: number;
}

/** Extra metadata of a booking, used on create and on update. */
export interface ExpenseMetadata {
  invoiceDate?: string | null;
  paymentDate?: string | null;
  correspondent?: string | null;
  note?: string | null;
  referenceNumber?: string | null;
  paymentMethod?: PaymentMethod | null;
  category?: string | null;
  /** Linked invoice. ``null`` removes the link. */
  invoiceId?: Uuid | null;
}

/** Create a booking: standalone (``budgetId``) or bound to an application. */
export interface ExpenseCreate extends ExpenseMetadata {
  amount: string;
  description: string;
  kind?: ExpenseKind;
  budgetId?: Uuid | null;
  fiscalYearId?: Uuid | null;
  applicationId?: Uuid | null;
  // No `accountId`: the account is not a manual booking field. Only the account
  // reconciliation sets it.
}

/** Update a booking: amount, description, cost center and extra metadata. */
export interface ExpenseUpdate extends ExpenseMetadata {
  amount?: string;
  description?: string;
  /** Rebook to another cost center. The fiscal year stays fixed. */
  budgetId?: Uuid;
}

/** Manually create a sub-booking. It carries only its own fields. The parent gives the rest. */
export interface SubBookingBody extends ExpenseMetadata {
  amount: string;
  description: string;
}

export type InvoiceStatus = 'open' | 'paid';

/** Invoice as a standalone document. Money is a string (Decimal). */
export interface Invoice {
  id: Uuid;
  number: string | null;
  issueDate: string | null;
  dueDate: string | null;
  supplier: string | null;
  netAmount: string | null;
  taxAmount: string | null;
  grossAmount: string;
  currency: string;
  note: string | null;
  status: InvoiceStatus;
  fileName: string | null;
  hasFile: boolean;
  actor: string | null;
  createdAt: string;
}

/** Create an invoice. ``grossAmount`` is required and the rest is optional. On
 *  import the parse supplies ``fileToken``, ``fileName`` and ``fileMime``. */
export interface InvoiceCreate {
  number?: string | null;
  issueDate?: string | null;
  dueDate?: string | null;
  supplier?: string | null;
  netAmount?: string | null;
  taxAmount?: string | null;
  grossAmount: string;
  note?: string | null;
  status?: InvoiceStatus;
  fileToken?: string | null;
  fileName?: string | null;
  fileMime?: string | null;
}

/** Update an invoice. It applies only the set fields and does no file handling. */
export interface InvoiceUpdate {
  number?: string | null;
  issueDate?: string | null;
  dueDate?: string | null;
  supplier?: string | null;
  netAmount?: string | null;
  taxAmount?: string | null;
  grossAmount?: string;
  note?: string | null;
  status?: InvoiceStatus;
}

/** Result of ``POST /invoices/parse``: parsed fields + file handle. */
export interface InvoiceParseResult {
  number: string | null;
  issueDate: string | null;
  dueDate: string | null;
  supplier: string | null;
  netAmount: string | null;
  taxAmount: string | null;
  grossAmount: string;
  currency: string;
  fileToken: string;
  fileName: string;
  fileMime: string;
  /** Possible duplicate: an invoice with the same number already exists. */
  duplicate: boolean;
}

/** Handle to a stored document PDF: ``POST /invoices/file``. */
export interface InvoiceFileResult {
  fileToken: string;
  fileName: string;
  fileMime: string;
}

/** Minimal invoice choice for the booking dropdown. */
export interface InvoiceOption {
  id: Uuid;
  label: string;
}

/** Filter and paging of the invoice list. The server does the fuzzy match and the filter. */
export interface InvoiceQuery {
  q?: string;
  status?: InvoiceStatus;
  grossMin?: number;
  grossMax?: number;
  issueFrom?: string;
  issueTo?: string;
  dueFrom?: string;
  dueTo?: string;
  limit?: number;
  offset?: number;
}

/** Offset page of invoices. */
export interface InvoicePage {
  items: Invoice[];
  total: number;
  limit: number;
  offset: number;
}

/** Filter/paging of the bookings list. */
export interface ExpenseQuery {
  /** Exact booking (deep link from the accounts tab). */
  id?: Uuid;
  budget?: Uuid;
  fiscalYear?: Uuid;
  account?: Uuid;
  /** Only bookings without a bank link (link candidates in the accounts tab). */
  unallocated?: boolean;
  kind?: ExpenseKind;
  applicationId?: Uuid;
  q?: string;
  amountMin?: number;
  amountMax?: number;
  createdFrom?: string;
  createdTo?: string;
  sort?: 'createdAt' | 'amount' | 'invoiceDate' | 'paymentDate';
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

/** Tree node (cost center) with the sums per fiscal year and the recursive children. */
export interface BudgetTreeNode {
  id: Uuid;
  parentId: Uuid | null;
  gremiumId: Uuid | null;
  key: string;
  pathKey: string;
  name: string;
  currency: string;
  active: boolean;
  /** Display color for the pie and the tree. `null` means automatic. */
  color: string | null;
  /** Top-level only: flow-state keys that count as accepted/denied. */
  acceptedStateKeys: string[];
  deniedStateKeys: string[];
  /** Hide in the budget tab. This is display only and the rollups do not change. */
  hiddenInBudget: boolean;
  /** Visibility gremium: its members see this subtree in the budget tab as a root.
   *  They need no global budget.* permissions. */
  viewGremiumId: Uuid | null;
  /** Fiscal-year cutoff: the day and month of the period start. Only the top level
   *  uses it. */
  fiscalStartMonth: number;
  fiscalStartDay: number;
  byFiscalYear: BudgetAllocationView[];
  children: BudgetTreeNode[];
}

export interface BudgetNode {
  id: Uuid;
  parentId: Uuid | null;
  gremiumId: Uuid | null;
  key: string;
  pathKey: string;
  name: string;
  currency: string;
  active: boolean;
  color?: string | null;
  acceptedStateKeys?: string[];
  deniedStateKeys?: string[];
  hiddenInBudget?: boolean;
  fiscalStartMonth?: number;
  fiscalStartDay?: number;
}

export interface FiscalYear {
  id: Uuid;
  budgetId: Uuid;
  /** Start year. A fiscal year is unique by year and takes no free text. */
  year: number;
  /** Display: ``YYYY`` (cutoff 01.01.) or ``YYYY/YY`` (otherwise). */
  display: string;
  startDate: string;
  endDate: string;
  active: boolean;
}

export interface BudgetNodeCreate {
  key: string;
  name: string;
  parentId?: Uuid | null;
  gremiumId?: Uuid | null;
  currency?: string;
  color?: string | null;
  fiscalStartMonth?: number;
  fiscalStartDay?: number;
}

/** Partial update of a node. All fields are optional and ``color:""`` clears the color. */
export interface BudgetNodeUpdate {
  key?: string;
  name?: string;
  active?: boolean;
  color?: string | null;
  acceptedStateKeys?: string[];
  deniedStateKeys?: string[];
  hiddenInBudget?: boolean;
  /** Visibility gremium. `null` clears the assignment. */
  viewGremiumId?: Uuid | null;
  fiscalStartMonth?: number;
  fiscalStartDay?: number;
}

export interface FiscalYearCreate {
  year: number;
}

/** An application inside a cost center and its subtree. Used for budget statistics. */
export interface BudgetApplication {
  applicationId: Uuid;
  title: string | null;
  budgetId: Uuid | null;
  pathKey: string | null;
  fiscalYearId: Uuid | null;
  amount: string | null;
  currency: string | null;
  stage: string | null;
  stateId: Uuid | null;
  /** Current flow state (i18n label map and color) for the status column. */
  stateLabel?: Record<string, string> | null;
  stateColor?: string | null;
  createdAt: string;
}

/**
 * Client for the cost-center tree (P(`budget.view`/`manage`)). It calls the tree
 * endpoints `/api/budgets`, fiscal-years and allocations. Money stays a string
 * (Decimal). The UI formats it with `Number`.
 */
@Injectable({ providedIn: 'root' })
export class BudgetTreeApi {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  tree(gremiumId?: string): Observable<BudgetTreeNode[]> {
    const params = gremiumId ? { gremium: gremiumId } : undefined;
    // The budget and dashboard pages have their own loading indicator. Every other
    // call only hydrates the nav or a dropdown, so suppress the global overlay.
    return this.http.get<BudgetTreeNode[]>(`${this.base}/budgets`, {
      params,
      context: skipLoading(),
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

  createFiscalYear(topId: Uuid, body: FiscalYearCreate): Observable<FiscalYear> {
    return this.http.post<FiscalYear>(`${this.base}/budgets/${topId}/fiscal-years`, body);
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
    const params: Record<string, string> = {};
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        params[key] = String(value);
      }
    }
    return this.http.get<ExpensePage>(`${this.base}/expenses`, {
      params,
      context: skipLoading(),
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
  listSubBookings(expenseId: Uuid): Observable<Expense[]> {
    return this.http.get<Expense[]>(`${this.base}/budget-expenses/${expenseId}/sub-bookings`);
  }
  /** Manually create a sub-booking. It inherits account, cost center, fiscal year
   *  and kind from the parent. */
  createSubBooking(expenseId: Uuid, body: SubBookingBody): Observable<Expense> {
    return this.http.post<Expense>(`${this.base}/budget-expenses/${expenseId}/sub-bookings`, body);
  }
  /** Create sub-bookings from a CAMT.053/MT940 file. They inherit account, cost
   *  center, fiscal year and kind. */
  importSubBookings(expenseId: Uuid, file: File): Observable<Expense[]> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<Expense[]>(
      `${this.base}/budget-expenses/${expenseId}/sub-bookings/import`,
      form,
    );
  }

  /** Transfer from cost center to cost center. It books an expense and an income in
   *  the same fiscal year. */
  createTransfer(body: TransferCreate): Observable<unknown> {
    return this.http.post(`${this.base}/budget-transfers`, body);
  }

  /** Invoices, fuzzy-searched, filtered and offset-paginated. Mirrors
   *  {@link listExpenses}. */
  listInvoicesPaged(query: InvoiceQuery = {}): Observable<InvoicePage> {
    const params: Record<string, string> = {};
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        params[key] = String(value);
      }
    }
    return this.http.get<InvoicePage>(`${this.base}/invoices`, {
      params,
      context: skipLoading(),
    });
  }

  /** Full invoice list, newest invoice date first. The booking link dropdown needs
   *  all invoices. */
  listInvoices(): Observable<Invoice[]> {
    return this.listInvoicesPaged({ limit: 200 }).pipe(map((page) => page.items));
  }
  /** Single invoice by ID for the detail dialog. The linked invoice can sit outside
   *  the list cache, which is capped at 200. */
  getInvoice(id: Uuid): Observable<Invoice> {
    return this.http.get<Invoice>(`${this.base}/invoices/${id}`);
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

  listAccounts(): Observable<Account[]> {
    return this.http.get<Account[]>(`${this.base}/accounts`);
  }
  /** Active accounts as id and name (no IBAN) for booking dropdowns. Bookers may
   *  call this without account.manage. */
  listAccountOptions(): Observable<AccountOption[]> {
    return this.http.get<AccountOption[]>(`${this.base}/accounts/options`, {
      context: skipLoading(),
    });
  }
  createAccount(body: AccountBody): Observable<Account> {
    return this.http.post<Account>(`${this.base}/accounts`, body);
  }
  updateAccount(id: Uuid, body: Partial<AccountBody>): Observable<Account> {
    return this.http.patch<Account>(`${this.base}/accounts/${id}`, body);
  }
  deleteAccount(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/accounts/${id}`);
  }

  // Bank reconciliation.
  /** Connection status of a booker for an account: FinTS-capable and own credentials
   *  stored. It skips the global loading overlay because the dialog shows its own. */
  fintsCredentialStatus(accountId: Uuid): Observable<FintsCredentialStatus> {
    return this.http.get<FintsCredentialStatus>(
      `${this.base}/accounts/${accountId}/fints/credential`,
      { context: skipLoading() },
    );
  }
  /** Create or replace the personal FinTS credentials (login and PIN). */
  setFintsCredential(accountId: Uuid, body: FintsCredentialBody): Observable<FintsCredentialStatus> {
    return this.http.put<FintsCredentialStatus>(
      `${this.base}/accounts/${accountId}/fints/credential`,
      body,
    );
  }
  /** Delete own FinTS credentials for the account. */
  deleteFintsCredential(accountId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/accounts/${accountId}/fints/credential`);
  }
  /** Start a FinTS sync: stage statement lines or request a TAN (`needs_tan`). */
  fintsSync(accountId: Uuid): Observable<BankSyncResult> {
    return this.http.post<BankSyncResult>(`${this.base}/accounts/${accountId}/fints/sync`, {});
  }
  /** Continue a pending TAN session. An empty `tan` is a decoupled poll. The poll
   *  skips the global loading overlay. */
  fintsSubmitTan(accountId: Uuid, sessionToken: Uuid, tan: string): Observable<BankSyncResult> {
    return this.http.post<BankSyncResult>(
      `${this.base}/accounts/${accountId}/fints/sessions/${sessionToken}/tan`,
      { tan },
      { context: skipLoading() },
    );
  }
  /** Option D: upload a CAMT.053/MT940 file -> stage statement lines. */
  importStatementFile(accountId: Uuid, file: File): Observable<BankImportResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<BankImportResult>(
      `${this.base}/accounts/${accountId}/statement/import`,
      form,
    );
  }
  /** Staged statement lines, filtered and paginated. */
  listStatementLines(
    opts: {
      account?: Uuid;
      state?: string;
      linked?: boolean;
      includeIgnored?: boolean;
      kind?: ExpenseKind;
      q?: string;
      dateFrom?: string;
      dateTo?: string;
      sort?: 'date' | 'amount';
      order?: 'asc' | 'desc';
      limit?: number;
      offset?: number;
    } = {},
  ): Observable<StatementLinePage> {
    const params: Record<string, string> = {};
    if (opts.account) params['account'] = opts.account;
    if (opts.state) params['state'] = opts.state;
    if (opts.linked !== undefined) params['linked'] = String(opts.linked);
    if (opts.includeIgnored !== undefined) params['includeIgnored'] = String(opts.includeIgnored);
    if (opts.kind) params['kind'] = opts.kind;
    if (opts.q) params['q'] = opts.q;
    if (opts.dateFrom) params['dateFrom'] = opts.dateFrom;
    if (opts.dateTo) params['dateTo'] = opts.dateTo;
    if (opts.sort) params['sort'] = opts.sort;
    if (opts.order) params['order'] = opts.order;
    params['limit'] = String(opts.limit ?? 50);
    params['offset'] = String(opts.offset ?? 0);
    return this.http.get<StatementLinePage>(`${this.base}/statement-lines`, { params });
  }
  /** Book a statement line. */
  confirmStatementLine(lineId: Uuid, body: ConfirmLineBody): Observable<Expense> {
    return this.http.post<Expense>(`${this.base}/statement-lines/${lineId}/confirm`, body);
  }
  /** Mark a statement line as irrelevant (P(``budget.reconcile_ignore``)). The audit
   * reason is optional. */
  ignoreStatementLine(lineId: Uuid, reason?: string): Observable<void> {
    return this.http.post<void>(`${this.base}/statement-lines/${lineId}/ignore`, {
      reason: reason?.trim() || undefined,
    });
  }
  /** Undo an ignore. The line returns to the open reconcile queue
   * (P(``budget.reconcile_ignore``)). */
  reactivateStatementLine(lineId: Uuid): Observable<StatementLine> {
    return this.http.post<StatementLine>(`${this.base}/statement-lines/${lineId}/reactivate`, {});
  }
  /** Remove the statement-line<->booking link. The booking stays and the line reopens. */
  unlinkStatementLine(lineId: Uuid): Observable<StatementLine> {
    return this.http.post<StatementLine>(`${this.base}/statement-lines/${lineId}/unlink`, {});
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
      ids?: string[];
    } = {},
  ): Observable<Blob> {
    let params = new HttpParams();
    for (const [k, v] of Object.entries(opts)) {
      if (k === 'ids' || v === undefined || v === null || v === '') continue;
      params = params.set(k, String(v));
    }
    for (const id of opts.ids ?? []) params = params.append('ids', id);
    return this.http.get(`${this.base}/expenses/export.xlsx`, { params, responseType: 'blob' });
  }

  /** Budget tree as ``.xlsx`` (P(``budget.export``)), filtered like the dashboard. */
  exportXlsx(opts: { node?: string; fiscalYear?: string; gremium?: string } = {}): Observable<Blob> {
    const params: Record<string, string> = {};
    if (opts.node) params['node'] = opts.node;
    if (opts.fiscalYear) params['fiscalYear'] = opts.fiscalYear;
    if (opts.gremium) params['gremium'] = opts.gremium;
    return this.http.get(`${this.base}/budget/export.xlsx`, { params, responseType: 'blob' });
  }

  /** Assign an application to a cost center. ``budgetId=null`` removes the
   *  assignment. ``fiscalYearId`` is optional. If it is set, it names the fiscal
   *  year. If it is unset, the server derives the single active fiscal year, else
   *  it answers 422. */
  assignBudget(
    applicationId: Uuid,
    budgetId: Uuid | null,
    fiscalYearId?: Uuid | null,
  ): Observable<{ applicationId: Uuid; budgetId: Uuid | null; fiscalYearId: Uuid | null }> {
    return this.http.post<{ applicationId: Uuid; budgetId: Uuid | null; fiscalYearId: Uuid | null }>(
      `${this.base}/applications/${applicationId}/assign-budget`,
      { budgetId, fiscalYearId: fiscalYearId ?? null },
    );
  }
}

// The shared path simplification lives in @shared/budget-path. This file imports it,
// uses it below, and re-exports it so that the existing imports keep working.
import { simplifyPathKey } from '@shared/budget-path';
export { simplifyPathKey };

/** Tree (recursive) -> flat option list (pre-order, "pathKey - name", simplified). */
export function flattenBudgetOptions(
  nodes: BudgetTreeNode[],
): { value: Uuid; label: string }[] {
  const out: { value: Uuid; label: string }[] = [];
  const walk = (ns: BudgetTreeNode[]): void => {
    for (const n of ns) {
      out.push({ value: n.id, label: `${simplifyPathKey(n.pathKey)} – ${n.name}` });
      if (n.children?.length) walk(n.children);
    }
  };
  walk(nodes);
  return out;
}

/** An indented tree row (for a tree picker without a real tree widget). */
export interface BudgetTreeRow {
  id: Uuid;
  key: string;
  name: string;
  depth: number;
}

/** Tree (recursive) -> indented flat list (pre-order) with depth per node. */
export function flattenBudgetTreeRows(nodes: BudgetTreeNode[]): BudgetTreeRow[] {
  const out: BudgetTreeRow[] = [];
  const walk = (ns: BudgetTreeNode[], depth: number): void => {
    for (const n of ns) {
      out.push({ id: n.id, key: n.key, name: n.name, depth });
      if (n.children?.length) walk(n.children, depth + 1);
    }
  };
  walk(nodes, 0);
  return out;
}
