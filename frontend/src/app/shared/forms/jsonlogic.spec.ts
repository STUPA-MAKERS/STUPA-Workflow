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
});
