import type {
  DateAnswer,
  ElectionConfig,
  ElectionFields,
  IsoDateTime,
  PollConfig,
  PollIn,
  PollMode,
  PollOption,
  PollResult,
  VoteStatus,
} from '@core/api/models';
import type { Translate } from '@core/i18n/translations';
import type { StatusView } from '@shared/status-kind.util';

/** The bounds of the server (`PollConfig`). */
export const POLL_MIN_OPTIONS = 2;
export const POLL_MAX_OPTIONS = 20;
export const POLL_LABEL_MAX = 200;

/** The three answers of a date poll, in the order of the buttons. */
export const DATE_ANSWERS: readonly DateAnswer[] = ['yes', 'maybe', 'no'];

/** The abstention key of the counts of a single or multi poll. */
export const POLL_ABSTAIN = 'abstain';

/** The poll of a vote, or `null` for a motion and an election. */
export function pollOf(vote: ElectionFields | null | undefined): PollConfig | null {
  if (!vote || vote.kind !== 'poll') return null;
  return vote.poll ?? null;
}

/** The most options of one ballot: 1 (single), `maxChoices` or every option (multi). */
export function pollChoiceLimit(poll: PollConfig): number {
  if (poll.mode === 'single') return 1;
  return poll.maxChoices ?? poll.options.length;
}

/**
 * A single or multi poll as an election ballot: the options are the candidates and the
 * choice limit is the seats. The ballot reuses the candidate rows of an election (F2).
 */
export function pollAsElection(poll: PollConfig): ElectionConfig {
  return {
    seats: pollChoiceLimit(poll),
    candidates: poll.options.map((o) => ({ id: o.id, name: o.label ?? o.id })),
    secret: poll.secret,
  };
}

/** The time zone of the meetings. A date option shows in it, as the protocol writes it. */
export const POLL_TZ = 'Europe/Berlin';
const WEEKDAYS_DE = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];

/** The parts of an instant in the time zone of the meetings. */
function berlinParts(iso: IsoDateTime): Record<string, string> {
  return Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', {
      timeZone: POLL_TZ,
      weekday: 'short',
      day: 'numeric',
      month: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(new Date(iso))
      .map((p) => [p.type, p.value]),
  );
}

/**
 * "Di, 3.11. · 18:00–20:00": the label of a date option in the time zone of the meetings.
 * The protocol snippet (`pollSnippet`) and the backend write the same text, so a card and
 * the protocol show the same date. A locale other than German names the weekday in it.
 */
export function dateOptionLabel(
  start: IsoDateTime,
  end: IsoDateTime | null | undefined,
  locale: string,
): string {
  const s = berlinParts(start);
  const index = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(s['weekday'] ?? '');
  const weekday = locale.startsWith('de')
    ? (WEEKDAYS_DE[index] ?? '')
    : new Intl.DateTimeFormat(locale, { timeZone: POLL_TZ, weekday: 'short' }).format(new Date(start));
  let text = `${weekday}, ${Number(s['day'])}.${Number(s['month'])}. · ${s['hour']}:${s['minute']}`;
  if (end) {
    const e = berlinParts(end);
    text += `–${e['hour']}:${e['minute']}`;
  }
  return text;
}

/** The label of a poll option: its text, or its date. */
export function pollOptionLabel(option: PollOption, locale: string): string {
  if (option.start) return dateOptionLabel(option.start, option.end, locale);
  return option.label ?? option.id;
}

/** The label of an option id, or the id when the poll does not know it. */
export function pollLabelOf(poll: PollConfig | null, id: string, locale: string): string {
  const option = poll?.options.find((o) => o.id === id);
  return option ? pollOptionLabel(option, locale) : id;
}

/** "Umfrage · Einzelwahl", "Umfrage · Mehrfachwahl, höchstens 2", "Terminumfrage". */
export function pollCaption(poll: PollConfig, t: Translate): string {
  if (poll.mode === 'date') return t('poll.mode.date');
  if (poll.mode === 'single') return t('poll.caption', { mode: t('poll.mode.single') });
  const mode =
    poll.maxChoices != null
      ? t('poll.mode.multiMax', { n: poll.maxChoices })
      : t('poll.mode.multi');
  return t('poll.caption', { mode });
}

/** The label of a single or multi poll ballot: "A, B", or "Enthaltung". */
export function pollChoiceLabel(
  poll: PollConfig | null,
  picks: readonly string[],
  locale: string,
  t: Translate,
): string {
  if (picks.length === 0) return t('vote.option.abstain');
  return picks.map((id) => pollLabelOf(poll, id, locale)).join(', ');
}

/** "1 Option", "2 Optionen", or "Enthaltung" (no option). */
export function pollCountText(n: number, t: Translate): string {
  if (n === 0) return t('vote.option.abstain');
  return n === 1 ? t('poll.options.one') : t('poll.options.other', { n });
}

/** Every date of the poll has an answer. */
export function answersComplete(
  poll: PollConfig,
  answers: Readonly<Record<string, DateAnswer>> | null | undefined,
): boolean {
  return !!answers && poll.options.every((o) => answers[o.id] !== undefined);
}

/** The status of a poll in a list or a card: "Umfrage offen", "Umfrage beendet". */
export function pollStatus(status: VoteStatus | string): StatusView | null {
  if (status === 'open') return { kind: 'accent', key: 'poll.status.open' };
  if (status === 'closed') return { kind: 'accent', key: 'poll.status.closed' };
  return null;
}

/** One row of a poll result. */
export interface PollBar {
  id: string;
  label: string;
  /** The votes; a date poll: the Ja answers. */
  count: number;
  /** A date poll: the Vielleicht answers. `null` otherwise. */
  maybe: number | null;
  /** "meiste Stimmen" / "bester Termin". */
  top: boolean;
}

/**
 * The rows of a poll result, highest first (the order of the server), then the
 * abstentions of a single or multi poll. Without a stored result the rows come from
 * the revealed counts, ranked by votes.
 */
export function pollBars(
  poll: PollConfig,
  result: PollResult | null,
  counts: Readonly<Record<string, number>>,
  locale: string,
  t: Translate,
): PollBar[] {
  const date = poll.mode === 'date';
  const ids = poll.options.map((o) => o.id);
  const source = result?.counts ?? counts;
  let order = (result?.order ?? []).filter((id) => ids.includes(id));
  if (order.length !== ids.length) {
    order = [...ids].sort((a, b) => (source[b] ?? 0) - (source[a] ?? 0));
  }
  const top = new Set(result?.top ?? topOf(order, source));
  const rows: PollBar[] = order.map((id) => ({
    id,
    label: pollLabelOf(poll, id, locale),
    count: source[id] ?? 0,
    maybe: date ? (result?.maybe?.[id] ?? 0) : null,
    top: top.has(id),
  }));
  if (date) return rows;
  const abstain = result?.abstentions ?? counts[POLL_ABSTAIN] ?? 0;
  return [
    ...rows,
    { id: POLL_ABSTAIN, label: t('election.abstentionsLabel'), count: abstain, maybe: null, top: false },
  ];
}

/** The options with the most votes, none while no option has a vote. */
function topOf(order: readonly string[], counts: Readonly<Record<string, number>>): string[] {
  const most = Math.max(0, ...order.map((id) => counts[id] ?? 0));
  return most > 0 ? order.filter((id) => (counts[id] ?? 0) === most) : [];
}

/** "Meiste Stimmen: A, B" or "Bester Termin: Di, 03.11. · 18:00", or `null` (no vote). */
export function pollTopLine(poll: PollConfig, bars: readonly PollBar[], t: Translate): string | null {
  const names = bars.filter((b) => b.top).map((b) => b.label);
  if (names.length === 0) return null;
  const key = poll.mode === 'date' ? 'poll.result.bestDate' : 'poll.result.most';
  return t(key, { names: names.join(', ') });
}

// ------------------------------------------------------------------ the editor

/** One option in the editor: a text, or a date with a start and an optional end. */
export interface PollOptionDraft {
  /** A local key for the list; the server gives the ids. */
  key: number;
  label: string;
  /** `YYYY-MM-DD`, `HH:MM`, `HH:MM` or `''` (date mode). */
  date: string;
  start: string;
  end: string;
}

/** The poll as the editor holds it. */
export interface PollDraft {
  mode: PollMode;
  /** The stepper "Höchstens wählbar" of a multi poll. */
  maxChoices: number;
  options: PollOptionDraft[];
}

export function emptyPollDraft(): PollDraft {
  return { mode: 'single', maxChoices: 2, options: [] };
}

/** A local `YYYY-MM-DD` and `HH:MM` as an ISO moment, or `null`. */
export function localMoment(date: string, time: string): IsoDateTime | null {
  if (!date || !time) return null;
  const at = new Date(`${date}T${time}`);
  return Number.isNaN(at.getTime()) ? null : at.toISOString();
}

/** The options of the current mode: the texts, or the dates. */
export function draftOptions(draft: PollDraft): PollOptionDraft[] {
  const date = draft.mode === 'date';
  return draft.options.filter((o) => (date ? !!o.date && !!o.start : !!o.label.trim()));
}

/** The draft fits the server rules: 2 to 20 options of the mode. */
export function pollDraftValid(draft: PollDraft): boolean {
  const n = draftOptions(draft).length;
  return n >= POLL_MIN_OPTIONS && n <= POLL_MAX_OPTIONS;
}

/** The body of the poll (`PollIn`) from the draft. */
export function pollInOf(draft: PollDraft): PollIn {
  const options = draftOptions(draft).map((o) => {
    if (draft.mode !== 'date') return { label: o.label.trim() };
    const start = localMoment(o.date, o.start)!;
    const end = o.end ? localMoment(o.date, o.end) : null;
    return end ? { start, end } : { start };
  });
  return {
    mode: draft.mode,
    options,
    ...(draft.mode === 'multi'
      ? { maxChoices: Math.min(draft.maxChoices, Math.max(1, options.length)) }
      : {}),
  };
}

/**
 * The label of a date option in the editor list: the day and the times as typed, in the
 * form of `dateOptionLabel`.
 */
export function draftDateLabel(o: PollOptionDraft, locale: string): string {
  const start = localMoment(o.date, o.start);
  if (!start) return o.date;
  const day = new Date(`${o.date}T12:00:00Z`);
  const weekday = locale.startsWith('de')
    ? (WEEKDAYS_DE[day.getUTCDay()] ?? '')
    : new Intl.DateTimeFormat(locale, { timeZone: 'UTC', weekday: 'short' }).format(day);
  const head = `${weekday}, ${day.getUTCDate()}.${day.getUTCMonth() + 1}. · ${o.start}`;
  return o.end ? `${head}–${o.end}` : head;
}
