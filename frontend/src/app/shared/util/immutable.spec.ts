import { assertNever, toggled, withEntry, withoutKey } from './immutable';

describe('immutable helpers', () => {
  it('toggled adds an absent item and keeps the input', () => {
    const before: ReadonlySet<string> = new Set(['a']);
    const after = toggled(before, 'b');
    expect([...after]).toEqual(['a', 'b']);
    expect([...before]).toEqual(['a']);
  });

  it('toggled removes a present item', () => {
    expect([...toggled(new Set(['a', 'b']), 'a')]).toEqual(['b']);
  });

  it('withEntry sets a key in a new map', () => {
    const before: ReadonlyMap<string, number> = new Map([['a', 1]]);
    const after = withEntry(before, 'a', 2);
    expect(after.get('a')).toBe(2);
    expect(before.get('a')).toBe(1);
  });

  it('withoutKey drops a key from a new record', () => {
    const before = { a: 1, b: 2 };
    expect(withoutKey(before, 'a')).toEqual({ b: 2 });
    expect(before).toEqual({ a: 1, b: 2 });
  });

  it('assertNever throws on a value the types rule out', () => {
    expect(() => assertNever('x' as never)).toThrow('Unexpected value: x');
  });
});
