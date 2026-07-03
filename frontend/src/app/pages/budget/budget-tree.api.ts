import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { skipLoading } from '@core/loading/loading.interceptor';
import type { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { API_BASE_URL } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';

/** Available/bound/requested of a node in a fiscal year (money as string). */
export interface BudgetAllocationView {
  fiscalYearId: Uuid;
  allocated: string;
  /** Bound: accepted applications, reduced proportionally by committed expenses. */
  bound: string;
  /** Expended: actual expenses. */
  expended: string;
  /** Income — increases the available budget. */
  income: string;
  /** Total consumption (= bound + expended, backwards-compatible). */
  committed: string;
  /** Requested (in-flight applications, neither accepted nor denied). */
  requested: string;
  available: string;
}

/** Booking kind of an actual movement. */
export type ExpenseKind = 'expense' | 'income';
/** Payment method. */
export type PaymentMethod = 'ueberweisung' | 'bar' | 'lastschrift' | 'karte' | 'paypal';

/** Booked expense/income; money as string (Decimal). */
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
  // `actor` = raw principal `sub` (audit); `actorName` = server-resolved display
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
  // `childCount` > 0 -> it HAS sub-bookings (expandable; `amount` = sum of children,
  // then read-only).
  parentExpenseId: Uuid | null;
  childCount: number;
  createdAt: string;
}

/** Account (name + free-text IBAN), not bound to cost-centres. */
export interface Account {
  id: Uuid;
  name: string;
  iban: string;
  active: boolean;
  // FinTS **bank connection**: only endpoint + BLZ (same for all bookers, set by the
  // admin). `fintsConfigured` = both set -> the account is FinTS-capable. Personal
  // logins/PINs are kept per booker and never appear here.
  fintsEndpoint: string | null;
  fintsBlz: string | null;
  fintsConfigured: boolean;
}

export interface AccountBody {
  name: string;
  iban?: string;
  active?: boolean;
  // FinTS bank connection: `null`/`""` clears it. Login/PIN are no longer part of
  // the account master data — each booker sets them in the bookings tab.
  fintsEndpoint?: string | null;
  fintsBlz?: string | null;
}

/** Booker's personal FinTS credentials; `fintsPin` write-only. */
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
  /** Booker's login name (not a secret); `null` when no credential. */
  fintsLogin: string | null;
  fintsLastSyncAt: string | null;
  /**
   * Lock cooldown: ISO timestamp until which the server rejects every sync (after a
   * bank lock/signature rejection). `null` = not locked. Until then the FE disables
   * the fetch button and warns NOT to retry (risk of a full bank lock).
   */
  fintsLockedUntil: string | null;
}

/** Staged account statement line; `amount` signed (>0 incoming). */
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
  /** Account is FinTS-capable (endpoint + BLZ set) — not a secret, visible without account.manage. */
  fintsConfigured: boolean;
  /** The requesting booker has already stored their own credentials. */
  fintsHasCredential: boolean;
  fintsLastSyncAt: string | null;
  /** Last bank balance + as-of date; `null` = never synced. */
  fintsLastBalance: string | null;
  fintsBalanceAt: string | null;
}

/** Transfer cost-centre -> cost-centre (same fiscal year). */
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

/** Extra metadata of a booking — on create & update. */
export interface ExpenseMetadata {
  invoiceDate?: string | null;
  paymentDate?: string | null;
  correspondent?: string | null;
  note?: string | null;
  referenceNumber?: string | null;
  paymentMethod?: PaymentMethod | null;
  category?: string | null;
  /** Linked invoice; ``null`` removes the link. */
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
  // No `accountId`: the account is not a manual booking field, it's only set by the
  // account reconciliation.
}

/** Update a booking: amount, description, cost-centre + extra metadata. */
export interface ExpenseUpdate extends ExpenseMetadata {
  amount?: string;
  description?: string;
  /** Rebook to another cost-centre; fiscal year stays fixed. */
  budgetId?: Uuid;
}

/** Manually create a sub-booking — only its own fields; the rest inherited from the parent. */
export interface SubBookingBody extends ExpenseMetadata {
  amount: string;
  description: string;
}

// ------------------------------------------------------------------ invoices
/** Status of an invoice. */
export type InvoiceStatus = 'open' | 'paid';

/** Invoice — standalone document; money as string (Decimal). */
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

/** Create an invoice: ``grossAmount`` required, the rest optional. On import,
 *  ``fileToken``/``fileName``/``fileMime`` are taken from the parse. */
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

/** Update an invoice — only the set fields; no file handling. */
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

/** Filter/paging of the invoice list — fuzzy-matched + filtered server-side. */
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

/** Tree node (cost-centre) incl. sums per fiscal year + children (recursive). */
export interface BudgetTreeNode {
  id: Uuid;
  parentId: Uuid | null;
  gremiumId: Uuid | null;
  key: string;
  pathKey: string;
  name: string;
  currency: string;
  active: boolean;
  /** Display colour (pie/tree); null = automatic. */
  color: string | null;
  /** Top-level only: flow-state keys that count as accepted/denied. */
  acceptedStateKeys: string[];
  deniedStateKeys: string[];
  /** Hide in the budget tab — display only, rollups unchanged. */
  hiddenInBudget: boolean;
  /** Visibility gremium: its members see this subtree in the budget tab as a root
   *  — without global budget.* permissions. */
  viewGremiumId: Uuid | null;
  /** Fiscal-year cutoff (day/month of the period start) — only relevant at top level. */
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
  /** Start year (a fiscal year is unique by year — no free text). */
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

/** Partial update of a node (all fields optional; ``color:""`` clears the colour). */
export interface BudgetNodeUpdate {
  key?: string;
  name?: string;
  active?: boolean;
  color?: string | null;
  acceptedStateKeys?: string[];
  deniedStateKeys?: string[];
  hiddenInBudget?: boolean;
  /** Visibility gremium; `null` clears the assignment. */
  viewGremiumId?: Uuid | null;
  fiscalStartMonth?: number;
  fiscalStartDay?: number;
}

export interface FiscalYearCreate {
  year: number;
}

/** An application within a cost-centre (+ subtree) — budget statistics. */
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
  /** Current flow state (i18n label map + colour) for the status column. */
  stateLabel?: Record<string, string> | null;
  stateColor?: string | null;
  createdAt: string;
}

/**
 * Client for the cost-centre tree (P(`budget.view`/`manage`)). Talks to the
 * **existing** tree endpoints (`/api/budgets`, fiscal-years, allocations). Money
 * stays as string (Decimal) — the UI formats via `Number`.
 */
@Injectable({ providedIn: 'root' })
export class BudgetTreeApi {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  tree(gremiumId?: string): Observable<BudgetTreeNode[]> {
    const params = gremiumId ? { gremium: gremiumId } : undefined;
    // Budget/dashboard pages have their own loading indicator; otherwise just
    // nav/dropdown hydration -> suppress the global overlay.
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

  /** Applications of a cost-centre + subtree, optionally filtered by fiscal year. */
  applications(budgetId: Uuid, fiscalYearId?: string): Observable<BudgetApplication[]> {
    const params = fiscalYearId ? { fiscalYear: fiscalYearId } : undefined;
    return this.http.get<BudgetApplication[]>(`${this.base}/budgets/${budgetId}/applications`, {
      params,
      context: skipLoading(),
    });
  }

  /** Booked expenses/income, filtered + offset-paginated. */
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

  /** Update a booking's amount/description. */
  updateExpense(id: Uuid, body: ExpenseUpdate): Observable<Expense> {
    return this.http.patch<Expense>(`${this.base}/budget-expenses/${id}`, body);
  }

  /** Delete a booking. Part of a transfer -> both bookings go. */
  deleteExpense(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/budget-expenses/${id}`);
  }

  /** Sub-bookings of a booking — expand in the bookings tab. */
  listSubBookings(expenseId: Uuid): Observable<Expense[]> {
    return this.http.get<Expense[]>(`${this.base}/budget-expenses/${expenseId}/sub-bookings`);
  }
  /** Manually create a sub-booking — inherits account/cost-centre/fiscal year/kind from the parent. */
  createSubBooking(expenseId: Uuid, body: SubBookingBody): Observable<Expense> {
    return this.http.post<Expense>(`${this.base}/budget-expenses/${expenseId}/sub-bookings`, body);
  }
  /** Create sub-bookings from a CAMT.053/MT940 file — inherit account/cost-centre/fiscal year/kind. */
  importSubBookings(expenseId: Uuid, file: File): Observable<Expense[]> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<Expense[]>(
      `${this.base}/budget-expenses/${expenseId}/sub-bookings/import`,
      form,
    );
  }

  /** Transfer cost-centre -> cost-centre (expense + income, same fiscal year). */
  createTransfer(body: TransferCreate): Observable<unknown> {
    return this.http.post(`${this.base}/budget-transfers`, body);
  }

  // ------------------------------------------------------------- invoices
  /** Invoices, fuzzy-searched + filtered + offset-paginated (mirrors
   *  {@link listExpenses}). */
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

  /** Full invoice list (newest invoice date first) — for the booking link dropdown,
   *  which needs all invoices. */
  listInvoices(): Observable<Invoice[]> {
    return this.listInvoicesPaged({ limit: 200 }).pipe(map((page) => page.items));
  }
  /** Single invoice by ID — detail dialog, in case the linked invoice is outside
   *  the list cache capped at 200. */
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
  /** Parse a ZUGFeRD/Factur-X PDF: fields + file handle for the dialog.
   *  422 ``invoice_not_zugferd`` => the UI offers manual entry. */
  parseInvoice(file: File): Observable<InvoiceParseResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<InvoiceParseResult>(`${this.base}/invoices/parse`, form);
  }
  /** Store a document PDF without a ZUGFeRD parse — for manual invoices. */
  uploadInvoiceFile(file: File): Observable<InvoiceFileResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<InvoiceFileResult>(`${this.base}/invoices/file`, form);
  }
  /** Load the original document as a blob: the API streams the PDF because MinIO is
   *  only reachable internally (no presigned URL with an internal host). */
  invoiceFileBlob(id: Uuid): Observable<Blob> {
    return this.http.get(`${this.base}/invoices/${id}/file`, { responseType: 'blob' });
  }

  // ------------------------------------------------------------- accounts
  listAccounts(): Observable<Account[]> {
    return this.http.get<Account[]>(`${this.base}/accounts`);
  }
  /** Active accounts as id+name (no IBAN) for booking dropdowns — bookers may do
   *  this without account.manage. */
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

  // ------------------------------------------------------- bank reconcile
  /** Booker's connection status for an account: FinTS-capable + own credentials
   *  stored? Without the global loading overlay (dialog-internal loading). */
  fintsCredentialStatus(accountId: Uuid): Observable<FintsCredentialStatus> {
    return this.http.get<FintsCredentialStatus>(
      `${this.base}/accounts/${accountId}/fints/credential`,
      { context: skipLoading() },
    );
  }
  /** Create/replace personal FinTS credentials (login + PIN). */
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
  /** Continue a pending TAN session — empty `tan` = decoupled poll. Polls without
   *  the global loading overlay. */
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
  /** Staged statement lines, filtered + paginated. */
  listStatementLines(
    opts: {
      account?: Uuid;
      state?: string;
      linked?: boolean;
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
  /** Mark a statement line as irrelevant (P(``budget.reconcile_ignore``)); optional
   * audit reason. */
  ignoreStatementLine(lineId: Uuid, reason?: string): Observable<void> {
    return this.http.post<void>(`${this.base}/statement-lines/${lineId}/ignore`, {
      reason: reason?.trim() || undefined,
    });
  }
  /** Undo an ignore — the line returns to the open reconcile queue
   * (P(``budget.reconcile_ignore``)). */
  reactivateStatementLine(lineId: Uuid): Observable<StatementLine> {
    return this.http.post<StatementLine>(`${this.base}/statement-lines/${lineId}/reactivate`, {});
  }
  /** Remove the statement-line<->booking link — the booking stays, the line reopens. */
  unlinkStatementLine(lineId: Uuid): Observable<StatementLine> {
    return this.http.post<StatementLine>(`${this.base}/statement-lines/${lineId}/unlink`, {});
  }

  /** Filtered bookings as ``.xlsx`` (P(``budget.export``)) — content like the list. */
  exportExpensesXlsx(opts: Record<string, string | undefined> = {}): Observable<Blob> {
    const params: Record<string, string> = {};
    for (const [k, v] of Object.entries(opts)) if (v) params[k] = v;
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

  /** Assign an application to a cost-centre; ``budgetId=null`` removes the assignment.
   *  ``fiscalYearId`` optional: set -> explicit fiscal year; unset -> the server
   *  derives the single active fiscal year (else 422). */
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

// The shared path simplification lives in @shared/budget-path; imported locally
// (for flattenBudgetOptions) + re-exported for existing imports.
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
