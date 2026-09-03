/**
 * Guard and action builder plus validation for the flow editor.
 *
 * This file mirrors `app/shared/guards.py` (`validate_guard` and
 * `validate_action`). The check stays purely declarative. It uses a whitelist and
 * no `eval`. The backend is authoritative and validates again when it saves the
 * flow version. This client check gives immediate UI feedback. It stops the admin
 * from building a graph that the server rejects.
 */
import { type TranslationKey } from '../../core/i18n/translations';
import {
  ACTION_TYPES,
  type ActionDef,
  COMPARE_OPS,
  GUARD_ACTOR_OPERATORS,
  GUARD_COMBINATORS,
  GUARD_LEAF_OPERATORS,
  type Guard,
  type GuardCombinator,
  type GuardLeafOperator,
  NOTIFY_RECIPIENT_KINDS,
} from './admin.models';

/**
 * A rejected guard or action, named by a translation key.
 *
 * The reason is a key and its parameters, not a sentence. These messages reach an admin in
 * the flow editor, so the caller decides the language; a thrown English string could only
 * be shown as it was written.
 */
export class GuardError extends Error {
  constructor(
    readonly key: TranslationKey,
    readonly params?: Record<string, string | number>,
  ) {
    super(key);
    this.name = 'GuardError';
  }
}

const LEAF_SET = new Set<string>(GUARD_LEAF_OPERATORS);
const ACTOR_SET = new Set<string>(GUARD_ACTOR_OPERATORS);
const COMBINATOR_SET = new Set<string>(GUARD_COMBINATORS);
const ACTION_SET = new Set<string>(ACTION_TYPES);
const COMPARE_OP_SET = new Set<string>(COMPARE_OPS);
const RECIPIENT_SET = new Set<string>(NOTIFY_RECIPIENT_KINDS);

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function children(op: string, value: unknown): Guard[] {
  const list = Array.isArray(value) ? value : [value];
  for (const c of list) {
    if (!isRecord(c)) {
      throw new GuardError('admin.flow.err.guardChildren', { op });
    }
  }
  return list as Guard[];
}

/**
 * Check a guard before a save, like the backend `validate_guard`.
 *
 * A guard must hold exactly one operator. The operator must come from the
 * whitelist. A combinator must have the correct structure. A `compare` must have
 * the correct shape. Automatic transitions pass `allowActorOps=false`. That
 * forbids `roleIs` and `isInCommittee`. An empty or `null` guard sets no gate and
 * passes.
 */
export function validateGuard(guard: Guard | null | undefined, allowActorOps = true): void {
  if (!guard) return;
  const keys = Object.keys(guard);
  if (keys.length !== 1) {
    throw new GuardError('admin.flow.err.guardOneOperator', { ops: keys.join(', ') || '—' });
  }
  const op = keys[0];
  const value = guard[op];

  if (COMBINATOR_SET.has(op)) {
    const kids = children(op, value);
    if (op === 'not' && kids.length !== 1) {
      throw new GuardError('admin.flow.err.guardNotOneChild');
    }
    if ((op === 'and' || op === 'or') && kids.length === 0) {
      throw new GuardError('admin.flow.err.guardNeedsChild', { op });
    }
    for (const c of kids) validateGuard(c, allowActorOps);
    return;
  }

  if (!LEAF_SET.has(op)) {
    throw new GuardError('admin.flow.err.guardUnknownOp', { op });
  }
  if (ACTOR_SET.has(op) && !allowActorOps) {
    throw new GuardError('admin.flow.err.guardActorManualOnly', { op });
  }
  if (op === 'compare') {
    validateCompare(value);
    return;
  }
  // These operators need a non-empty value. The server rejects an empty one.
  if (
    op === 'roleIs' ||
    op === 'isInCommittee' ||
    op === 'applicantRoleIs' ||
    op === 'applicantCommitteeIs' ||
    op === 'applicationTypeIs' ||
    op === 'budgetIs' ||
    op === 'hasField'
  ) {
    if (typeof value !== 'string' || value.trim() === '') {
      throw new GuardError('admin.flow.err.guardNeedsValue', { op });
    }
  }
}

function validateCompare(spec: unknown): void {
  if (!isRecord(spec)) {
    throw new GuardError('admin.flow.err.compareShape');
  }
  const field = spec['field'];
  const op = spec['op'];
  if (typeof field !== 'string' || field.trim() === '') {
    throw new GuardError('admin.flow.err.compareField');
  }
  if (typeof op !== 'string' || !COMPARE_OP_SET.has(op)) {
    throw new GuardError('admin.flow.err.compareUnknownOp', { op: String(op) });
  }
  if (op === 'in' && !Array.isArray(spec['value'])) {
    throw new GuardError('admin.flow.err.compareInList');
  }
}

/** Action check (whitelist type + required fields), like backend `validate_action`. */
export function validateAction(action: ActionDef | null | undefined): void {
  if (!isRecord(action)) {
    throw new GuardError('admin.flow.err.actionShape');
  }
  const type = (action as ActionDef).type;
  if (typeof type !== 'string' || !ACTION_SET.has(type)) {
    throw new GuardError('admin.flow.err.actionUnknownType', { type: String(type) });
  }
  if (type === 'webhook') {
    if (typeof action['webhookId'] !== 'string' || !action['webhookId']) {
      throw new GuardError('admin.flow.err.actionWebhook');
    }
  } else if (type === 'notify') {
    validateRecipients(action['recipients']);
  } else if (type === 'addToNextSession') {
    if (typeof action['gremiumId'] !== 'string' || !action['gremiumId']) {
      throw new GuardError('admin.flow.err.actionGremium');
    }
  } else if (type === 'assignBudget') {
    if (typeof action['budgetId'] !== 'string' || !action['budgetId']) {
      throw new GuardError('admin.flow.err.actionBudget');
    }
  } else if (type === 'assignBudgetFromField') {
    if (typeof action['field'] !== 'string' || !action['field']) {
      throw new GuardError('admin.flow.err.actionField');
    }
  }
}

function validateRecipients(recipients: unknown): void {
  if (!Array.isArray(recipients) || recipients.length === 0) {
    throw new GuardError('admin.flow.err.notifyRecipients');
  }
  for (const r of recipients) {
    if (!isRecord(r) || !RECIPIENT_SET.has(String(r['kind']))) {
      throw new GuardError('admin.flow.err.notifyRecipientInvalid');
    }
    const kind = r['kind'];
    if ((kind === 'gremium' || kind === 'role' || kind === 'email') && !r['ref']) {
      throw new GuardError('admin.flow.err.notifyRecipientValue', { kind: String(kind) });
    }
  }
}

export function isGuardValid(guard: Guard | null | undefined, allowActorOps = true): boolean {
  try {
    validateGuard(guard, allowActorOps);
    return true;
  } catch {
    return false;
  }
}

/** Build a leaf guard, e.g. `buildLeaf('roleIs', 'stupa')` → `{roleIs:'stupa'}`. */
export function buildLeaf(op: GuardLeafOperator, value: unknown): Guard {
  return { [op]: value };
}

/** Build a combinator guard (`and`/`or` with n children, `not` with exactly one). */
export function combine(op: GuardCombinator, kids: Guard[]): Guard {
  return op === 'not' ? { not: kids[0] } : { [op]: kids };
}

/** Human-readable short description of a guard (read-only display). */
export function describeGuard(guard: Guard | null | undefined): string {
  if (!guard) return '—';
  const keys = Object.keys(guard);
  if (keys.length !== 1) return '⚠ invalid';
  const op = keys[0];
  const value = guard[op];
  if (op === 'and' || op === 'or') {
    const kids = (Array.isArray(value) ? value : [value]) as Guard[];
    return kids.map((k) => describeGuard(k)).join(op === 'and' ? ' ∧ ' : ' ∨ ');
  }
  if (op === 'not') return `¬(${describeGuard(value as Guard)})`;
  if (op === 'compare' && isRecord(value)) {
    return `${String(value['field'])} ${String(value['op'])} ${JSON.stringify(value['value'])}`;
  }
  return `${op}: ${JSON.stringify(value)}`;
}
