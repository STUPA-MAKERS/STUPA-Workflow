/**
 * Pure helpers of the tab "Gremien": role order and labels, months and ranges, the cells
 * and sums of the attendance matrix, dates and the CSV export.
 *
 * Nothing here reads a service, so the specs call the functions directly.
 */
import type {
  GremiumAttendanceCell,
  GremiumAttendanceMonth,
  GremiumAttendanceRow,
  LocalizedText,
} from '@core/api/gremien.service';
import { toFormatLocale } from '@core/i18n/i18n.service';
import { monthShort } from '@shared/date-format';
import { resolveI18n } from '@shared/forms/i18n-text';

// ------------------------------------------------------------------ roles

/** The fixed roles first, the roles of the gremium between them, as on the server. */
const ROLE_ORDER: Readonly<Record<string, number>> = { vorstand: 0, manager: 1, member: 3 };

/** The sort rank of a role key: Vorstand, Manager, other roles, Mitglied. */
export function roleRank(key: string | null | undefined): number {
  return key && key in ROLE_ORDER ? ROLE_ORDER[key] : 2;
}

/** The text for `locale`, else the German one, else any, else `fallback`. */
export function localized(
  text: LocalizedText | null | undefined,
  locale: string,
  fallback = '',
): string {
  return resolveI18n(text, locale) || fallback;
}

// ------------------------------------------------------------------ months

/** `YYYY-MM` of a date (local time). */
export function monthKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

/** The first day of a month key, in local time. */
export function monthDate(key: string): Date {
  const [y, m] = key.split('-').map(Number);
  return new Date(y, m - 1, 1);
}

/** The month `n` months after `key` (`n` < 0: before it). */
export function shiftMonth(key: string, n: number): string {
  const d = monthDate(key);
  return monthKey(new Date(d.getFullYear(), d.getMonth() + n, 1));
}

/** "Mai – Okt 2026", "Nov 2025 – Apr 2026" or "Okt 2026". */
export function rangeLabel(from: string, to: string, locale: string): string {
  const year = (k: string) => k.slice(0, 4);
  const month = (k: string): string => monthShort(k, toFormatLocale(locale));
  if (from === to) return `${month(from)} ${year(from)}`;
  if (year(from) === year(to)) {
    return `${month(from)} – ${month(to)} ${year(to)}`;
  }
  return `${month(from)} ${year(from)} – ${month(to)} ${year(to)}`;
}

/** The choices of the chip "Zeitraum" of the attendance. */
export type RangePreset = 'last6' | 'last12' | 'last24' | 'semester' | 'prevSemester';

export interface MonthRange {
  readonly from: string;
  readonly to: string;
}

/**
 * The months of a preset at `today`. A semester is the summer semester (April to
 * September) or the winter semester (October to March).
 */
export function presetRange(preset: RangePreset, today: Date): MonthRange {
  const now = monthKey(today);
  switch (preset) {
    case 'last12':
      return { from: shiftMonth(now, -11), to: now };
    case 'last24':
      return { from: shiftMonth(now, -23), to: now };
    case 'semester':
    case 'prevSemester': {
      const m = today.getMonth() + 1;
      const y = today.getFullYear();
      let from: string;
      if (m >= 4 && m <= 9) from = `${y}-04`;
      else from = m >= 10 ? `${y}-10` : `${y - 1}-10`;
      if (preset === 'prevSemester') from = shiftMonth(from, -6);
      return { from, to: shiftMonth(from, 5) };
    }
    default:
      return { from: shiftMonth(now, -5), to: now };
  }
}

/**
 * The semester of a range that starts in April or October: `{ summer, year }` with the
 * year of the start, else null.
 */
export function semesterOf(range: MonthRange): { summer: boolean; year: number } | null {
  const month = range.from.slice(5);
  if (shiftMonth(range.from, 5) !== range.to || (month !== '04' && month !== '10')) return null;
  return { summer: month === '04', year: Number(range.from.slice(0, 4)) };
}

// ------------------------------------------------------------------ attendance

/** How one cell of the matrix shows. */
export interface CellView {
  /** `na`: no member in the month; `none`: no meeting; `count`: the numbers. */
  readonly kind: 'na' | 'none' | 'count';
  readonly present: number;
  readonly held: number;
  readonly excused: number;
  readonly delegated: number;
  /** present / held, 0 to 1. */
  readonly share: number;
}

export function cellView(cell: GremiumAttendanceCell, held: number): CellView {
  const base = {
    present: cell.present,
    held,
    excused: cell.excused,
    delegated: cell.delegated,
  };
  if (!cell.member) return { kind: 'na', share: 0, ...base };
  if (held === 0) return { kind: 'none', share: 0, ...base };
  return { kind: 'count', share: Math.min(1, cell.present / held), ...base };
}

/**
 * The strength of the accent in a cell, in percent: 100 at every meeting, 0 at none,
 * 20 to 70 between. The CSS mixes the accent with surface 3 by this value.
 */
export function cellStrength(share: number): number {
  if (share >= 1) return 100;
  if (share <= 0) return 0;
  return Math.round(20 + 50 * share);
}

export interface RowTotals {
  readonly present: number;
  /** The closed meetings of the months in which the person was a member. */
  readonly held: number;
  /** Rounded percent, or null without a meeting. */
  readonly pct: number | null;
}

/** The sum of a row: only the months with a membership count. */
export function rowTotals(
  row: GremiumAttendanceRow,
  months: readonly GremiumAttendanceMonth[],
): RowTotals {
  let present = 0;
  let held = 0;
  row.cells.forEach((cell, i) => {
    if (!cell.member) return;
    present += cell.present;
    held += months[i]?.meetings ?? 0;
  });
  return { present, held, pct: held ? Math.round((100 * present) / held) : null };
}

/** The chip "Sortierung" of the attendance. */
export type AttendanceSort = 'quotaAsc' | 'quotaDesc' | 'name';

/** The name of a row, or a dash for a person without a name. */
export function personName(name: string | null | undefined): string {
  return name?.trim() || '—';
}

/**
 * The rows in the chosen order. By quota, a row without a meeting goes to the end; the
 * name decides a tie.
 */
export function sortRows(
  rows: readonly GremiumAttendanceRow[],
  months: readonly GremiumAttendanceMonth[],
  sort: AttendanceSort,
  locale: string,
): GremiumAttendanceRow[] {
  // A person without a name goes after the named ones.
  const byName = (a: GremiumAttendanceRow, b: GremiumAttendanceRow) => {
    const na = a.displayName?.trim() ?? '';
    const nb = b.displayName?.trim() ?? '';
    if (!na || !nb) return Number(!na) - Number(!nb);
    return na.localeCompare(nb, locale);
  };
  if (sort === 'name') return [...rows].sort(byName);
  const ratio = new Map(
    rows.map((r) => {
      const t = rowTotals(r, months);
      return [r, t.held ? t.present / t.held : null] as const;
    }),
  );
  const dir = sort === 'quotaAsc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const ra = ratio.get(a) ?? null;
    const rb = ratio.get(b) ?? null;
    if (ra === null || rb === null) {
      if (ra === rb) return byName(a, b);
      return ra === null ? 1 : -1;
    }
    return ra === rb ? byName(a, b) : (ra - rb) * dir;
  });
}

/**
 * "Ø anwesend je Sitzung": per month the present members divided by the meetings, and
 * the same over the range. A month without a meeting gives null.
 */
export function monthAverages(
  rows: readonly GremiumAttendanceRow[],
  months: readonly GremiumAttendanceMonth[],
): { months: (number | null)[]; total: number | null } {
  const sums = months.map(() => 0);
  for (const row of rows) {
    row.cells.forEach((cell, i) => {
      if (i < sums.length) sums[i] += cell.present;
    });
  }
  const meetings = months.reduce((n, m) => n + m.meetings, 0);
  const all = sums.reduce((n, s) => n + s, 0);
  return {
    months: months.map((m, i) => (m.meetings ? sums[i] / m.meetings : null)),
    total: meetings ? all / meetings : null,
  };
}

/** A number with one decimal in the locale ("27,0"). */
export function oneDecimal(value: number, locale: string): string {
  return new Intl.NumberFormat(toFormatLocale(locale), {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value);
}


// ------------------------------------------------------------------ CSV

/**
 * A CSV text for a spreadsheet: semicolons, CRLF and a byte order mark, so a German
 * spreadsheet opens it with the right columns and umlauts. A cell that starts like a
 * formula gets a leading apostrophe, so the spreadsheet shows it as text.
 */
export function toCsv(rows: readonly (readonly (string | number | null | undefined)[])[]): string {
  const cell = (value: string | number | null | undefined): string => {
    let s = value === null || value === undefined ? '' : String(value);
    if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return /[";\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return '﻿' + rows.map((r) => r.map(cell).join(';')).join('\r\n') + '\r\n';
}

/** A file name part of a gremium name: "Fachschaft Informatik" → "fachschaft-informatik". */
export function fileSlug(name: string): string {
  const slug = name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'gremium';
}
