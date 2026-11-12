import type { Uuid } from '@core/api/models';
import type { BudgetTreeNode } from '../budget-tree.api';
import type { PlanLine, PlanState, PlanVersion, Side } from './budget-plan.api';

/** One Kostenstelle of a plan version, ready for the list and the tables. */
export interface PlanRow {
  readonly id: Uuid;
  readonly parentId: Uuid | null;
  readonly name: string;
  readonly pathKey: string;
  readonly side: Side;
  /** 0 for a direct child of the top-level Kostenstelle. */
  readonly depth: number;
  readonly amount: number;
  /** The Ansatz of the version in force, for a Nachtrag. `null` without such a line. */
  readonly base: number | null;
  /** The Ansatz of the year before. `null` when that year has no figure. */
  readonly prev: number | null;
  /** The booked amount of the year before. `null` when there is no year before. */
  readonly actual: number | null;
  readonly note: string;
  readonly transferable: boolean;
  readonly coverable: boolean;
  readonly blocked: number;
  /** A child Kostenstelle has a line in the version, so the Ansatz is at least their sum. */
  readonly hasChildren: boolean;
}

/** What the rows of a version are built from. */
export interface PlanRowSource {
  readonly top: BudgetTreeNode;
  readonly version: PlanVersion;
  /** The version in force, when `version` is a Nachtrag before `in_force`. */
  readonly base: PlanVersion | null;
  /** The version in force of the year before. */
  readonly prev: PlanVersion | null;
  /** The fiscal year before, for the booked amounts. */
  readonly prevFiscalYearId: Uuid | null;
}

/** The states a version passes, in the order of the steps of the plan page. */
export const PLAN_STEPS: readonly PlanState[] = ['draft', 'resolved', 'approved', 'in_force'];

/** The states of a version that is not yet in force. */
const OPEN_STATES: readonly PlanState[] = ['draft', 'resolved', 'approved'];

const lineMap = (version: PlanVersion | null): ReadonlyMap<Uuid, PlanLine> =>
  new Map((version?.lines ?? []).map((l) => [l.budgetId, l] as const));

/** The booked amount of a Kostenstelle in a fiscal year: income for the income side. */
function actualOf(node: BudgetTreeNode, side: Side, fiscalYearId: Uuid | null): number | null {
  const view = node.byFiscalYear.find((a) => a.fiscalYearId === fiscalYearId);
  if (!fiscalYearId) return null;
  return Number(side === 'income' ? (view?.income ?? 0) : (view?.expended ?? 0));
}

/** The rows of a version in tree order. A Kostenstelle without a line is not in the plan. */
export function planRows(source: PlanRowSource): readonly PlanRow[] {
  const lines = lineMap(source.version);
  const base = lineMap(source.base);
  const prev = lineMap(source.prev);
  const rowsOf = (node: BudgetTreeNode, depth: number): readonly PlanRow[] => {
    const line = lines.get(node.id);
    if (!line || !node.side) return [];
    const below = node.children.flatMap((c) => rowsOf(c, depth + 1));
    const row: PlanRow = {
      id: node.id,
      parentId: depth === 0 ? null : node.parentId,
      name: line.name ?? node.name,
      pathKey: line.pathKey ?? node.pathKey,
      side: node.side,
      depth,
      amount: Number(line.amount),
      base: base.has(node.id) ? Number(base.get(node.id)?.amount) : null,
      prev: prev.has(node.id) ? Number(prev.get(node.id)?.amount) : null,
      actual: actualOf(node, node.side, source.prevFiscalYearId),
      note: line.note ?? '',
      transferable: line.transferable,
      coverable: line.coverable,
      blocked: Number(line.blocked),
      hasChildren: below.length > 0,
    };
    return [row, ...below];
  };
  return source.top.children.flatMap((c) => rowsOf(c, 0));
}

/** The sum of the Ansätze of one side, over the direct children of the top level. */
export function sideSum(rows: readonly PlanRow[], side: Side): number {
  return rows.filter((r) => r.depth === 0 && r.side === side).reduce((sum, r) => sum + r.amount, 0);
}

/** Round to cents, so a sum of decimals compares exactly. */
export function cents(value: number): number {
  return Math.round(value * 100);
}

/** The Kostenstellen that can enter the version: no line yet, and the parent is in the plan. */
export function addable(top: BudgetTreeNode, version: PlanVersion): readonly BudgetTreeNode[] {
  const lines = lineMap(version);
  const below = (node: BudgetTreeNode): readonly BudgetTreeNode[] =>
    lines.has(node.id) ? node.children.flatMap(below) : [node];
  return top.children.flatMap(below).filter((n) => !!n.side);
}

/** The ids of the Kostenstellen of a year: those with a line in the version in force. */
export function memberIds(version: PlanVersion | null): ReadonlySet<Uuid> | null {
  return version ? new Set(version.lines.map((l) => l.budgetId)) : null;
}

/** The version in force of a plan, or `null`. */
export function inForce(versions: readonly PlanVersion[]): PlanVersion | null {
  return versions.find((v) => v.state === 'in_force') ?? null;
}

/** The version a person works on: the one before `in_force`, else the one in force. */
export function currentVersion(versions: readonly PlanVersion[]): PlanVersion | null {
  return versions.find((v) => OPEN_STATES.includes(v.state)) ?? inForce(versions) ?? versions.at(-1) ?? null;
}

/** The index of the active step of a version. A version that is or was in force has passed each step. */
export function stepIndex(state: PlanState): number {
  return state === 'in_force' || state === 'replaced' ? PLAN_STEPS.length : PLAN_STEPS.indexOf(state);
}
