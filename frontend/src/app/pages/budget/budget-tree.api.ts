import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';

/** Verfügbar/gebunden/beantragt eines Knotens in einem Haushaltsjahr (Geld als String). */
export interface BudgetAllocationView {
  fiscalYearId: Uuid;
  allocated: string;
  /** Gebunden: angenommene Anträge, anteilig um gebundene Ausgaben gemindert (#25). */
  bound: string;
  /** Ausgegeben: tatsächliche Ausgaben (#25). */
  expended: string;
  /** Einnahmen (#25) — erhöhen das verfügbare Budget. */
  income: string;
  /** Gesamt-Verbrauch (= bound + expended, abwärtskompatibel). */
  committed: string;
  /** Beantragt (in-flight Anträge, weder accepted noch denied). */
  requested: string;
  available: string;
}

/** Buchungsart einer tatsächlichen Bewegung (#25). */
export type ExpenseKind = 'expense' | 'income';

/** Gebuchte Ausgabe/Einnahme (#25); Geld als String (Decimal). */
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
  actor: string | null;
  createdAt: string;
}

/** Konto (Name + IBAN-Freitext), nicht an Kostenstellen gebunden. */
export interface Account {
  id: Uuid;
  name: string;
  iban: string;
  active: boolean;
}

export interface AccountBody {
  name: string;
  iban?: string;
  active?: boolean;
}

/** Minimale Konto-Auswahl (id + Name, ohne IBAN) für Buchungs-Dropdowns (#5-2/#2). */
export interface AccountOption {
  id: Uuid;
  name: string;
}

/** Übertrag Kostenstelle → Kostenstelle (gleiches HHJ). */
export interface TransferCreate {
  fromBudgetId: Uuid;
  toBudgetId: Uuid;
  fiscalYearId: Uuid;
  amount: string;
  description: string;
}

/** Offset-Seite gebuchter Ausgaben/Einnahmen. */
export interface ExpensePage {
  items: Expense[];
  total: number;
  limit: number;
  offset: number;
}

/** Buchung anlegen (#25): eigenständig (``budgetId``) oder an Antrag gebunden. */
export interface ExpenseCreate {
  amount: string;
  description: string;
  kind?: ExpenseKind;
  budgetId?: Uuid | null;
  fiscalYearId?: Uuid | null;
  applicationId?: Uuid | null;
  accountId?: Uuid | null;
}

/** Buchung ändern (Betrag/Beschreibung). */
export interface ExpenseUpdate {
  amount?: string;
  description?: string;
}

/** Filter/Paging der Buchungsliste (#25). */
export interface ExpenseQuery {
  budget?: Uuid;
  fiscalYear?: Uuid;
  kind?: ExpenseKind;
  applicationId?: Uuid;
  q?: string;
  amountMin?: number;
  amountMax?: number;
  createdFrom?: string;
  createdTo?: string;
  sort?: 'createdAt' | 'amount';
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

/** Baumknoten (Kostenstelle) inkl. Summen je HHJ + Kinder (rekursiv). */
export interface BudgetTreeNode {
  id: Uuid;
  parentId: Uuid | null;
  gremiumId: Uuid | null;
  key: string;
  pathKey: string;
  name: string;
  currency: string;
  active: boolean;
  /** Anzeigefarbe (Pie/Baum); null = automatisch. */
  color: string | null;
  /** Nur am Top-Level: Flow-State-Keys, die als angenommen/abgelehnt gelten. */
  acceptedStateKeys: string[];
  deniedStateKeys: string[];
  /** Ganze Kostenstelle (inkl. Unterbaum) gilt je HHJ als gebunden (committed = allocated). */
  fullyBound: boolean;
  /** Im Budget-Tab ausblenden (#budget-hide) — reine Anzeige, Rollups unverändert. */
  hiddenInBudget: boolean;
  /** Sichtbarkeits-Gremium (#budget-scope): dessen Mitglieder sehen diesen
   *  Teilbaum im Budget-Tab als Root — ohne globale budget.*-Rechte. */
  viewGremiumId: Uuid | null;
  /** HHJ-Stichtag (Tag/Monat des Periodenstarts) — nur am Top-Level relevant. */
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
  fullyBound?: boolean;
  hiddenInBudget?: boolean;
  fiscalStartMonth?: number;
  fiscalStartDay?: number;
}

export interface FiscalYear {
  id: Uuid;
  budgetId: Uuid;
  /** Startjahr (HHJ ist über das Jahr eindeutig — kein Freitext). */
  year: number;
  /** Anzeige: ``YYYY`` (Stichtag 01.01.) bzw. ``YYYY/YY`` (abweichend). */
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

/** Teil-Update eines Knotens (alle Felder optional; ``color:""`` löscht die Farbe). */
export interface BudgetNodeUpdate {
  key?: string;
  name?: string;
  active?: boolean;
  color?: string | null;
  acceptedStateKeys?: string[];
  deniedStateKeys?: string[];
  fullyBound?: boolean;
  hiddenInBudget?: boolean;
  /** Sichtbarkeits-Gremium (#budget-scope); `null` löscht die Zuordnung. */
  viewGremiumId?: Uuid | null;
  fiscalStartMonth?: number;
  fiscalStartDay?: number;
}

export interface FiscalYearCreate {
  year: number;
}

/** Ein Antrag innerhalb einer Kostenstelle (+ Unterbaum) — Budget-Statistik (#17). */
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
  /** Aktueller Flow-State (i18n-Label-Map + Farbe) für die Status-Spalte (#17). */
  stateLabel?: Record<string, string> | null;
  stateColor?: string | null;
  createdAt: string;
}

/**
 * Client für den Kostenstellen-Baum (#9, api.md »budget«, P(`budget.view`/`manage`)).
 * Spricht die **bereits vorhandenen** Tree-Endpunkte (`/api/budgets`, fiscal-years,
 * allocations). Geld bleibt als String (Decimal) — die UI formatiert über `Number`.
 */
@Injectable({ providedIn: 'root' })
export class BudgetTreeApi {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  tree(gremiumId?: string): Observable<BudgetTreeNode[]> {
    const params = gremiumId ? { gremium: gremiumId } : undefined;
    return this.http.get<BudgetTreeNode[]>(`${this.base}/budgets`, { params });
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
    return this.http.get<FiscalYear[]>(`${this.base}/budgets/${topId}/fiscal-years`);
  }

  createFiscalYear(topId: Uuid, body: FiscalYearCreate): Observable<FiscalYear> {
    return this.http.post<FiscalYear>(`${this.base}/budgets/${topId}/fiscal-years`, body);
  }

  setAllocation(id: Uuid, fiscalYearId: Uuid, allocated: string): Observable<unknown> {
    return this.http.put(`${this.base}/budgets/${id}/allocations/${fiscalYearId}`, { allocated });
  }

  /** Anträge einer Kostenstelle + Unterbaum (#17), optional HHJ-gefiltert. */
  applications(budgetId: Uuid, fiscalYearId?: string): Observable<BudgetApplication[]> {
    const params = fiscalYearId ? { fiscalYear: fiscalYearId } : undefined;
    return this.http.get<BudgetApplication[]>(`${this.base}/budgets/${budgetId}/applications`, {
      params,
    });
  }

  /** Gebuchte Ausgaben/Einnahmen (#25), gefiltert + offset-paginiert. */
  listExpenses(query: ExpenseQuery = {}): Observable<ExpensePage> {
    const params: Record<string, string> = {};
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        params[key] = String(value);
      }
    }
    return this.http.get<ExpensePage>(`${this.base}/expenses`, { params });
  }

  /** Buchung anlegen (#25): eigenständig oder an einen Antrag gebunden. */
  bookExpense(body: ExpenseCreate): Observable<Expense> {
    return this.http.post<Expense>(`${this.base}/expenses`, body);
  }

  /** Betrag/Beschreibung einer Buchung ändern (#25). */
  updateExpense(id: Uuid, body: ExpenseUpdate): Observable<Expense> {
    return this.http.patch<Expense>(`${this.base}/budget-expenses/${id}`, body);
  }

  /** Buchung löschen (#25). Teil eines Übertrags → beide Buchungen weg. */
  deleteExpense(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/budget-expenses/${id}`);
  }

  /** Übertrag Kostenstelle → Kostenstelle (Ausgabe + Einnahme, gleiches HHJ). */
  createTransfer(body: TransferCreate): Observable<unknown> {
    return this.http.post(`${this.base}/budget-transfers`, body);
  }

  // ------------------------------------------------------------- accounts
  listAccounts(): Observable<Account[]> {
    return this.http.get<Account[]>(`${this.base}/accounts`);
  }
  /** Aktive Konten als id+Name (ohne IBAN) für Buchungs-Dropdowns — Bucher dürfen das
   *  ohne account.manage (#5-2/#2). */
  listAccountOptions(): Observable<AccountOption[]> {
    return this.http.get<AccountOption[]>(`${this.base}/accounts/options`);
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

  /** Gefilterte Buchungen als ``.xlsx`` (P(``budget.export``)) — Inhalt wie die Liste. */
  exportExpensesXlsx(opts: Record<string, string | undefined> = {}): Observable<Blob> {
    const params: Record<string, string> = {};
    for (const [k, v] of Object.entries(opts)) if (v) params[k] = v;
    return this.http.get(`${this.base}/expenses/export.xlsx`, { params, responseType: 'blob' });
  }

  /** Budget-Baum als ``.xlsx`` (P(``budget.export``)), gefiltert wie das Dashboard. */
  exportXlsx(opts: { node?: string; fiscalYear?: string; gremium?: string } = {}): Observable<Blob> {
    const params: Record<string, string> = {};
    if (opts.node) params['node'] = opts.node;
    if (opts.fiscalYear) params['fiscalYear'] = opts.fiscalYear;
    if (opts.gremium) params['gremium'] = opts.gremium;
    return this.http.get(`${this.base}/budget/export.xlsx`, { params, responseType: 'blob' });
  }

  /** Antrag einer Kostenstelle zuordnen (#17); ``budgetId=null`` löst die Zuordnung. */
  assignBudget(
    applicationId: Uuid,
    budgetId: Uuid | null,
  ): Observable<{ applicationId: Uuid; budgetId: Uuid | null; fiscalYearId: Uuid | null }> {
    return this.http.post<{ applicationId: Uuid; budgetId: Uuid | null; fiscalYearId: Uuid | null }>(
      `${this.base}/applications/${applicationId}/assign-budget`,
      { budgetId },
    );
  }
}

// Geteilte Pfad-Vereinfachung (#path-display) liegt in @shared/budget-path; lokal
// importiert (für flattenBudgetOptions) + re-exportiert für Bestands-Importe.
import { simplifyPathKey } from '@shared/budget-path';
export { simplifyPathKey };

/** Baum (rekursiv) → flache Optionsliste (pre-order, „pathKey – name", vereinfacht). */
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

/** Eine eingerückte Baumzeile (für Tree-Picker ohne echtes Tree-Widget). */
export interface BudgetTreeRow {
  id: Uuid;
  key: string;
  name: string;
  depth: number;
}

/** Baum (rekursiv) → eingerückte Flachliste (pre-order) mit Tiefe je Knoten. */
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
