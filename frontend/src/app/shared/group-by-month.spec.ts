import { groupByMonth } from './group-by-month';

describe('groupByMonth', () => {
  const at = (iso: string | null) => ({ at: iso });

  it('groups runs of rows by their local month, in the order of the rows', () => {
    const rows = [
      at(new Date(2026, 9, 20, 9).toISOString()),
      at(new Date(2026, 9, 1, 9).toISOString()),
      at(new Date(2026, 8, 30, 9).toISOString()),
      at(new Date(2026, 9, 2, 9).toISOString()),
    ];
    const groups = groupByMonth(rows, (r) => r.at, 'de-DE');
    expect(groups.map((g) => [g.key, g.label, g.items.length])).toEqual([
      ['2026-10', 'Oktober 2026', 2],
      ['2026-09', 'September 2026', 1],
      ['2026-10', 'Oktober 2026', 1],
    ]);
    expect(groups[0].items).toEqual([rows[0], rows[1]]);
  });

  it('puts a run of rows without a date into a group of its own', () => {
    const rows = [at('2026-10-02'), at(null), at('kaputt'), at('2026-10-03')];
    const groups = groupByMonth(rows, (r) => r.at, 'en-GB');
    expect(groups.map((g) => [g.key, g.label, g.items.length])).toEqual([
      ['2026-10', 'October 2026', 1],
      ['', '', 2],
      ['2026-10', 'October 2026', 1],
    ]);
    expect(groupByMonth([], (r: { at: string }) => r.at, 'de-DE')).toEqual([]);
  });

  it('groups plain days of the server with utc, a row without a date on its own', () => {
    const rows = ['2026-09-28', '2026-09-01', null, '2026-08-12', '2026-09-03'];
    const groups = groupByMonth(rows, (r) => r, 'de-DE', { utc: true });
    expect(groups.map((g) => [g.key, g.label, g.items.length])).toEqual([
      ['2026-09', 'September 2026', 2],
      ['', '', 1],
      ['2026-08', 'August 2026', 1],
      ['2026-09', 'September 2026', 1],
    ]);
    expect(groupByMonth(['2026-01-02'], (r) => r, 'en-GB', { utc: true })[0].label).toBe(
      'January 2026',
    );
  });

  it('reads the month of the server text with utc', () => {
    const late = '2026-09-30T23:30:00Z';
    expect(groupByMonth([late], (r) => r, 'de-DE', { utc: true })[0]).toEqual({
      key: '2026-09',
      label: 'September 2026',
      items: [late],
    });
    expect(groupByMonth(['2026-13-01', 'x'], (r) => r, 'de-DE', { utc: true })).toEqual([
      { key: '', label: '', items: ['2026-13-01', 'x'] },
    ]);
    const moment = new Date(Date.UTC(2026, 0, 31, 23, 30));
    expect(groupByMonth([moment], (r) => r, 'de-DE', { utc: true })[0].key).toBe('2026-01');
    expect(groupByMonth([null], (r) => r, 'de-DE', { utc: true })[0].key).toBe('');
  });
});
