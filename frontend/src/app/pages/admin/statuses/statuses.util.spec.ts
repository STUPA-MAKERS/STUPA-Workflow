import { keyOf, moveRow, newRow, rowKeys } from './statuses.util';

describe('statuses.util', () => {
  it('makes a free key of a name', () => {
    expect(keyOf('Zurückgegeben', new Set())).toBe('zurueckgegeben');
    expect(keyOf('In Planung!', new Set(['in_planung']))).toBe('in_planung_2');
    expect(keyOf('2. Mahnung', new Set())).toBe('mahnung');
    expect(keyOf('—', new Set())).toBe('status');
    expect(keyOf('x'.repeat(60), new Set()).length).toBeLessThanOrEqual(40);
  });

  /** A new row never takes the key of a stored status, also not of a removed one. */
  it('keeps the stored keys and gives new rows a free key', () => {
    const fresh = { ...newRow(), name: { de: 'Storniert' } };
    const stored = [{ key: 'cancelled', name: { de: 'Storniert' }, tone: 'muted' as const, phase: 'void' as const, start: false }];
    expect(rowKeys([fresh, fresh], 'de', [{ ...stored[0], key: 'storniert' }])).toEqual(['storniert_2', 'storniert_3']);
    const rows = [fresh, { ...fresh, key: 'a', fresh: false }];
    expect(moveRow(rows, 1, -1)).toEqual([rows[1], rows[0]]);
    expect(moveRow(rows, 0, -1)).toBe(rows);
  });
});
