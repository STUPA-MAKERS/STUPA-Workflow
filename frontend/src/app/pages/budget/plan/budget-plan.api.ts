import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { skipLoading } from '@stupa-makers/ui-kit';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';

/** The side of a Kostenstelle in a Haushaltsplan. */
export type Side = 'income' | 'expense';

/** The state of a plan version, in the order a version passes them. */
export type PlanState = 'draft' | 'in_progress' | 'in_force' | 'replaced';

/** A state a person asks for: into force, or back to the draft. */
export type PlanTarget = 'draft' | 'in_force';

/** One step of a budget or of a version. A version keeps the time it passed the step. */
export interface PlanStep {
  readonly name: string;
  readonly gremiumId: Uuid | null;
  readonly gremiumName?: string | null;
  readonly passedAt?: string | null;
  /** The vote of the Gremium on this step. A deleted vote leaves the id without a status. */
  readonly voteId?: Uuid | null;
  readonly voteStatus?: 'draft' | 'open' | 'closed' | 'cancelled' | null;
  readonly voteResult?: string | null;
}

/** The steps of a top-level Kostenstelle. */
export interface PlanSteps {
  readonly budgetId: Uuid;
  readonly steps: readonly PlanStep[];
}

/** The body that creates a Kostenstelle and its line in a draft. */
export interface PlanNodeCreate {
  readonly parentId: Uuid;
  readonly key: string;
  readonly name: string;
  readonly side: Side | null;
  readonly amount: string;
}

/** One line of a plan version. Money is a string (Decimal). */
export interface PlanLine {
  readonly budgetId: Uuid;
  readonly amount: string;
  readonly note: string | null;
  /** The name and the path key at the decision. `null` in a draft. */
  readonly name: string | null;
  readonly pathKey: string | null;
  readonly transferable: boolean;
  readonly coverable: boolean;
  readonly blocked: string;
}

/** One version of a Haushaltsplan: the Stammplan (number 0) or a Nachtrag. */
export interface PlanVersion {
  readonly id: Uuid;
  readonly number: number;
  readonly state: PlanState;
  readonly createdAt: string;
  readonly inForceAt: string | null;
  /** The steps of the version. A draft shows the steps of its budget. */
  readonly steps: readonly PlanStep[];
  readonly lines: readonly PlanLine[];
}

/** The Haushaltsplan of a fiscal year with every version, the Stammplan first. */
export interface BudgetPlan {
  readonly id: Uuid;
  readonly budgetId: Uuid;
  readonly fiscalYearId: Uuid;
  readonly versions: readonly PlanVersion[];
}

/** The body of a line write. A field the body leaves out keeps the value of the line. */
export interface PlanLineSet {
  readonly amount?: string;
  readonly note?: string | null;
  readonly transferable?: boolean;
  readonly coverable?: boolean;
  readonly blocked?: string;
}

/** One allocation that the Stammplan of the plan switch changes. Money is a string. */
export interface PlanSwitchChange {
  readonly fiscalYearId: Uuid;
  readonly year: string;
  readonly budgetId: Uuid;
  readonly pathKey: string;
  readonly name: string;
  readonly allocated: string;
  readonly planned: string;
}

/** What the plan switch changes when it goes on. */
export interface PlanSwitchPreview {
  readonly budgetId: Uuid;
  readonly changes: readonly PlanSwitchChange[];
}

/** The problem code of a plan read for a year without a plan (404). */
export const PLAN_NOT_FOUND = 'plan_not_found';

/** The routes of the Haushaltsplan. A write needs `budget.structure`. */
@Injectable({ providedIn: 'root' })
export class BudgetPlanApi {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  /** The plan of a fiscal year. A year without a plan answers 404 `plan_not_found`. */
  plan(topId: Uuid, fiscalYearId: Uuid): Observable<BudgetPlan> {
    return this.http.get<BudgetPlan>(this.planUrl(topId, fiscalYearId), { context: skipLoading() });
  }

  /** The plan that holds a version, for the link from the vote of a step. */
  planOfVersion(versionId: Uuid): Observable<BudgetPlan> {
    return this.http.get<BudgetPlan>(`${this.versionUrl(versionId)}/plan`, { context: skipLoading() });
  }

  /** Create the plan with a Stammplan in draft, empty or as a copy of another year. */
  createPlan(topId: Uuid, fiscalYearId: Uuid, copyFromFiscalYearId: Uuid | null): Observable<BudgetPlan> {
    return this.http.post<BudgetPlan>(this.planUrl(topId, fiscalYearId), { copyFromFiscalYearId });
  }

  /** Create a Nachtrag as a copy of the version in force. */
  createNachtrag(topId: Uuid, fiscalYearId: Uuid): Observable<BudgetPlan> {
    return this.http.post<BudgetPlan>(`${this.planUrl(topId, fiscalYearId)}/versions`, {});
  }

  setLine(versionId: Uuid, budgetId: Uuid, body: PlanLineSet): Observable<BudgetPlan> {
    return this.http.put<BudgetPlan>(this.lineUrl(versionId, budgetId), body, { context: skipLoading() });
  }

  deleteLine(versionId: Uuid, budgetId: Uuid): Observable<BudgetPlan> {
    return this.http.delete<BudgetPlan>(this.lineUrl(versionId, budgetId));
  }

  setState(versionId: Uuid, state: PlanTarget): Observable<BudgetPlan> {
    return this.http.post<BudgetPlan>(`${this.versionUrl(versionId)}/state`, { state });
  }

  /** Delete a draft version. The plan goes with it when it has no other version. */
  deleteVersion(versionId: Uuid): Observable<void> {
    return this.http.delete<void>(this.versionUrl(versionId));
  }

  /** Record the next step of a version as passed. */
  passNextStep(versionId: Uuid, step: number): Observable<BudgetPlan> {
    return this.http.post<BudgetPlan>(`${this.versionUrl(versionId)}/steps/next`, { step });
  }

  /** Create the draft vote of the Gremium of the next step. */
  createStepVote(versionId: Uuid): Observable<BudgetPlan> {
    return this.http.post<BudgetPlan>(`${this.versionUrl(versionId)}/steps/next/vote`, {});
  }

  /** Create a Kostenstelle and its line in a draft version. */
  createNode(versionId: Uuid, body: PlanNodeCreate): Observable<BudgetPlan> {
    return this.http.post<BudgetPlan>(`${this.versionUrl(versionId)}/cost-centres`, body);
  }

  steps(topId: Uuid): Observable<PlanSteps> {
    return this.http.get<PlanSteps>(`${this.base}/budgets/${topId}/plan-steps`, { context: skipLoading() });
  }

  setSteps(topId: Uuid, steps: readonly Pick<PlanStep, 'name' | 'gremiumId'>[]): Observable<PlanSteps> {
    return this.http.put<PlanSteps>(`${this.base}/budgets/${topId}/plan-steps`, { steps });
  }

  setSide(budgetId: Uuid, side: Side): Observable<unknown> {
    return this.http.put(`${this.base}/budgets/${budgetId}/side`, { side });
  }

  /** The allocations that the Stammplan changes when the plan switch goes on. */
  switchPreview(topId: Uuid, sides: Readonly<Record<string, Side | ''>> = {}): Observable<PlanSwitchPreview> {
    const of = (side: Side): string[] => Object.keys(sides).filter((id) => sides[id] === side);
    return this.http.get<PlanSwitchPreview>(`${this.base}/budgets/${topId}/plan-switch/preview`, {
      context: skipLoading(),
      params: { income: of('income'), expense: of('expense') },
    });
  }

  /** Set the plan switch. `confirmChanges` says that the person saw the changed allocations. */
  setPlanSwitch(topId: Uuid, enabled: boolean, confirmChanges = false): Observable<unknown> {
    return this.http.put(`${this.base}/budgets/${topId}/plan-switch`, { enabled, confirmChanges });
  }

  private planUrl(topId: Uuid, fiscalYearId: Uuid): string {
    return `${this.base}/budgets/${topId}/fiscal-years/${fiscalYearId}/plan`;
  }

  private versionUrl(versionId: Uuid): string {
    return `${this.base}/budget-plan-versions/${versionId}`;
  }

  private lineUrl(versionId: Uuid, budgetId: Uuid): string {
    return `${this.versionUrl(versionId)}/lines/${budgetId}`;
  }
}
