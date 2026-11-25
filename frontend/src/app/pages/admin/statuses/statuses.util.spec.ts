import { DEFAULT_STATUS_LISTS } from '@core/api/statuses.service';
import {
  draftOf,
  elementsOf,
  keyOf,
  listValid,
  moveRow,
  nameText,
  newRow,
  removeRow,
  removedInUse,
  rowKeys,
  rowOf,
} from './statuses.util';

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
    const stored = [
      {
        key: 'cancelled',
        name: { de: 'Storniert' },
        tone: 'muted' as const,
        phase: 'void' as const,
        start: false,
      },
    ];
    expect(rowKeys([fresh, fresh], 'de', [{ ...stored[0], key: 'storniert' }])).toEqual([
      'storniert_2',
      'storniert_3',
    ]);
    const rows = [fresh, { ...fresh, key: 'a', fresh: false }];
    expect(moveRow(rows, 1, -1)).toEqual([rows[1], rows[0]]);
    expect(moveRow(rows, 0, -1)).toBe(rows);
  });
});

describe('removeRow and elementsOf', () => {
  const stored = DEFAULT_STATUS_LISTS.order.map((s, i) => ({ ...s, used: [2, 0, 1, 3][i] }));
  const list = draftOf(stored);

  it('removes a row and keeps the target of a stored row only', () => {
    const fresh = { ...list, rows: [...list.rows, newRow()] };
    expect(removeRow(fresh, 4, 'planned')).toEqual(list);
    expect(removeRow(list, 3, 'delivered').replacements).toEqual({ cancelled: 'delivered' });
    expect(removeRow(list, 9, 'planned')).toBe(list);
  });

  it('passes the elements of an earlier delete on to the next target', () => {
    const once = removeRow(list, 3, 'delivered');
    expect(elementsOf(once.rows[2], once, stored)).toBe(4);
    expect(removeRow(once, 2, 'ordered').replacements).toEqual({
      cancelled: 'ordered',
      delivered: 'ordered',
    });
    expect(elementsOf(newRow(), once, stored)).toBe(0);
  });
});

describe('the rules of a list', () => {
  const bare = DEFAULT_STATUS_LISTS.event.map(({ key, name, tone, phase, start }) => ({
    key,
    name,
    tone,
    phase,
    start,
  }));

  it('reads a stored status without count or date', () => {
    expect(rowOf(bare[0])).toEqual(
      expect.objectContaining({ used: 0, setsDate: null, fresh: false }),
    );
    expect(removedInUse(bare, [])).toEqual([]);
    expect(
      elementsOf(rowOf(bare[0]), { rows: [], replacements: { settled: 'planned' } }, bare),
    ).toBe(0);
  });

  it('falls back to German, then to nothing', () => {
    expect(nameText({ de: 'Geplant' }, 'en')).toBe('Geplant');
    expect(nameText({}, 'en')).toBe('');
  });

  it('takes the last number when every key is taken', () => {
    const taken = new Set(['x', ...Array.from({ length: 100 }, (_, i) => `x_${i + 1}`)]);
    expect(keyOf('x', taken)).toBe('x_100');
  });

  it('refuses an empty name, an open-less start and a missing replacement', () => {
    const stored = DEFAULT_STATUS_LISTS.event.map((s) => ({ ...s, used: 1 }));
    const list = draftOf(stored);
    expect(listValid(list, stored, 'de')).toBe(true);
    expect(
      listValid(
        { ...list, rows: [{ ...list.rows[0], name: {} }, ...list.rows.slice(1)] },
        stored,
        'de',
      ),
    ).toBe(false);
    expect(listValid({ ...list, rows: [...list.rows.slice(1), list.rows[0]] }, stored, 'de')).toBe(
      false,
    );
    const fewer = {
      ...list,
      rows: [...list.rows, { ...newRow(), name: { de: 'Weg' }, phase: 'void' as const }].filter(
        (r) => r.key !== 'cancelled',
      ),
    };
    expect(listValid(fewer, stored, 'de')).toBe(false);
    expect(listValid({ ...fewer, replacements: { cancelled: 'planned' } }, stored, 'de')).toBe(
      true,
    );
  });
});
