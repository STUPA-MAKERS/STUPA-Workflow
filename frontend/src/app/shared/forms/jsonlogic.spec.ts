import { evalJsonLogic, isFieldVisible, JsonLogicError } from './jsonlogic';

describe('evalJsonLogic', () => {
  it('returns literals unchanged', () => {
    expect(evalJsonLogic(5)).toBe(5);
    expect(evalJsonLogic('x')).toBe('x');
    expect(evalJsonLogic([1, 2])).toEqual([1, 2]);
    expect(evalJsonLogic(null)).toBeNull();
  });

  it('resolves var paths (dot-path, default, whole ctx)', () => {
    expect(evalJsonLogic({ var: 'a' }, { a: 1 })).toBe(1);
    expect(evalJsonLogic({ var: 'a.b' }, { a: { b: 2 } })).toBe(2);
    expect(evalJsonLogic({ var: ['missing', 9] }, {})).toBe(9);
    expect(evalJsonLogic({ var: '' }, { a: 1 })).toEqual({ a: 1 });
    expect(evalJsonLogic({ var: 'list.1' }, { list: ['a', 'b'] })).toBe('b');
  });

  it('evaluates comparisons and equality', () => {
    expect(evalJsonLogic({ '>': [{ var: 'x' }, 3] }, { x: 5 })).toBe(true);
    expect(evalJsonLogic({ '<=': [2, 2] })).toBe(true);
    expect(evalJsonLogic({ '==': [{ var: 'a' }, 'y'] }, { a: 'y' })).toBe(true);
    expect(evalJsonLogic({ '!=': [1, 2] })).toBe(true);
  });

  it('evaluates boolean operators without short-circuit', () => {
    expect(evalJsonLogic({ and: [true, true] })).toBe(true);
    expect(evalJsonLogic({ or: [false, true] })).toBe(true);
    expect(evalJsonLogic({ not: [false] })).toBe(true);
  });

  it('evaluates arithmetic incl. unary minus and in', () => {
    expect(evalJsonLogic({ '+': [1, 2, 3] })).toBe(6);
    expect(evalJsonLogic({ '*': [2, 3] })).toBe(6);
    expect(evalJsonLogic({ '-': [5, 2] })).toBe(3);
    expect(evalJsonLogic({ '-': [5] })).toBe(-5);
    expect(evalJsonLogic({ '/': [6, 2] })).toBe(3);
    expect(evalJsonLogic({ in: ['a', ['a', 'b']] })).toBe(true);
    expect(evalJsonLogic({ in: ['x', 'taxi'] })).toBe(true);
  });

  it('throws JsonLogicError on unknown operators and bad arity', () => {
    expect(() => evalJsonLogic({ pow: [2, 3] })).toThrow(JsonLogicError);
    expect(() => evalJsonLogic({ '>': [1] })).toThrow(JsonLogicError);
    expect(() => evalJsonLogic({ a: 1, b: 2 })).toThrow(JsonLogicError);
    expect(() => evalJsonLogic({ '/': [1, 0] })).toThrow(/division by zero/);
    expect(() => evalJsonLogic({ '>': ['nope', 1] })).toThrow(/expected a number/);
  });

  it('throws when an object operation has zero keys', () => {
    expect(() => evalJsonLogic({})).toThrow(JsonLogicError);
    expect(() => evalJsonLogic({})).toThrow(/exactly one operator/);
  });

  it('covers every comparison operator (true and false)', () => {
    expect(evalJsonLogic({ '>': [5, 3] })).toBe(true);
    expect(evalJsonLogic({ '>': [3, 5] })).toBe(false);
    expect(evalJsonLogic({ '>=': [5, 5] })).toBe(true);
    expect(evalJsonLogic({ '>=': [4, 5] })).toBe(false);
    expect(evalJsonLogic({ '<': [3, 5] })).toBe(true);
    expect(evalJsonLogic({ '<': [5, 3] })).toBe(false);
    expect(evalJsonLogic({ '<=': [5, 5] })).toBe(true);
    expect(evalJsonLogic({ '<=': [6, 5] })).toBe(false);
    expect(evalJsonLogic({ '==': [1, 2] })).toBe(false);
    expect(evalJsonLogic({ '!=': [1, 1] })).toBe(false);
  });

  it('evaluates and/or to false branches and not on truthy', () => {
    expect(evalJsonLogic({ and: [true, false] })).toBe(false);
    expect(evalJsonLogic({ or: [false, false] })).toBe(false);
    expect(evalJsonLogic({ not: [true] })).toBe(false);
  });

  it('treats a single (non-array) operand as a one-element arg list', () => {
    // asArgs wraps a scalar; `not` requires arity 1 → ok.
    expect(evalJsonLogic({ not: false })).toBe(true);
  });

  it("'in' on a string coerces the needle to a string", () => {
    expect(evalJsonLogic({ in: [1, '0123'] })).toBe(true);
    expect(evalJsonLogic({ in: ['z', ['a', 'b']] })).toBe(false);
  });

  it("throws when 'in' second operand is neither list nor string", () => {
    expect(() => evalJsonLogic({ in: ['a', 5] })).toThrow(/must be a list or string/);
  });

  it("throws on '+' / '*' with zero operands", () => {
    expect(() => evalJsonLogic({ '+': [] })).toThrow(/at least 1 operand/);
    expect(() => evalJsonLogic({ '*': [] })).toThrow(/at least 1 operand/);
  });

  it("multiplies a populated list and throws on '-' with 3 operands", () => {
    expect(evalJsonLogic({ '*': [2, 3, 4] })).toBe(24);
    expect(() => evalJsonLogic({ '-': [1, 2, 3] })).toThrow(/1 \(negate\) or 2 operands/);
  });

  it('rejects a non-string var path', () => {
    expect(() => evalJsonLogic({ var: 5 })).toThrow(/var path must be a string/);
    // first element of an array path is non-string → same guard.
    expect(() => evalJsonLogic({ var: [5, 'fb'] })).toThrow(/var path must be a string/);
  });

  it('resolves var with null/undefined path to the whole ctx', () => {
    expect(evalJsonLogic({ var: null }, { a: 1 })).toEqual({ a: 1 });
    expect(evalJsonLogic({ var: undefined }, { a: 1 })).toEqual({ a: 1 });
    // empty array path → p='' → whole ctx.
    expect(evalJsonLogic({ var: [] }, { a: 1 })).toEqual({ a: 1 });
  });

  it('returns the fallback when a dot path misses (object and array index)', () => {
    expect(evalJsonLogic({ var: ['a.b', 'fb'] }, { a: {} })).toBe('fb');
    // array index out of range → fallback (null default).
    expect(evalJsonLogic({ var: 'list.5' }, { list: ['a'] })).toBeNull();
    // index into a non-array/non-record → fallback.
    expect(evalJsonLogic({ var: 'a.b' }, { a: 'scalar' })).toBeNull();
  });

  it('rejects NaN as not-a-number', () => {
    expect(() => evalJsonLogic({ '>': [Number.NaN, 1] })).toThrow(/expected a number/);
  });
});

describe('isFieldVisible', () => {
  it('is visible when no condition is set', () => {
    expect(isFieldVisible(undefined, {})).toBe(true);
    expect(isFieldVisible(null, {})).toBe(true);
  });

  it('reflects the condition result', () => {
    const cond = { '==': [{ var: 'needs_detail' }, true] };
    expect(isFieldVisible(cond, { needs_detail: true })).toBe(true);
    expect(isFieldVisible(cond, { needs_detail: false })).toBe(false);
  });

  it('is conservatively visible when evaluation errors (backend parity)', () => {
    // `>` on a missing (→ null) var throws → treated as visible, not skipped.
    expect(isFieldVisible({ '>': [{ var: 'y' }, 0] }, {})).toBe(true);
  });

  it('rethrows non-JsonLogicError exceptions (unexpected failures bubble up)', () => {
    // A proxy whose ownKeys trap throws a TypeError — not a JsonLogicError — so
    // isFieldVisible must NOT swallow it.
    const boom = new Proxy(
      {},
      {
        ownKeys() {
          throw new TypeError('boom');
        },
      },
    ) as Record<string, unknown>;
    expect(() => isFieldVisible(boom, {})).toThrow(TypeError);
  });
});
