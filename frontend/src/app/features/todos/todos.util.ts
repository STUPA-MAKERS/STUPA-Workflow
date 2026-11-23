import type { PersonRef, Uuid } from '@core/api/models';
import type {
  TodoBoardSummary,
  TodoEvent,
  TodoLabelColor,
  TodoLink,
  TodoLinkDetail,
  TodoLinkKind,
  TodoLinkTarget,
  TodoVoteResult,
  TodoVoteStatus,
} from '@core/api/todos.service';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import { formatMoney } from '@shared/format-money';
import { dayMonth, dayMonthYear, daysUntil, parseDay, shortDay, weekdayDate, weekdayName } from '@shared/date-format';
import { resolveI18n } from '@shared/forms/i18n-text';
import type { IconName } from '@stupa-makers/ui-kit';
import { personName } from '@shared/person-label.util';
import { assertNever } from '@shared/util/immutable';

/** The fixed label palette of the server, in the order of the settings dialog. */
export const LABEL_COLORS: readonly TodoLabelColor[] = ['green', 'blue', 'violet', 'amber', 'red', 'gray'];

export const LABEL_COLOR_NAME: Record<TodoLabelColor, TranslationKey> = {
  green: 'todos.color.green',
  blue: 'todos.color.blue',
  violet: 'todos.color.violet',
  amber: 'todos.color.amber',
  red: 'todos.color.red',
  gray: 'todos.color.gray',
};

export const LINK_ICON: Record<TodoLinkKind, IconName> = {
  application: 'file',
  meeting: 'users',
  agenda_item: 'list',
  vote: 'vote',
  appointment: 'cal',
  gremium: 'landmark',
  invoice: 'receipt',
  expense: 'swap',
  budget: 'pie',
  ticket: 'chat',
  todo: 'circleok',
};

export const LINK_KIND_LABEL: Record<TodoLinkKind, TranslationKey> = {
  application: 'todos.linkKind.application',
  meeting: 'todos.linkKind.meeting',
  agenda_item: 'todos.linkKind.agenda_item',
  vote: 'todos.linkKind.vote',
  appointment: 'todos.linkKind.appointment',
  gremium: 'todos.linkKind.gremium',
  invoice: 'todos.linkKind.invoice',
  expense: 'todos.linkKind.expense',
  budget: 'todos.linkKind.budget',
  ticket: 'todos.linkKind.ticket',
  todo: 'todos.linkKind.todo',
};

/** The state of a vote link: the result once closed, else the status. */
export const VOTE_STATUS_LABEL: Record<TodoVoteStatus, TranslationKey> = {
  draft: 'voting.list.status.draft',
  open: 'meetings.voteStatus.open',
  closed: 'meetings.voteStatus.closed',
  cancelled: 'meetings.voteStatus.cancelled',
};

export const VOTE_RESULT_LABEL: Record<TodoVoteResult, TranslationKey> = {
  passed: 'vote.result.passed',
  rejected: 'vote.result.rejected',
  tie: 'vote.result.tie',
  elected: 'vote.result.elected',
  runoff: 'vote.result.runoff',
  no_majority: 'vote.result.no_majority',
};

export const TICKET_STATUS_LABEL: Record<string, TranslationKey> = {
  new: 'tickets.status.new',
  in_progress: 'tickets.status.in_progress',
  waiting: 'tickets.status.waiting',
  done: 'tickets.status.done',
  rejected: 'tickets.status.rejected',
};

/** The colour of a due date: overdue red, today and tomorrow amber. */
export type DueTone = 'overdue' | 'soon' | 'normal';

export interface DueInfo {
  /** "14.10." */
  readonly date: string;
  /** "überfällig", "heute", "morgen" or null. */
  readonly note: string | null;
  readonly tone: DueTone;
}

/**
 * The due date of a tile: the short date, and a note while it presses. A card in the
 * done column has no note and no colour.
 */
export function dueInfo(day: string, today: string, locale: string, t: Translate, done = false): DueInfo {
  const date = shortDay(day, locale, today) || day;
  const n = daysUntil(day, today);
  if (done || n === null || n > 1) return { date, note: null, tone: 'normal' };
  if (n < 0) return { date, note: t('todos.due.overdue'), tone: 'overdue' };
  return { date, note: t(n === 0 ? 'todos.due.today' : 'todos.due.tomorrow'), tone: 'soon' };
}

/** "in 19 Tagen", "heute", "morgen", "gestern", "vor 3 Tagen". */
export function relativeDays(day: string, today: string, t: Translate): string {
  const n = daysUntil(day, today);
  switch (n) {
    case null:
      return '';
    case 0:
      return t('todos.due.today');
    case 1:
      return t('todos.due.tomorrow');
    case -1:
      return t('todos.due.yesterday');
    default:
      return n > 0 ? t('todos.due.inDays', { n }) : t('todos.due.daysAgo', { n: -n });
  }
}

/** The title of a link, or "<Kind> (kein Zugriff)". */
export function linkTitle(link: Pick<TodoLink, 'kind' | 'accessible' | 'title'>, t: Translate): string {
  if (!link.accessible || !link.title) {
    return t('todos.link.noAccess', { kind: t(LINK_KIND_LABEL[link.kind]) });
  }
  return link.title;
}

/** A part of a link line that is present: neither null nor undefined. */
const isPart = (part: string | null | undefined): part is string =>
  part !== null && part !== undefined;

/** The TOP position of an agenda item, unless the title already starts with it. */
function topPart(position: number | null | undefined, title: string, t: Translate): string | null {
  const top = position ? t('todos.link.top', { n: position }) : null;
  return top && !title.startsWith(`${top}:`) && title !== top ? top : null;
}

/** A number of a link (invoice, ticket), unless the title already starts with it. */
const numberPart = (num: string | null | undefined, title: string): string | null =>
  num && !title.startsWith(num) ? num : null;

/** The facts of a link of `kind` after its kind label; a falsy entry is left out. */
function linkFacts(
  kind: TodoLinkKind,
  d: TodoLinkDetail,
  title: string,
  locale: string,
  lang: string,
  t: Translate,
): readonly (string | null | undefined)[] {
  switch (kind) {
    case 'application':
      return [d.stateLabel ? resolveI18n(d.stateLabel, lang) : null];
    case 'meeting':
      return [d.date ? weekdayDate(d.date, locale) : null];
    case 'agenda_item':
      return [d.meetingTitle, topPart(d.position, title, t)];
    case 'vote': {
      const status = d.voteStatus ? t(VOTE_STATUS_LABEL[d.voteStatus]) : null;
      return [d.meetingTitle, d.voteResult ? t(VOTE_RESULT_LABEL[d.voteResult]) : status];
    }
    case 'appointment':
      return [d.date ? weekdayDate(d.date, locale) : null, d.startTime ? d.startTime.slice(0, 5) : null, d.place];
    case 'invoice': {
      const counterparty = d.counterparty !== title ? d.counterparty : null;
      const date = d.date ? weekdayDate(d.date, locale) : null;
      const amount = d.amount ? formatMoney(d.amount, locale) : date;
      return [numberPart(d.number, title), counterparty, amount];
    }
    case 'expense':
      return [d.costCentre, d.amount ? formatMoney(d.amount, locale) : null];
    case 'budget':
      return [d.costCentre];
    case 'ticket':
      return [
        numberPart(d.number, title),
        d.status ? t(TICKET_STATUS_LABEL[d.status] ?? 'tickets.status.new') : null,
      ];
    case 'todo':
      return [d.boardName, d.columnName];
    case 'gremium':
      return [];
    default:
      return assertNever(kind);
  }
}

/**
 * The facts of a link below its title: "TOP · 33. Sitzung · TOP 2". A number or a TOP
 * position that the title already starts with is not repeated.
 */
export function linkSub(
  link:
    | (Pick<TodoLink, 'kind' | 'detail' | 'accessible'> & { readonly title?: string | null })
    | TodoLinkTarget,
  locale: string,
  lang: string,
  t: Translate,
): string {
  const kind = t(LINK_KIND_LABEL[link.kind]);
  const d = link.detail;
  const hidden = !d || ('accessible' in link && !link.accessible);
  const facts = hidden ? [] : linkFacts(link.kind, d, link.title ?? '', locale, lang, t);
  return hidden ? kind : [kind, ...facts].filter(Boolean).join(' · ');
}

/** The day and weekday of a meeting or agenda item link ("Di, 03.11."), else null. */
function linkDay(link: TodoLink, today: string, locale: string): string | null {
  const day =
    (link.kind === 'meeting' || link.kind === 'agenda_item' || link.kind === 'appointment') && link.detail?.date
      ? parseDay(link.detail.date)
      : null;
  return day ? `${weekdayName(day, locale)}, ${shortDay(day, locale, today)}` : null;
}

/** The link line of a tile: "Sitzung · Sondersitzung Haushalt 2027 · Di, 03.11.". */
export function linkLine(link: TodoLink, today: string, locale: string, t: Translate): string {
  const kind = t(LINK_KIND_LABEL[link.kind]);
  const number = link.kind === 'ticket' && link.detail?.number ? link.detail.number : null;
  const money = link.kind === 'invoice' || link.kind === 'expense';
  const amount = money && link.detail?.amount ? formatMoney(link.detail.amount, locale) : null;
  return !link.accessible || !link.title
    ? linkTitle(link, t)
    : [kind, number, link.title, amount, linkDay(link, today, locale)].filter(isPart).join(' · ');
}

/** The text of an event in the activity ("Selin Yıldız hat die Karte … verschoben"). */
export function eventText(event: TodoEvent, locale: string, t: Translate): string {
  const actor = event.actor ? personName(event.actor, t) : t('todos.event.system');
  const p = event.payload as Record<string, unknown>;
  const str = (v: unknown): string => (typeof v === 'string' ? v : '');
  switch (event.kind) {
    case 'created':
      return t('todos.event.created', { actor });
    case 'moved':
      if (p['toBoardName'] !== undefined) {
        return t('todos.event.movedBoard', { actor, from: str(p['fromBoardName']), to: str(p['toBoardName']) });
      }
      return t('todos.event.moved', { actor, from: str(p['fromColumnName']), to: str(p['toColumnName']) });
    case 'assigned': {
      const person = (p['person'] ?? null) as PersonRef | null;
      const name = personName(person, t);
      const self = !!event.actor?.principalId && person?.principalId === event.actor.principalId;
      if (p['added']) return self ? t('todos.event.took', { actor }) : t('todos.event.assigned', { actor, name });
      return t('todos.event.unassigned', { actor, name });
    }
    case 'due': {
      const to = str(p['to']);
      return to
        ? t('todos.event.due', { actor, date: weekdayDate(to, locale) })
        : t('todos.event.dueCleared', { actor });
    }
    case 'linked':
    case 'unlinked': {
      const kind = (p['linkKind'] as TodoLinkKind) ?? 'application';
      const title = str(p['title']);
      const target = title
        ? `${t(LINK_KIND_LABEL[kind] ?? 'todos.linkKind.application')} ${title}`
        : t('todos.link.noAccess', { kind: t(LINK_KIND_LABEL[kind] ?? 'todos.linkKind.application') });
      return t(event.kind === 'linked' ? 'todos.event.linked' : 'todos.event.unlinked', { actor, target });
    }
    case 'checklist': {
      const text = str(p['text']);
      const key: Record<string, TranslationKey> = {
        added: 'todos.event.checkAdded',
        done: 'todos.event.checkDone',
        undone: 'todos.event.checkUndone',
        removed: 'todos.event.checkRemoved',
        renamed: 'todos.event.checkRenamed',
      };
      return t(key[str(p['action'])] ?? 'todos.event.checkAdded', { actor, text });
    }
    case 'renamed':
      return t('todos.event.renamed', { actor, title: str(p['to']) });
    case 'archived':
      return event.actor ? t('todos.event.archived', { actor }) : t('todos.event.archivedAuto');
    case 'restored':
      return t('todos.event.restored', { actor });
  }
}

export {
  DROP_ENTER,
  NO_FILTER,
  applyMove,
  canTransfer,
  cardsOf,
  dropEnter,
  dropMove,
  filterActive,
  insertAt,
  insertTile,
  matchesFilter,
  moveRequest,
  placeTile,
  removeTile,
  replaceTile,
  sheetMove,
  sortedColumns,
  withHeld,
  type BoardFilter,
  type TileBoard,
} from '@stupa-makers/ui-kit/views/board';

/** The error codes of a refused move or transfer that have a text of their own. */
const MOVE_ERROR_TEXT: Record<string, TranslationKey> = {
  card_moved: 'todos.error.transfer',
  transfer_to_personal: 'todos.error.transferToPersonal',
  todo_write_required: 'todos.error.readOnly',
  board_archived: 'todos.error.archived',
};

/** The toast text of a refused move or transfer: its code's text, else `fallback`. */
export function moveErrorText(err: unknown, fallback: TranslationKey): TranslationKey {
  const body = (err as { error?: unknown } | null)?.error;
  const code = typeof body === 'object' && body !== null ? (body as { code?: unknown }).code : undefined;
  return (typeof code === 'string' && MOVE_ERROR_TEXT[code]) || fallback;
}

/**
 * The board `/todos` opens without a board in the URL: the personal board "Meine To-Dos", else
 * the board of the caller's first own gremium by name. An admin also lists the boards of gremien
 * they do not belong to, so a gremium board outside `ownGremiumIds` comes only after the boards
 * of the own gremien.
 */
export function defaultBoard(
  boards: readonly TodoBoardSummary[],
  ownGremiumIds: readonly Uuid[] = [],
): TodoBoardSummary | null {
  return (
    boards.find((b) => b.kind === 'personal') ??
    boards.find((b) => b.kind === 'gremium' && b.gremiumId !== null && ownGremiumIds.includes(b.gremiumId)) ??
    boards.find((b) => b.kind === 'gremium') ??
    boards[0] ??
    null
  );
}

/** An app route of a link ("/meetings/m-1?item=a-1") as router path and query. */
export function splitUrl(url: string): {
  readonly path: string;
  readonly query: Readonly<Record<string, string>>;
} {
  const [path, search = ''] = url.split('?');
  const query = Object.fromEntries(new URLSearchParams(search));
  return { path, query };
}

/**
 * The dates of an Event: "20.11.2026", or "20.11.–21.11.2026" when it lasts several days
 * ("30.12.2026–02.01.2027" across a year). Null without a start.
 */
export function eventDays(start: string | null, end: string | null, locale: string): string | null {
  if (!start) return null;
  if (!end || end === start) return dayMonthYear(start, locale);
  if (start.slice(0, 4) === end.slice(0, 4)) return `${dayMonth(start, locale)}–${dayMonthYear(end, locale)}`;
  return `${dayMonthYear(start, locale)}–${dayMonthYear(end, locale)}`;
}
