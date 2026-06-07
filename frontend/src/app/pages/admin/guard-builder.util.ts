/**
 * Guard-/Action-Builder + Validierung (Expert-Modus des Flow-Editors, T-34).
 *
 * Spiegelt `app/shared/guards.py` (`validate_guard`/`validate_action`): rein
 * deklarativ, **Whitelist, kein `eval`**. Das Backend validiert autoritativ beim
 * Speichern der Flow-Version; diese Client-Prüfung gibt sofortiges UI-Feedback,
 * damit der Admin keinen Graphen baut, den der Server ablehnt.
 */
import {
  ACTION_TYPES,
  type ActionDef,
  GUARD_COMBINATORS,
  GUARD_LEAF_OPERATORS,
  type Guard,
  type GuardCombinator,
  type GuardLeafOperator,
  VOTE_RESULTS,
} from './admin.models';

export class GuardError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'GuardError';
  }
}

const LEAF_SET = new Set<string>(GUARD_LEAF_OPERATORS);
const COMBINATOR_SET = new Set<string>(GUARD_COMBINATORS);
const ACTION_SET = new Set<string>(ACTION_TYPES);

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function children(op: string, value: unknown): Guard[] {
  const list = Array.isArray(value) ? value : [value];
  for (const c of list) {
    if (!isRecord(c)) {
      throw new GuardError(`'${op}' children must be guard objects`);
    }
  }
  return list as Guard[];
}

/**
 * Statische Guard-Prüfung (Speicher-Gate, wie Backend `validate_guard`):
 * genau ein Operator, nur Whitelist-Operatoren, korrekte Kombinator-Struktur,
 * gültiger `voteResult`-Wert. Leerer/`null`-Guard ⇒ kein Gate ⇒ ok.
 */
export function validateGuard(guard: Guard | null | undefined): void {
  if (!guard) return;
  const keys = Object.keys(guard);
  if (keys.length !== 1) {
    throw new GuardError(`guard must have exactly one operator, got ${keys.join(',') || '(none)'}`);
  }
  const op = keys[0];
  const value = guard[op];

  if (COMBINATOR_SET.has(op)) {
    const kids = children(op, value);
    if (op === 'not' && kids.length !== 1) {
      throw new GuardError("'not' requires exactly one child guard");
    }
    if ((op === 'and' || op === 'or') && kids.length === 0) {
      throw new GuardError(`'${op}' requires at least one child guard`);
    }
    for (const c of kids) validateGuard(c);
    return;
  }

  if (LEAF_SET.has(op)) {
    if (op === 'voteResult' && !VOTE_RESULTS.includes(String(value))) {
      throw new GuardError(`invalid voteResult value: ${JSON.stringify(value)}`);
    }
    return;
  }

  throw new GuardError(`unknown guard operator: ${op}`);
}

/** Action-Prüfung (Whitelist-Typ), wie Backend `validate_action`. */
export function validateAction(action: ActionDef | null | undefined): void {
  if (!isRecord(action)) {
    throw new GuardError('action must be an object');
  }
  const type = (action as ActionDef).type;
  if (typeof type !== 'string' || !ACTION_SET.has(type)) {
    throw new GuardError(`unknown action type: ${JSON.stringify(type)}`);
  }
}

export function isGuardValid(guard: Guard | null | undefined): boolean {
  try {
    validateGuard(guard);
    return true;
  } catch {
    return false;
  }
}

// --- Builder-Helfer ---------------------------------------------------------

/** Blatt-Guard bauen, z. B. `buildLeaf('roleIs', 'stupa')` → `{roleIs:'stupa'}`. */
export function buildLeaf(op: GuardLeafOperator, value: unknown): Guard {
  return { [op]: value };
}

/** Kombinator-Guard bauen (`and`/`or` mit n Kindern, `not` mit genau einem). */
export function combine(op: GuardCombinator, kids: Guard[]): Guard {
  return op === 'not' ? { not: kids[0] } : { [op]: kids };
}

/**
 * Lesbare Kurzbeschreibung eines Guards (für Simple-Modus / Read-only-Anzeige).
 * Bewusst knapp; keine i18n der Operator-Namen (Expert-Feature).
 */
export function describeGuard(guard: Guard | null | undefined): string {
  if (!guard) return '—';
  const keys = Object.keys(guard);
  if (keys.length !== 1) return '⚠ invalid';
  const op = keys[0];
  const value = guard[op];
  if (op === 'and' || op === 'or') {
    const kids = (Array.isArray(value) ? value : [value]) as Guard[];
    return kids.map(describeGuard).join(op === 'and' ? ' ∧ ' : ' ∨ ');
  }
  if (op === 'not') return `¬(${describeGuard(value as Guard)})`;
  return `${op}: ${JSON.stringify(value)}`;
}
