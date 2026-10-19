import { computed } from '@angular/core';
import { expandSet } from './expand-set';

describe('expandSet', () => {
  it('opens and closes each row on its own', () => {
    const s = expandSet<string>();
    expect(s.toggle('a')).toBe(true);
    expect(s.toggle('b')).toBe(true);
    expect(s.has('a') && s.has('b')).toBe(true);
    expect(s.toggle('a')).toBe(false);
    expect(s.has('a')).toBe(false);
    expect([...s.ids()]).toEqual(['b']);
  });

  it('keeps an open row open on open, and clears all rows', () => {
    const s = expandSet<number>();
    s.open(1);
    const before = s.ids();
    s.open(1);
    expect(s.ids()).toBe(before);
    s.open(2);
    expect(s.ids().size).toBe(2);
    s.clear();
    expect(s.ids().size).toBe(0);
  });

  it('is a signal, so a computed follows it', () => {
    const s = expandSet<string>();
    const open = computed(() => s.has('x'));
    expect(open()).toBe(false);
    s.toggle('x');
    expect(open()).toBe(true);
  });
});
