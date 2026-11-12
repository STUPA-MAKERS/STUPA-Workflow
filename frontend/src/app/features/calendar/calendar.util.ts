import type { IconName } from '@stupa-makers/ui-kit';
import type { AnswerKey, AppointmentInput, CalendarEntry, EntryKind } from '@core/api/calendar.service';
import type { TranslationKey } from '@core/i18n/translations';
import { dayMonth, isoDay, shortTime, weekdayDate } from '@shared/date-format';
import type { CalendarDay } from './calendar-grid.util';

/** The kinds of the filter "Art". An Event counts to the Termine (§ 000737). */
export type FilterKind = 'meeting' | 'card' | 'appointment' | 'external';
export const FILTER_KINDS: readonly FilterKind[] = ['meeting', 'card', 'appointment', 'external'];

/** The two views of the desktop Kalender. */
export type CalendarView = 'week' | 'month';

/** The key in `localStorage` that keeps the chosen view per browser. */
export const VIEW_STORAGE_KEY = 'ap.calendar.view';

/** The view that this browser chose last, else the month. A blocked storage gives the month. */
export function readStoredView(): CalendarView {
  try {
    return localStorage.getItem(VIEW_STORAGE_KEY) === 'week' ? 'week' : 'month';
  } catch {
    return 'month';
  }
}

/** Keep the chosen view for the next visit. A blocked storage only forgets it. */
export function storeView(view: CalendarView): void {
  try {
    localStorage.setItem(VIEW_STORAGE_KEY, view);
  } catch {
    // Nothing to do: the view is a convenience, not data.
  }
}

/** The kind of the filter that an entry counts to. */
export function filterKind(kind: EntryKind): FilterKind {
  return kind === 'event' ? 'appointment' : kind;
}

const ICONS: Readonly<Record<EntryKind, IconName>> = {
  meeting: 'users',
  card: 'circleok',
  event: 'cal',
  appointment: 'cal',
  external: 'globe',
};

/** The icon of the kind of an entry. */
export function entryIcon(kind: EntryKind): IconName {
  return ICONS[kind];
}

/** The text key of the kind of an entry ("Sitzung", "Karte", "Termin", "Extern"). */
export function kindKey(kind: EntryKind): TranslationKey {
  return `calendar.kind.${filterKind(kind)}`;
}

/**
 * The entries that the filters keep. A picked Gremium keeps only the entries of that
 * Gremium, so an entry without a Gremium shows only when no Gremium is picked (§ 000713).
 */
export function visibleEntries(
  entries: readonly CalendarEntry[],
  kinds: readonly string[],
  gremiumId: string,
): readonly CalendarEntry[] {
  return entries.filter(
    (e) =>
      (kinds.length === 0 || kinds.includes(filterKind(e.kind))) &&
      (gremiumId === '' || e.gremiumIds.includes(gremiumId)),
  );
}

/** The entry takes more than one day. */
export function isSpan(e: CalendarEntry): boolean {
  return e.startsOn !== e.endsOn;
}

/** The entries with this day in their span, in the order of the server (day, then time). */
export function onDay(entries: readonly CalendarEntry[], iso: string): readonly CalendarEntry[] {
  return entries.filter((e) => e.startsOn <= iso && iso <= e.endsOn);
}

/** The entries of one day only, for the cell of the month grid. */
export function singleDay(entries: readonly CalendarEntry[], iso: string): readonly CalendarEntry[] {
  return entries.filter((e) => e.startsOn === iso && e.endsOn === iso);
}

/** An entry over several days as one bar across the days of a week. */
export interface Bar {
  readonly entry: CalendarEntry;
  /** The grid line where the bar starts (1 to 7) and the line after its end (2 to 8). */
  readonly from: number;
  readonly to: number;
  readonly lane: number;
  /** The entry starts before or ends after this week. */
  readonly openStart: boolean;
  readonly openEnd: boolean;
}

/**
 * The bars of a week. Each bar takes the first lane that is free from its start, so two
 * entries that do not overlap share a lane.
 */
export function weekBars(entries: readonly CalendarEntry[], week: readonly CalendarDay[]): readonly Bar[] {
  const first = week[0].iso;
  const last = week[week.length - 1].iso;
  const column = (iso: string): number => week.findIndex((d) => d.iso === iso);
  const spans = entries
    .filter((e) => isSpan(e) && e.startsOn <= last && e.endsOn >= first)
    .map((e) => ({
      entry: e,
      from: (e.startsOn < first ? 0 : column(e.startsOn)) + 1,
      to: (e.endsOn > last ? week.length - 1 : column(e.endsOn)) + 2,
      openStart: e.startsOn < first,
      openEnd: e.endsOn > last,
    }));
  return spans.reduce<readonly Bar[]>((placed, span) => {
    const taken = new Set(placed.filter((b) => b.from < span.to && span.from < b.to).map((b) => b.lane));
    const lane = Array.from({ length: placed.length + 1 }, (_, i) => i).find((i) => !taken.has(i)) ?? 0;
    return [...placed, { ...span, lane }];
  }, []);
}

/** The number of lanes that the bars of a week take. */
export function laneCount(bars: readonly Bar[]): number {
  return bars.reduce((max, b) => Math.max(max, b.lane + 1), 0);
}

/** The entry is a block in the hour grid: it has a start time (§ 000744). */
export function isTimed(e: CalendarEntry): boolean {
  return e.startTime !== null;
}

/** The entries of a day for the row above the hours (§ 000728). */
export function allDayOf(entries: readonly CalendarEntry[], iso: string): readonly CalendarEntry[] {
  return onDay(entries, iso).filter((e) => !isTimed(e));
}

/** A clock time `HH:MM[:SS]` as hours with a fraction. */
export function hoursOf(clock: string): number {
  return Number(clock.slice(0, 2)) + Number(clock.slice(3, 5)) / 60;
}

/** The shortest block, in hours: a 5 minute Termin still shows its start time. */
export const MIN_BLOCK = 0.4;
/** A block below this length shows its time and its title in one line. */
export const SHORT_BLOCK = 0.75;
/**
 * A block that starts this many hours after the block to its left may cover it: the time
 * and the first line of the title of the earlier block stay free (§ 000745).
 */
export const OVERLAP_HEAD = 0.75;
/** A block that lies on another starts this many percent of the column after it. */
export const OVERLAP_INDENT = 20;
/** The height of an hour in the week view, in rem. It matches `--cw-hour` of the styles. */
export const HOUR_REM = 3.5;

/** A timed entry on one day as a block of the week view. `top` and `height` are hours. */
export interface Block {
  readonly entry: CalendarEntry;
  readonly top: number;
  readonly height: number;
  /** The start and the width of the block in percent of the day column. */
  readonly left: number;
  readonly width: number;
  /** The lane of the block. A block of a higher lane lies above the blocks to its left. */
  readonly lane: number;
  /** The block covers a part of a block to its left (§ 000745). */
  readonly over: boolean;
  readonly short: boolean;
  /** The lines of the title that fit below the time. */
  readonly lines: number;
  /** The clock time where the entry starts or ends on this day, or null where it goes on. */
  readonly start: string | null;
  readonly end: string | null;
}

/** The hour where the part of an entry on the day `iso` ends. */
function partEnd(e: CalendarEntry, iso: string, from: number, lastHour: number): number {
  if (e.endsOn !== iso) return lastHour;
  if (e.endTime) return Math.max(hoursOf(e.endTime), from);
  return isSpan(e) ? lastHour : from + 1;
}

/**
 * The blocks of a day. An entry over several days has one block on each of its days: from
 * its start time to the last hour, the whole day, and from the first hour to its end time
 * (§ 000744). Entries that overlap take lanes: each takes the first lane that is free at
 * its start, and a chain of overlapping blocks divides the column by its number of lanes.
 * A block grows to the right over the lanes that are free. A block whose neighbour to the
 * right starts `OVERLAP_HEAD` later reaches to the end of the column below that neighbour,
 * so the later block lies on the earlier one (§ 000745). A block that starts that much
 * later than every block to its left starts `OVERLAP_INDENT` after them, not at its lane,
 * so it keeps most of the width. Two blocks that start together stay side by side,
 * because the one above would hide the title of the other.
 */
export function dayBlocks(
  entries: readonly CalendarEntry[],
  iso: string,
  firstHour: number,
  lastHour: number,
): readonly Block[] {
  const items = [
    ...onDay(entries, iso)
      .filter(isTimed)
      .map((e) => {
        const from = e.startsOn === iso ? hoursOf(e.startTime ?? '') : firstHour;
        const real = partEnd(e, iso, from, lastHour) - from;
        return { entry: e, from, real, to: from + Math.max(real, MIN_BLOCK) };
      }),
  ].sort((a, b) => a.from - b.from || b.to - a.to);
  const placed = items.reduce<readonly ((typeof items)[number] & { readonly lane: number })[]>((done, item) => {
    const taken = new Set(done.filter((o) => o.to > item.from).map((o) => o.lane));
    const lane = Array.from({ length: done.length + 1 }, (_, i) => i).find((i) => !taken.has(i)) ?? 0;
    return [...done, { ...item, lane }];
  }, []);
  type Placed = (typeof placed)[number];
  const meets = (a: Placed, b: Placed): boolean => a.from < b.to && b.from < a.to;
  const cluster = (seed: readonly Placed[]): readonly Placed[] => {
    const more = placed.filter((o) => !seed.includes(o) && seed.some((s) => meets(o, s)));
    return more.length > 0 ? cluster([...seed, ...more]) : seed;
  };
  const lanesOf = (item: Placed): number => Math.max(...cluster([item]).map((o) => o.lane)) + 1;
  const lefts = placed.reduce<readonly { readonly item: Placed; readonly left: number }[]>((done, item) => {
    const lower = placed.filter((o) => o.lane < item.lane && meets(o, item));
    const own = (item.lane / lanesOf(item)) * 100;
    const onTop = lower.length > 0 && lower.every((o) => item.from >= o.from + OVERLAP_HEAD);
    const below = Math.max(0, ...done.filter((d) => lower.includes(d.item)).map((d) => d.left));
    return [...done, { item, left: onTop ? Math.min(own, below + OVERLAP_INDENT) : own }];
  }, []);
  const boxes = lefts.map(({ item, left }) => {
    const lanes = lanesOf(item);
    const right = placed.filter((o) => o.lane > item.lane && meets(o, item));
    const next = Math.min(lanes, ...right.map((o) => o.lane));
    const under = right.length > 0 && right.every((o) => o.lane > next || o.from >= item.from + OVERLAP_HEAD);
    return { item, left, width: under ? 100 - left : (next * 100) / lanes - left };
  });
  return boxes.map(({ item, left, width }) => {
    const height = Math.max(item.real, MIN_BLOCK);
    return {
      entry: item.entry,
      top: item.from - firstHour,
      height,
      left,
      width,
      lane: item.lane,
      over: boxes.some(
        (o) => o.left < left && o.left + o.width > left + 0.01 && meets(o.item, item),
      ),
      short: item.real < SHORT_BLOCK,
      lines: Math.max(1, Math.floor((height * HOUR_REM * 16 - 28) / 16)),
      start: item.entry.startsOn === iso ? item.entry.startTime : null,
      end: item.entry.endsOn === iso ? item.entry.endTime : null,
    };
  });
}

/** The week view shows the whole day, 00:00 to 24:00 (§ 000746). */
export const DAY_HOURS = 24;
/** The hour at the top of the week view when it opens. */
export const OPEN_HOUR = 8;

/**
 * The hour at the top of the week view when it opens: 08:00, or the hour of the first
 * timed entry that starts on one of the days when that is earlier, so no entry of the
 * week hides above the view.
 */
export function openHour(entries: readonly CalendarEntry[], days: readonly string[]): number {
  const starts = entries
    .filter((e) => isTimed(e) && days.includes(e.startsOn))
    .map((e) => Math.floor(hoursOf(e.startTime ?? '')));
  return Math.min(OPEN_HOUR, ...starts);
}

/**
 * The time of an entry beside its kind: "14:00 – 15:30", "14:00", or "17.11. – 19.11."
 * for an entry over several days. A card and an all-day entry of one day show no time.
 */
export function entryTime(e: CalendarEntry, locale: string): string {
  if (isSpan(e)) return `${dayMonth(e.startsOn, locale)} – ${dayMonth(e.endsOn, locale)}`;
  if (e.startTime === null) return '';
  return e.endTime ? `${shortTime(e.startTime)} – ${shortTime(e.endTime)}` : shortTime(e.startTime);
}

/** The days with entries from `from` to `to`, each with its entries, for the phone list. */
export function dayList(
  entries: readonly CalendarEntry[],
  days: readonly string[],
): readonly { readonly iso: string; readonly items: readonly CalendarEntry[] }[] {
  return days.map((iso) => ({ iso, items: onDay(entries, iso) })).filter((day) => day.items.length > 0);
}

/** The entries of two reads as one list without doubles, in the order of the day. */
export function mergeEntries(
  have: readonly CalendarEntry[],
  more: readonly CalendarEntry[],
): readonly CalendarEntry[] {
  const key = (e: CalendarEntry): string => `${e.kind}:${e.id}`;
  const fresh = new Set(more.map(key));
  return [...have.filter((e) => !fresh.has(key(e))), ...more].sort(
    (a, b) =>
      a.startsOn.localeCompare(b.startsOn) ||
      (a.startTime ?? '').localeCompare(b.startTime ?? '') ||
      a.title.localeCompare(b.title),
  );
}

/** The route that an entry opens, or null for a Termin and an external entry (a dialog). */
export function entryLink(
  e: CalendarEntry,
): { readonly commands: readonly string[]; readonly queryParams?: Readonly<Record<string, string>> } | null {
  switch (e.kind) {
    case 'meeting':
      return { commands: ['/meetings', e.id] };
    case 'card':
    case 'event':
      return { commands: ['/todos'], queryParams: { card: e.id } };
    case 'appointment':
    case 'external':
      return null;
  }
}

/** The form of the Termin dialog. The times are `HH:MM`, and empty for an all-day Termin. */
export interface AppointmentForm {
  readonly title: string;
  readonly allDay: boolean;
  readonly startsOn: string;
  readonly endsOn: string;
  readonly startTime: string;
  readonly endTime: string;
  readonly place: string;
  readonly description: string;
  readonly forAll: boolean;
  readonly public: boolean;
}

/** A new Termin on `day`: all-day, one day. */
export function emptyForm(day: string): AppointmentForm {
  return {
    title: '',
    allDay: true,
    startsOn: day,
    endsOn: day,
    startTime: '09:00',
    endTime: '10:00',
    place: '',
    description: '',
    forAll: false,
    public: false,
  };
}

/** The reason why a form cannot be saved, or null. */
export type FormError = 'title' | 'days' | 'times';

export function formError(form: AppointmentForm): FormError | null {
  if (!form.title.trim()) return 'title';
  if (!form.startsOn || !form.endsOn || form.endsOn < form.startsOn) return 'days';
  if (form.allDay) return null;
  if (!form.startTime || !form.endTime) return 'times';
  return form.endsOn === form.startsOn && form.endTime <= form.startTime ? 'times' : null;
}

/** The request body of a form with its invitations. */
export function toInput(
  form: AppointmentForm,
  gremiumIds: readonly string[],
  principalIds: readonly string[],
): AppointmentInput {
  return {
    title: form.title.trim(),
    startsOn: form.startsOn,
    endsOn: form.endsOn,
    startTime: form.allDay ? null : `${shortTime(form.startTime)}:00`,
    endTime: form.allDay ? null : `${shortTime(form.endTime)}:00`,
    place: form.place.trim() || null,
    description: form.description.trim() || null,
    forAll: form.forAll,
    public: form.public,
    gremiumIds,
    principalIds,
  };
}

/** The span of an entry or of a Termin. */
export interface Spanned {
  readonly startsOn: string;
  readonly endsOn: string;
  readonly startTime: string | null;
  readonly endTime: string | null;
}

/**
 * The whole span as text: "Mi, 11.11.2026 · 14:00 – 15:30" for one day,
 * "Di, 17.11.2026 – Do, 19.11.2026" for several days, with the times at the days of a
 * timed span. An all-day span of one day is the day alone.
 */
export function spanText(a: Spanned, locale: string): string {
  const start = weekdayDate(a.startsOn, locale);
  const from = a.startTime ? shortTime(a.startTime) : '';
  const to = a.endTime ? shortTime(a.endTime) : '';
  if (a.startsOn === a.endsOn) return [start, [from, to].filter(Boolean).join(' – ')].filter(Boolean).join(' · ');
  const end = weekdayDate(a.endsOn, locale);
  return `${[start, from].filter(Boolean).join(', ')} – ${[end, to].filter(Boolean).join(', ')}`;
}

/** The span is over. An all-day span ends with its last day. */
export function hasEnded(a: Spanned, now: Date): boolean {
  const today = isoDay(now);
  const clock = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  return a.endsOn < today || (a.endsOn === today && a.endTime !== null && shortTime(a.endTime) <= clock);
}

/** The text key of an answer. */
export function answerKey(answer: AnswerKey): TranslationKey {
  return `calendar.answer.${answer}`;
}

/** The status look of an answer. */
export function answerKind(answer: AnswerKey): 'accent' | 'warn' | 'muted' {
  switch (answer) {
    case 'accept':
      return 'accent';
    case 'tentative':
      return 'warn';
    case 'decline':
      return 'muted';
  }
}

/** The entry of the grid that stands for a Termin, so a save shows without a second read. */
export function entryOf(a: Spanned & { readonly id: string; readonly title: string; readonly place: string | null },
  gremien: readonly { readonly id: string; readonly name: string }[],
  myAnswer: AnswerKey | null,
): CalendarEntry {
  return {
    kind: 'appointment',
    id: a.id,
    title: a.title,
    startsOn: a.startsOn,
    endsOn: a.endsOn,
    startTime: a.startTime,
    endTime: a.endTime,
    place: a.place,
    source: gremien[0]?.name ?? null,
    gremiumIds: gremien.map((g) => g.id),
    mine: true,
    myAnswer,
  };
}

/** A day cell of the month grid with the entries that fit. */
export interface MonthCell {
  readonly day: CalendarDay;
  /** The entries of this day alone that the cell shows. */
  readonly shown: readonly CalendarEntry[];
  /** The number of entries of this day alone that do not fit ("+2 weitere"). */
  readonly more: number;
  /** The number of all entries on this day, for a screen reader. */
  readonly count: number;
}

/** A week of the month grid with its bars. */
export interface MonthRow {
  readonly key: string;
  readonly bars: readonly Bar[];
  readonly lanes: number;
  readonly cells: readonly MonthCell[];
}

/** A cell has room for this many lines: bars above, then entries of the day. */
export const CELL_ROOM = 2;

/** The weeks of the month grid. Each bar lane takes the room of one entry of the day. */
export function monthRows(
  entries: readonly CalendarEntry[],
  weeks: readonly (readonly CalendarDay[])[],
): readonly MonthRow[] {
  return weeks.map((week) => {
    const bars = weekBars(entries, week);
    const lanes = laneCount(bars);
    const room = Math.max(0, CELL_ROOM - lanes);
    return {
      key: week[0].iso,
      bars,
      lanes,
      cells: week.map((day) => {
        const own = singleDay(entries, day.iso);
        return {
          day,
          shown: own.slice(0, room),
          more: Math.max(0, own.length - room),
          count: onDay(entries, day.iso).length,
        };
      }),
    };
  });
}

/** The days from `from` to `to`, both included. */
export function daysBetween(from: string, to: string): readonly string[] {
  const start = Date.parse(`${from}T00:00:00Z`);
  const count = Math.max(0, Math.round((Date.parse(`${to}T00:00:00Z`) - start) / 86_400_000) + 1);
  return Array.from({ length: count }, (_, i) => new Date(start + i * 86_400_000).toISOString().slice(0, 10));
}

/** A range of days of one request. The server takes at most 100 days. */
export interface DayRange {
  readonly from: string;
  readonly to: string;
}

/** The number of days that the phone list loads at once. */
export const LIST_CHUNK = 60;
