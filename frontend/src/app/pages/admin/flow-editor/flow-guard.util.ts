/** Guard/action read helpers shared by the flow editor and its child components. */
import type {
  ActionDef,
  Guard,
  GuardLeafOperator,
  NotifyRecipient,
  TransitionDef,
} from '../admin.models';
import type { GuardGroup, Point } from './flow-editor.models';

/**
 * Group outgoing transitions by guard, in array (= priority) order.
 * Branch transitions (pass/fail of a vote state) are excluded — they have
 * their own dots and no guard priority.
 */
export function groupsOf(transitions: readonly TransitionDef[], fromKey: string): GuardGroup[] {
  const bySig = new Map<string, GuardGroup>();
  const order: GuardGroup[] = [];
  transitions.forEach((t, index) => {
    if (t.from !== fromKey || t.branch) return;
    const sig = t.guard ? JSON.stringify(t.guard) : '';
    let g = bySig.get(sig);
    if (!g) {
      g = {
        sig,
        guard: t.guard ?? null,
        op: t.guard ? Object.keys(t.guard)[0] : '',
        value: t.guard ? String(Object.values(t.guard)[0] ?? '') : '',
        indices: [],
      };
      bySig.set(sig, g);
      order.push(g);
    }
    g.indices.push(index);
  });
  return order;
}

/**
 * Connector dots of a normal node: one per guard group, plus a default
 * (catch-all) dot for drawing new guard-less edges if none exists.
 */
export function outDots(fromKey: string, transitions: readonly TransitionDef[]): GuardGroup[] {
  const groups = groupsOf(transitions, fromKey);
  if (!groups.some((g) => g.sig === '')) {
    groups.push({ sig: '', guard: null, op: '', value: '', indices: [] });
  }
  return groups;
}

export function branchDotsFor(kind: string | null | undefined): string[] {
  return kind === 'vote' ? ['pass', 'fail'] : [];
}

/**
 * Sort branch dots by average target y: without this, "pass" pointing down
 * and "fail" pointing up would cross right in front of the node.
 */
export function sortedBranchDots(
  fromKey: string,
  kind: string | null | undefined,
  transitions: readonly TransitionDef[],
  pos: Record<string, Point>,
): string[] {
  const branches = branchDotsFor(kind);
  if (branches.length < 2) return branches;
  const avgTargetY = (branch: string): number | null => {
    const ys = transitions
      .filter((t) => t.from === fromKey && t.branch === branch && pos[t.to])
      .map((t) => pos[t.to].y);
    return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : null;
  };
  return [...branches].sort((a, b) => {
    const ya = avgTargetY(a);
    const yb = avgTargetY(b);
    if (ya == null || yb == null) return 0;
    return ya - yb;
  });
}

export function guardOpOf(t: TransitionDef): string {
  return t.guard ? Object.keys(t.guard)[0] : '';
}

export function guardValueOf(t: TransitionDef): string {
  if (!t.guard) return '';
  const v = Object.values(t.guard)[0];
  return v == null || typeof v === 'object' ? '' : String(v);
}

export function guardBoolOf(t: TransitionDef): boolean {
  return !!(t.guard && Object.values(t.guard)[0] === true);
}

export function compareSpecOf(t: TransitionDef): { field: string; op: string; value: unknown } {
  const c = t.guard?.['compare'];
  return typeof c === 'object' && c !== null
    ? (c as { field: string; op: string; value: unknown })
    : { field: '', op: '==', value: '' };
}

export function defaultGuard(op: GuardLeafOperator): Guard {
  if (op === 'deadlinePassed' || op === 'budgetFitsApplication') return { [op]: true };
  if (op === 'compare') return { compare: { field: '', op: '==', value: '' } };
  return { [op]: '' };
}

/**
 * Value-control kind per guard operator:
 * - `none`      → boolean operators (deadlinePassed/budgetFitsApplication)
 * - `role`      → roleIs/applicantRoleIs → global-role dropdown
 * - `committee` → isInCommittee/applicantCommitteeIs → gremium dropdown
 * - `compare`   → typed comparison (field + operator + value)
 * - `text`      → budgetIs/hasField → free text
 */
export function guardValueKind(op: string): 'none' | 'role' | 'committee' | 'compare' | 'text' {
  if (op === 'deadlinePassed' || op === 'budgetFitsApplication' || !op) return 'none';
  if (op === 'roleIs' || op === 'applicantRoleIs') return 'role';
  if (op === 'isInCommittee' || op === 'applicantCommitteeIs') return 'committee';
  if (op === 'compare') return 'compare';
  return 'text';
}

export function recipientsOf(act: ActionDef): NotifyRecipient[] {
  return Array.isArray(act['recipients']) ? (act['recipients'] as NotifyRecipient[]) : [];
}

export function actionParamOf(act: ActionDef, key: string): string {
  const v = act[key];
  return typeof v === 'string' ? v : '';
}

/** Does the recipient kind need a `ref` (gremium/role/email)? */
export function recipientNeedsRef(kind: string): boolean {
  return kind === 'gremium' || kind === 'role' || kind === 'email';
}
