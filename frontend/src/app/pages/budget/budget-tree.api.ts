import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';

/** Verfügbar/gebunden/beantragt eines Knotens in einem Haushaltsjahr (Geld als String). */
export interface BudgetAllocationView {
  fiscalYearId: Uuid;
  allocated: string;
  committed: string;
  /** Beantragt (in-flight Anträge, weder accepted noch denied). */
  requested: string;
  available: string;
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
}

export interface FiscalYear {
  id: Uuid;
  budgetId: Uuid;
  label: string;
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
}

/** Teil-Update eines Knotens (alle Felder optional; ``color:""`` löscht die Farbe). */
export interface BudgetNodeUpdate {
  name?: string;
  active?: boolean;
  color?: string | null;
  acceptedStateKeys?: string[];
  deniedStateKeys?: string[];
}

export interface FiscalYearCreate {
  label: string;
  startDate: string;
  endDate: string;
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

/** Baum (rekursiv) → flache Optionsliste (pre-order, „pathKey – name"). */
export function flattenBudgetOptions(
  nodes: BudgetTreeNode[],
): { value: Uuid; label: string }[] {
  const out: { value: Uuid; label: string }[] = [];
  const walk = (ns: BudgetTreeNode[]): void => {
    for (const n of ns) {
      out.push({ value: n.id, label: `${n.pathKey} – ${n.name}` });
      if (n.children?.length) walk(n.children);
    }
  };
  walk(nodes);
  return out;
}
