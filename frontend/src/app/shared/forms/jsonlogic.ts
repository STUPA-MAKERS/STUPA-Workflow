/**
 * FE-Port des JsonLogic-Subsets (Backend `app/shared/jsonlogic.py`, data-model
 * §5.1 / flows §9.2). `visibleIf`/`compute` in Form-Feldern nutzen dieses Subset.
 *
 * **Kein `eval`** — deklarativer Baum, Whitelist-Operatoren. Semantik spiegelt das
 * Backend (Single Source of Truth bleibt der Server, der autoritativ re-validiert):
 * - Literal (kein Objekt) → unverändert zurück.
 * - Operation = Objekt mit **genau einem** Schlüssel = Operator.
 * - `and`/`or` werten **nicht** kurzschließend aus (alle Operanden evaluiert) —
 *   identisch zum Backend-Verhalten.
 *
 * Whitelist: `== != > >= < <= and or not var + - * / in`.
 */

export class JsonLogicError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'JsonLogicError';
  }
}

export type JsonLogicExpr = unknown;

const OPERATORS = new Set([
  '==',
  '!=',
  '>',
  '>=',
  '<',
  '<=',
  'and',
  'or',
  'not',
  'var',
  '+',
  '-',
  '*',
  '/',
  'in',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asArgs(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [value];
}

function resolveVar(path: unknown, ctx: Record<string, unknown>): unknown {
  let p = path;
  let fallback: unknown = null;
  if (Array.isArray(p)) {
    fallback = p.length > 1 ? p[1] : null;
    p = p.length > 0 ? p[0] : '';
  }
  if (p === '' || p === null || p === undefined) return ctx;
  if (typeof p !== 'string') {
    throw new JsonLogicError(`var path must be a string, got ${typeof p}`);
  }
  let current: unknown = ctx;
  for (const part of p.split('.')) {
    if (isRecord(current) && part in current) {
      current = current[part];
    } else if (Array.isArray(current) && /^\d+$/.test(part) && Number(part) < current.length) {
      current = current[Number(part)];
    } else {
      return fallback;
    }
  }
  return current;
}

function num(value: unknown): number {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new JsonLogicError(`expected a number, got ${JSON.stringify(value)}`);
  }
  return value;
}

/** Wertet einen JsonLogic-Ausdruck gegen `ctx` aus. Pure, kein Seiteneffekt. */
export function evalJsonLogic(expr: unknown, ctx: Record<string, unknown> = {}): unknown {
  if (!isRecord(expr)) return expr;
  const keys = Object.keys(expr);
  if (keys.length !== 1) {
    throw new JsonLogicError(`operation must have exactly one operator, got ${keys.join(',')}`);
  }
  const op = keys[0];
  const raw = expr[op];
  if (!OPERATORS.has(op)) throw new JsonLogicError(`unknown operator: ${op}`);

  if (op === 'var') return resolveVar(raw, ctx);

  const args = asArgs(raw).map((a) => evalJsonLogic(a, ctx));

  switch (op) {
    case '==':
      requireArity(op, args, 2);
      return args[0] === args[1];
    case '!=':
      requireArity(op, args, 2);
      return args[0] !== args[1];
    case '>':
      requireArity(op, args, 2);
      return num(args[0]) > num(args[1]);
    case '>=':
      requireArity(op, args, 2);
      return num(args[0]) >= num(args[1]);
    case '<':
      requireArity(op, args, 2);
      return num(args[0]) < num(args[1]);
    case '<=':
      requireArity(op, args, 2);
      return num(args[0]) <= num(args[1]);
    case 'and':
      return args.every((a) => Boolean(a));
    case 'or':
      return args.some((a) => Boolean(a));
    case 'not':
      requireArity(op, args, 1);
      return !args[0];
    case '+':
      if (args.length === 0) throw new JsonLogicError("'+' requires at least 1 operand");
      return args.reduce<number>((sum, a) => sum + num(a), 0);
    case '*':
      if (args.length === 0) throw new JsonLogicError("'*' requires at least 1 operand");
      return args.reduce<number>((product, a) => product * num(a), 1);
    case '-':
      if (args.length === 1) return -num(args[0]);
      if (args.length === 2) return num(args[0]) - num(args[1]);
      throw new JsonLogicError("'-' requires 1 (negate) or 2 operands");
    case '/': {
      requireArity(op, args, 2);
      const divisor = num(args[1]);
      if (divisor === 0) throw new JsonLogicError('division by zero');
      return num(args[0]) / divisor;
    }
    case 'in': {
      requireArity(op, args, 2);
      const [needle, haystack] = args;
      if (Array.isArray(haystack)) return haystack.includes(needle);
      if (typeof haystack === 'string') return haystack.includes(String(needle));
      throw new JsonLogicError("'in' second operand must be a list or string");
    }
    default:
      throw new JsonLogicError(`unhandled operator: ${op}`);
  }
}

function requireArity(op: string, args: unknown[], n: number): void {
  if (args.length !== n) {
    throw new JsonLogicError(`'${op}' requires exactly ${n} operand(s)`);
  }
}

/**
 * `visibleIf` auswerten. Kein Ausdruck ⇒ sichtbar. Eval-Fehler ⇒ **konservativ
 * sichtbar** (identisch zum Backend `_is_visible`: lieber validieren als still
 * überspringen).
 */
export function isFieldVisible(
  visibleIf: Record<string, unknown> | null | undefined,
  model: Record<string, unknown>,
): boolean {
  if (visibleIf === null || visibleIf === undefined) return true;
  try {
    return Boolean(evalJsonLogic(visibleIf, model));
  } catch (err) {
    if (err instanceof JsonLogicError) return true;
    throw err;
  }
}
