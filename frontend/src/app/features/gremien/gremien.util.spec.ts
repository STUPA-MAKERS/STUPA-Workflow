import type { GremiumAttendanceMonth, GremiumAttendanceRow } from '@core/api/gremien.service';
import {
  cellStrength,
  cellView,
  clock,
  dayMonth,
  euro,
  fileSlug,
  fullDate,
  isoDay,
  localized,
  monthAverages,
  monthDate,
  monthKey,
  monthLabel,
  oneDecimal,
  parseDay,
  personName,
  presetRange,
  rangeLabel,
  roleRank,
  rowTotals,
  semesterOf,
  shiftMonth,
  sortRows,
  toCsv,
  weekdayDay,
} from './gremien.util';

const MONTHS: GremiumAttendanceMonth[] = [
  { month: '2026-08', meetings: 0 },
  { month: '2026-09', meetings: 2 },
  { month: '2026-10', meetings: 1 },
];

function row(name: string | null, cells: [boolean, number][], id = name ?? 'x'): GremiumAttendanceRow {
  return {
    principalId: id,
    displayName: name,
    roleKey: 'member',
    roleName: { de: 'Mitglied' },
    isSelf: false,
    cells: cells.map(([member, present], i) => ({
      month: MONTHS[i].month,
      member,
      present,
      excused: 0,
      delegated: 0,
    })),
  };
}

describe('gremien.util', () => {
  it('orders the roles as the server does', () => {
    expect(['member', 'kasse', 'manager', 'vorstand', null].map(roleRank)).toEqual([3, 2, 1, 0, 2]);
  });

  it('picks the text of the locale, then German, then any', () => {
    expect(localized({ de: 'Vorstand', en: 'Board' }, 'en')).toBe('Board');
    expect(localized({ de: 'Vorstand' }, 'en')).toBe('Vorstand');
    expect(localized({ fr: 'Bureau' }, 'en')).toBe('Bureau');
    expect(localized({}, 'en', 'x')).toBe('x');
    expect(localized(null, 'de', 'key')).toBe('key');
    expect(localized(undefined, 'de')).toBe('');
  });

  it('counts months', () => {
    expect(monthKey(new Date(2026, 0, 31))).toBe('2026-01');
    expect(monthDate('2026-10').getMonth()).toBe(9);
    expect(shiftMonth('2026-01', -1)).toBe('2025-12');
    expect(shiftMonth('2026-11', 3)).toBe('2027-02');
  });

  it('names months and ranges', () => {
    expect(monthLabel('2026-10', 'de')).toBe('Okt');
    expect(monthLabel('2026-10', 'de', 'long')).toBe('Oktober 2026');
    expect(monthLabel('2026-10', 'en')).toBe('Oct');
    expect(rangeLabel('2026-05', '2026-10', 'de')).toBe('Mai – Okt 2026');
    expect(rangeLabel('2025-11', '2026-04', 'de')).toBe('Nov 2025 – Apr 2026');
    expect(rangeLabel('2026-10', '2026-10', 'de')).toBe('Okt 2026');
  });

  it('gives the months of each preset', () => {
    const oct = new Date(2026, 9, 15);
    expect(presetRange('last6', oct)).toEqual({ from: '2026-05', to: '2026-10' });
    expect(presetRange('last12', oct)).toEqual({ from: '2025-11', to: '2026-10' });
    expect(presetRange('last24', oct)).toEqual({ from: '2024-11', to: '2026-10' });
    expect(presetRange('semester', oct)).toEqual({ from: '2026-10', to: '2027-03' });
    expect(presetRange('prevSemester', oct)).toEqual({ from: '2026-04', to: '2026-09' });
    expect(presetRange('semester', new Date(2026, 5, 1))).toEqual({ from: '2026-04', to: '2026-09' });
    expect(presetRange('semester', new Date(2026, 1, 1))).toEqual({ from: '2025-10', to: '2026-03' });
  });

  it('tells the semester of a range', () => {
    expect(semesterOf({ from: '2026-04', to: '2026-09' })).toEqual({ summer: true, year: 2026 });
    expect(semesterOf({ from: '2025-10', to: '2026-03' })).toEqual({ summer: false, year: 2025 });
    expect(semesterOf({ from: '2026-05', to: '2026-10' })).toBeNull();
    expect(semesterOf({ from: '2026-04', to: '2026-10' })).toBeNull();
  });

  it('shows a cell as not a member, no meeting or counts', () => {
    const cell = { month: '2026-09', member: true, present: 1, excused: 1, delegated: 0 };
    expect(cellView({ ...cell, member: false }, 2).kind).toBe('na');
    expect(cellView(cell, 0).kind).toBe('none');
    expect(cellView(cell, 2)).toEqual({ kind: 'count', share: 0.5, present: 1, held: 2, excused: 1, delegated: 0 });
    expect(cellView({ ...cell, present: 3 }, 2).share).toBe(1);
  });

  it('mixes the accent by the share', () => {
    expect(cellStrength(1)).toBe(100);
    expect(cellStrength(0)).toBe(0);
    expect(cellStrength(0.5)).toBe(45);
  });

  it('sums a row over the months of the membership only', () => {
    const r = row('A', [
      [true, 0],
      [true, 1],
      [false, 0],
    ]);
    expect(rowTotals(r, MONTHS)).toEqual({ present: 1, held: 2, pct: 50 });
    expect(rowTotals(row('B', [[true, 0], [false, 0], [false, 0]]), MONTHS).pct).toBeNull();
    // A cell without a month counts no meeting.
    expect(rowTotals(row('C', [[true, 0], [true, 2], [true, 1]]), MONTHS.slice(0, 2)).held).toBe(2);
  });

  it('names a person', () => {
    expect(personName('  ')).toBe('—');
    expect(personName(null)).toBe('—');
    expect(personName('Mara')).toBe('Mara');
  });

  it('sorts by quota with ties by name, rows without meetings last', () => {
    const full = row('Zoe', [[true, 0], [true, 2], [true, 1]]);
    const half = row('Ben', [[true, 0], [true, 1], [true, 0]]);
    const halfToo = row('Ada', [[true, 0], [true, 1], [true, 0]]);
    const none = row('Cem', [[true, 0], [false, 0], [false, 0]]);
    const noneToo = row(null, [[false, 0], [false, 0], [false, 0]]);
    const rows = [full, none, half, noneToo, halfToo];
    const names = (rs: GremiumAttendanceRow[]) => rs.map((r) => r.displayName);
    expect(names(sortRows(rows, MONTHS, 'quotaAsc', 'de'))).toEqual(['Ada', 'Ben', 'Zoe', 'Cem', null]);
    expect(names(sortRows(rows, MONTHS, 'quotaDesc', 'de'))).toEqual(['Zoe', 'Ada', 'Ben', 'Cem', null]);
    expect(names(sortRows(rows, MONTHS, 'name', 'de'))).toEqual(['Ada', 'Ben', 'Cem', 'Zoe', null]);
    const nameless = row(null, [[true, 0], [true, 1], [true, 0]], 'y');
    expect(names(sortRows([nameless, half, noneToo], MONTHS, 'name', 'de'))).toEqual(['Ben', null, null]);
  });

  it('averages the present members per meeting', () => {
    const rows = [row('A', [[true, 0], [true, 2], [true, 1]]), row('B', [[true, 0], [true, 1], [true, 0]])];
    expect(monthAverages(rows, MONTHS)).toEqual({ months: [null, 1.5, 1], total: 4 / 3 });
    expect(monthAverages([], [{ month: '2026-08', meetings: 0 }])).toEqual({ months: [null], total: null });
    // A row with more cells than months adds nothing beyond the months.
    expect(monthAverages(rows, MONTHS.slice(0, 2)).months).toEqual([null, 1.5]);
    expect(oneDecimal(27, 'de')).toBe('27,0');
    expect(oneDecimal(2.25, 'en')).toBe('2.3');
  });

  it('reads and writes days', () => {
    expect(parseDay(null)).toBeNull();
    expect(parseDay('nope')).toBeNull();
    expect(parseDay('2026-10-20')?.getDate()).toBe(20);
    expect(parseDay('2026-10-20T10:00:00Z')).not.toBeNull();
    expect(dayMonth('2026-10-20', 'de')).toBe('20.10.');
    expect(dayMonth(null, 'de')).toBe('');
    expect(weekdayDay('2026-10-20', 'de')).toBe('Di, 20.10.');
    expect(weekdayDay('', 'de')).toBe('');
    expect(weekdayDay('2026-10-20', 'de', true)).toBe('Di, 20.10.2026');
    expect(fullDate('2025-10-01', 'de')).toBe('01.10.2025');
    expect(fullDate(undefined, 'de')).toBe('');
    expect(clock('18:00:00')).toBe('18:00');
    expect(clock(null)).toBe('');
    expect(isoDay(new Date(2026, 0, 5))).toBe('2026-01-05');
  });

  it('formats an amount in euro', () => {
    const plain = (v: string) => v.replace(/\s/g, ' ');
    expect(plain(euro('2890.00', 'de'))).toBe('2.890,00 €');
    expect(euro(12, 'en')).toBe('€12.00');
    expect(euro(null, 'de')).toBe('');
    expect(euro('', 'de')).toBe('');
    expect(euro('abc', 'de')).toBe('');
  });

  it('writes a CSV for a spreadsheet', () => {
    const csv = toCsv([
      ['Name', 'Wert'],
      ['A;B', '"x"'],
      ['=1+1', null],
      [undefined, 3],
    ]);
    expect(csv).toBe('﻿Name;Wert\r\n"A;B";"""x"""\r\n\'=1+1;\r\n;3\r\n');
  });

  it('makes a file name part', () => {
    expect(fileSlug('Fachschaft Wirtschaft & Recht')).toBe('fachschaft-wirtschaft-recht');
    expect(fileSlug('Ärzte-Ausschuss')).toBe('arzte-ausschuss');
    expect(fileSlug('!!!')).toBe('gremium');
  });
});
