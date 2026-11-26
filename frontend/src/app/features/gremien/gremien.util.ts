/**
 * Pure helpers of the tab "Gremien": role order and labels, months and ranges, the cells
 * and sums of the attendance matrix, dates and the CSV export.
 *
 * Nothing here reads a service, so the specs call the functions directly.
 */
import type {
  GremiumAttendanceCell,
  GremiumInfo,
  GremiumAttendanceMonth,
  GremiumAttendanceRow,
  LocalizedText,
} from '@core/api/gremien.service';
import { toFormatLocale } from '@core/i18n/i18n.service';
import { monthShort } from '@shared/date-format';
import { resolveI18n } from '@shared/forms/i18n-text';

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

/** The first month of the semester that holds `today`. */
function semesterStart(today: Date): string {
  const m = today.getMonth() + 1;
  const y = today.getFullYear();
  if (m >= 4 && m <= 9) return `${y}-04`;
  return m >= 10 ? `${y}-10` : `${y - 1}-10`;
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
      const current = semesterStart(today);
      const from = preset === 'prevSemester' ? shiftMonth(current, -6) : current;
      return { from, to: shiftMonth(from, 5) };
    }
    default:
      return { from: shiftMonth(now, -5), to: now };
  }
}

/** The first and the last day (`YYYY-MM-DD`) of a range of months. */
export function rangeDays(range: MonthRange): { readonly from: string; readonly to: string } {
  const [year, month] = range.to.split('-').map(Number);
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return { from: `${range.from}-01`, to: `${range.to}-${String(last).padStart(2, '0')}` };
}

/**
 * The semester of a range that starts in April or October: `{ summer, year }` with the
 * year of the start, else null.
 */
export function semesterOf(
  range: MonthRange,
): { readonly summer: boolean; readonly year: number } | null {
  const month = range.from.slice(5);
  if (shiftMonth(range.from, 5) !== range.to || (month !== '04' && month !== '10')) return null;
  return { summer: month === '04', year: Number(range.from.slice(0, 4)) };
}

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
  const counted = row.cells.flatMap((cell, i) =>
    cell.member ? [{ present: cell.present, held: months[i]?.meetings ?? 0 }] : [],
  );
  const present = counted.reduce((n, c) => n + c.present, 0);
  const held = counted.reduce((n, c) => n + c.held, 0);
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
): { readonly months: readonly (number | null)[]; readonly total: number | null } {
  const presents = rows.flatMap((row) => row.cells.map((cell, i) => ({ i, n: cell.present })));
  const sums = months.map((_, i) =>
    presents.filter((p) => p.i === i).reduce((n, p) => n + p.n, 0),
  );
  const meetings = months.reduce((n, m) => n + m.meetings, 0);
  const all = sums.reduce((n, s) => n + s, 0);
  return {
    months: months.map((m, i) => (m.meetings ? sums[i] / m.meetings : null)),
    total: meetings ? all / meetings : null,
  };
}

/** Items that share one key, in their original order. */
export interface ItemGroup<T> {
  readonly key: string;
  /** The first item of the group: it gives the label of the group. */
  readonly first: T;
  readonly items: readonly T[];
}

/** The items grouped by `keyOf`, the groups in the order of their first item. */
export function groupInOrder<T>(
  items: readonly T[],
  keyOf: (item: T) => string,
): readonly ItemGroup<T>[] {
  const keyed = items.map((item) => ({ item, key: keyOf(item) }));
  const keys = [...new Set(keyed.map((k) => k.key))];
  return keys.map((key) => {
    const members = keyed.filter((k) => k.key === key).map((k) => k.item);
    return { key, first: members[0], items: members };
  });
}

/** A number with one decimal in the locale ("27,0"). */
export function oneDecimal(value: number, locale: string): string {
  return new Intl.NumberFormat(toFormatLocale(locale), {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value);
}


/**
 * A CSV text for a spreadsheet: semicolons, CRLF and a byte order mark, so a German
 * spreadsheet opens it with the right columns and umlauts. A cell that starts like a
 * formula gets a leading apostrophe, so the spreadsheet shows it as text.
 */
export function toCsv(rows: readonly (readonly (string | number | null | undefined)[])[]): string {
  const cell = (value: string | number | null | undefined): string => {
    const raw = value === null || value === undefined ? '' : String(value);
    const s = /^[=+\-@\t\r]/.test(raw) ? `'${raw}` : raw;
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

/** The schemes that an Info link may use (spec 001012); the server refuses every other. */
const INFO_SCHEMES = ['https://', 'http://', 'mailto:'] as const;
/** The most links of one Info (spec 001012). */
export const INFO_MAX_LINKS = 30;
/** The longest label of an Info link (spec 001012). */
export const INFO_MAX_LABEL = 80;
/** The longest Info text (spec 001013). */
export const INFO_MAX_TEXT = 20_000;

/** The URL starts with `https://`, `http://` or `mailto:` and has more after it. */
export function infoUrlValid(url: string): boolean {
  const lower = url.trim().toLowerCase();
  return INFO_SCHEMES.some((s) => lower.startsWith(s) && lower.length > s.length);
}

/** The Info has no text and no link. */
export function infoEmpty(info: GremiumInfo): boolean {
  return info.bodyMd.trim() === '' && info.links.length === 0;
}

/**
 * The tab "Info" shows while the Info loads, after a load error, to an editor and when
 * the Info has content. A reader never sees an empty tab (spec 001015).
 */
export function infoTabShown(info: GremiumInfo | null | undefined): boolean {
  return info === undefined || info === null || info.canEdit || !infoEmpty(info);
}

/** The URL as the link list shows it: an e-mail address without `mailto:`, else whole. */
export function infoUrlShown(url: string): string {
  return url.toLowerCase().startsWith('mailto:') ? url.slice('mailto:'.length) : url;
}

/** A team in the tree order of the list, with its level under the shown parent. */
export interface TeamNode<T extends { readonly id: string; readonly parentId: string | null }> {
  readonly team: T;
  readonly depth: number;
}

/**
 * The teams in tree order (spec 003072): each team, then its sub-teams under it, each level
 * in the order of `teams` (by name from the server). A team whose parent is not among
 * `teams` starts a tree of its own at depth 0. A cycle cannot come from the server; a team
 * shows at most once.
 */
export function teamTree<T extends { readonly id: string; readonly parentId: string | null }>(
  teams: readonly T[],
): readonly TeamNode<T>[] {
  const ids = new Set(teams.map((t) => t.id));
  const children = (parent: string): readonly T[] => teams.filter((t) => t.parentId === parent);
  const walk = (team: T, depth: number, seen: ReadonlySet<string>): readonly TeamNode<T>[] =>
    seen.has(team.id)
      ? []
      : [
          { team, depth },
          ...children(team.id).flatMap((c) => walk(c, depth + 1, new Set([...seen, team.id]))),
        ];
  return teams
    .filter((t) => t.parentId === null || !ids.has(t.parentId))
    .flatMap((t) => walk(t, 0, new Set()));
}
