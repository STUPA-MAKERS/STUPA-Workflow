import type { PersonRef, Uuid } from '@core/api/models';
import type {
  TodoBoard,
  TodoBoardSummary,
  TodoCardMove,
  TodoCardTile,
  TodoEvent,
  TodoLabel,
  TodoLabelColor,
  TodoLink,
  TodoLinkKind,
  TodoLinkTarget,
} from '@core/api/todos.service';
import type { TranslationKey } from '@core/i18n/translations';
import { resolveI18n } from '@shared/forms/i18n-text';
import type { IconName } from '@stupa-makers/ui-kit';

/** A translate function: the key and its parameters. */
export type Translate = (key: TranslationKey, params?: Record<string, string | number>) => string;

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
  ticket: 'chat',
  todo: 'circleok',
};

export const LINK_KIND_LABEL: Record<TodoLinkKind, TranslationKey> = {
  application: 'todos.linkKind.application',
  meeting: 'todos.linkKind.meeting',
  agenda_item: 'todos.linkKind.agenda_item',
  ticket: 'todos.linkKind.ticket',
  todo: 'todos.linkKind.todo',
};

/** The kinds of the link picker, in the order of the server answer. */
export const LINK_KINDS: readonly TodoLinkKind[] = ['application', 'meeting', 'agenda_item', 'ticket', 'todo'];

export const TICKET_STATUS_LABEL: Record<string, TranslationKey> = {
  new: 'tickets.status.new',
  in_progress: 'tickets.status.in_progress',
  done: 'tickets.status.done',
  rejected: 'tickets.status.rejected',
};

const DAY_MS = 86_400_000;

/** The local calendar day of a moment as `YYYY-MM-DD`. */
export function isoDay(at: Date): string {
  const m = String(at.getMonth() + 1).padStart(2, '0');
  const d = String(at.getDate()).padStart(2, '0');
  return `${at.getFullYear()}-${m}-${d}`;
}

/** A `YYYY-MM-DD` day as a local date at noon (no DST edge), or null. */
export function parseDay(day: string | null | undefined): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day ?? '');
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12);
}

/** Calendar days from `today` to `day` (negative = past), or null for a bad day. */
export function daysUntil(day: string, today: string): number | null {
  const a = parseDay(today);
  const b = parseDay(day);
  if (!a || !b) return null;
  return Math.round((b.getTime() - a.getTime()) / DAY_MS);
}

/** "14.10." in the current year, else "14.10.2027". */
export function shortDay(day: string, today: string, locale: string): string {
  const d = parseDay(day);
  if (!d) return day;
  const sameYear = day.slice(0, 4) === today.slice(0, 4);
  const text = new Intl.DateTimeFormat(locale, {
    day: '2-digit',
    month: '2-digit',
    ...(sameYear ? {} : { year: 'numeric' }),
  }).format(d);
  // de-DE writes "14.10" without the closing dot of a day without a year.
  return sameYear && locale.startsWith('de') && !text.endsWith('.') ? `${text}.` : text;
}

/** "Di, 03.11.2026". */
export function longDay(day: string, locale: string): string {
  const d = parseDay(day);
  if (!d) return day;
  const weekday = new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(d).replace(/\.$/, '');
  const date = new Intl.DateTimeFormat(locale, { day: '2-digit', month: '2-digit', year: 'numeric' }).format(d);
  return `${weekday}, ${date}`;
}

/** The colour of a due date: overdue red, today and tomorrow amber. */
export type DueTone = 'overdue' | 'soon' | 'normal';

export interface DueInfo {
  /** "14.10." */
  date: string;
  /** "überfällig", "heute", "morgen" or null. */
  note: string | null;
  tone: DueTone;
}

/**
 * The due date of a tile: the short date, and a note while it presses. A card in the
 * done column has no note and no colour.
 */
export function dueInfo(day: string, today: string, locale: string, t: Translate, done = false): DueInfo {
  const date = shortDay(day, today, locale);
  const n = daysUntil(day, today);
  if (done || n === null || n > 1) return { date, note: null, tone: 'normal' };
  if (n < 0) return { date, note: t('todos.due.overdue'), tone: 'overdue' };
  return { date, note: t(n === 0 ? 'todos.due.today' : 'todos.due.tomorrow'), tone: 'soon' };
}

/** "in 19 Tagen", "heute", "morgen", "gestern", "vor 3 Tagen". */
export function relativeDays(day: string, today: string, t: Translate): string {
  const n = daysUntil(day, today);
  if (n === null) return '';
  if (n === 0) return t('todos.due.today');
  if (n === 1) return t('todos.due.tomorrow');
  if (n === -1) return t('todos.due.yesterday');
  return n > 0 ? t('todos.due.inDays', { n }) : t('todos.due.daysAgo', { n: -n });
}

/** A person by name; a deleted one is "Gelöschte Person". */
export function personName(ref: PersonRef | null | undefined, t: Translate): string {
  return ref?.displayName || t('chat.deletedPerson');
}

/** The title of a link, or "<Kind> (kein Zugriff)". */
export function linkTitle(link: Pick<TodoLink, 'kind' | 'accessible' | 'title'>, t: Translate): string {
  if (!link.accessible || !link.title) {
    return t('todos.link.noAccess', { kind: t(LINK_KIND_LABEL[link.kind]) });
  }
  return link.title;
}

/**
 * The facts of a link below its title: "TOP · 33. Sitzung · TOP 2". A number or a TOP
 * position that the title already starts with is not repeated.
 */
export function linkSub(
  link: (Pick<TodoLink, 'kind' | 'detail' | 'accessible'> & { title?: string | null }) | TodoLinkTarget,
  locale: string,
  lang: string,
  t: Translate,
): string {
  const parts = [t(LINK_KIND_LABEL[link.kind])];
  const d = link.detail;
  if (!d || ('accessible' in link && !link.accessible)) return parts[0];
  const title = link.title ?? '';
  switch (link.kind) {
    case 'application':
      if (d.stateLabel) parts.push(resolveI18n(d.stateLabel, lang));
      break;
    case 'meeting':
      if (d.date) parts.push(longDay(d.date, locale));
      break;
    case 'agenda_item':
      if (d.meetingTitle) parts.push(d.meetingTitle);
      if (d.position) {
        const top = t('todos.link.top', { n: d.position });
        if (!title.startsWith(`${top}:`) && title !== top) parts.push(top);
      }
      break;
    case 'ticket':
      if (d.number && !title.startsWith(d.number)) parts.push(d.number);
      if (d.status) parts.push(t(TICKET_STATUS_LABEL[d.status] ?? 'tickets.status.new'));
      break;
    case 'todo':
      if (d.boardName) parts.push(d.boardName);
      if (d.columnName) parts.push(d.columnName);
      break;
  }
  return parts.filter(Boolean).join(' · ');
}

/** The link line of a tile: "Sitzung · Sondersitzung Haushalt 2027 · Di, 03.11.". */
export function linkLine(link: TodoLink, today: string, locale: string, t: Translate): string {
  const kind = t(LINK_KIND_LABEL[link.kind]);
  if (!link.accessible || !link.title) return linkTitle(link, t);
  const parts = [kind];
  if (link.kind === 'ticket' && link.detail?.number) parts.push(link.detail.number);
  parts.push(link.title);
  if ((link.kind === 'meeting' || link.kind === 'agenda_item') && link.detail?.date) {
    const d = parseDay(link.detail.date);
    if (d) {
      const weekday = new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(d).replace(/\.$/, '');
      parts.push(`${weekday}, ${shortDay(link.detail.date, today, locale)}`);
    }
  }
  return parts.join(' · ');
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
        ? t('todos.event.due', { actor, date: longDay(to, locale) })
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

/** The filters of the board and the list view; all run in the browser. */
export interface BoardFilter {
  q: string;
  /** '' all, 'me' my cards, 'none' nobody, else a principal id. */
  assignee: string;
  labels: readonly string[];
  /** '' all, 'overdue', 'week' (within 7 days, overdue included), 'none' without a date. */
  due: '' | 'overdue' | 'week' | 'none';
}

export const NO_FILTER: BoardFilter = { q: '', assignee: '', labels: [], due: '' };

export function filterActive(f: BoardFilter): boolean {
  return !!(f.q.trim() || f.assignee || f.labels.length || f.due);
}

/** Whether a card passes the filters. `mine` holds the ids of the cards assigned to me. */
export function matchesFilter(
  card: TodoCardTile,
  f: BoardFilter,
  ctx: { today: string; mine: ReadonlySet<Uuid>; labels: ReadonlyMap<Uuid, TodoLabel> },
): boolean {
  if (f.assignee === 'me' && !ctx.mine.has(card.id)) return false;
  if (f.assignee === 'none' && card.assignees.length) return false;
  if (f.assignee && f.assignee !== 'me' && f.assignee !== 'none') {
    if (!card.assignees.some((a) => a.principalId === f.assignee)) return false;
  }
  if (f.labels.length && !f.labels.some((id) => card.labelIds.includes(id))) return false;
  if (f.due) {
    const n = card.dueDate ? daysUntil(card.dueDate, ctx.today) : null;
    if (f.due === 'none' && card.dueDate) return false;
    if (f.due === 'overdue' && (n === null || n >= 0)) return false;
    if (f.due === 'week' && (n === null || n > 7)) return false;
  }
  const q = f.q.trim().toLowerCase();
  if (q) {
    const hay = [
      card.title,
      card.primaryLink?.title ?? '',
      ...card.labelIds.map((id) => ctx.labels.get(id)?.name ?? ''),
      ...card.assignees.map((a) => a.displayName ?? ''),
    ]
      .join(' ')
      .toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

/** The columns by position. */
export function sortedColumns<T extends { position: number }>(columns: readonly T[]): T[] {
  return [...columns].sort((a, b) => a.position - b.position);
}

/** The cards of a column in board order (the server sends them by rank). */
export function cardsOf(board: TodoBoard, columnId: Uuid): TodoCardTile[] {
  return board.cards.filter((c) => c.columnId === columnId);
}

/**
 * The move request for a card at `index` of `list`, the target column in its new order
 * WITH the card. The neighbor above wins (`afterId`); the first place names the card
 * below (`beforeId`); an empty column needs neither. One neighbor is enough for the
 * server and stays valid when a filter hides cards between the two.
 */
export function moveRequest(list: readonly TodoCardTile[], index: number, columnId: Uuid): TodoCardMove {
  if (index > 0) return { columnId, afterId: list[index - 1].id };
  const below = list[index + 1];
  return below ? { columnId, beforeId: below.id } : { columnId };
}

/**
 * The move request for a card from another board that lands at `index` of `list`, the
 * target column WITHOUT the card (the same neighbors as `moveRequest`).
 */
export function dropMove(list: readonly TodoCardTile[], index: number, columnId: Uuid): TodoCardMove {
  if (index > 0) return { columnId, afterId: list[index - 1].id };
  return list[0] ? { columnId, beforeId: list[0].id } : { columnId };
}

/** What the tile helpers below read of a board: a board read or a row of "Meine To-Dos". */
export type TileBoard = Pick<TodoBoard, 'columns' | 'cards'>;

/**
 * The board after a move, before the server answers: the card leaves its place and sits
 * after `afterId`, before `beforeId`, or at the end of the column.
 */
export function applyMove<B extends TileBoard>(board: B, cardId: Uuid, move: TodoCardMove): B {
  const card = board.cards.find((c) => c.id === cardId);
  if (!card) return board;
  const moved: TodoCardTile = { ...card, columnId: move.columnId };
  const rest = board.cards.filter((c) => c.id !== cardId);
  let at = -1;
  if (move.afterId) {
    const i = rest.findIndex((c) => c.id === move.afterId);
    if (i >= 0) at = i + 1;
  } else if (move.beforeId) {
    at = rest.findIndex((c) => c.id === move.beforeId);
  }
  if (at < 0) {
    // The end of the column: after its last card, else where the column order puts it.
    const last = rest.map((c) => c.columnId).lastIndexOf(move.columnId);
    at = last >= 0 ? last + 1 : rest.length;
  }
  const cards = [...rest.slice(0, at), moved, ...rest.slice(at)];
  return { ...board, cards, columns: recount(board, cards) };
}

/** Put a server tile into the board (a move answer, a new card). */
export function replaceTile<B extends TileBoard>(board: B, tile: TodoCardTile): B {
  const has = board.cards.some((c) => c.id === tile.id);
  const cards = has ? board.cards.map((c) => (c.id === tile.id ? tile : c)) : [...board.cards, tile];
  return { ...board, cards, columns: recount(board, cards) };
}

/**
 * Put a server tile into the board at its place. A tile that changed its column, or that
 * the board does not hold yet (a restored card), goes before the first card of its column
 * with a higher rank, else to the end of it; any other tile keeps its place (`replaceTile`).
 */
export function placeTile<B extends TileBoard>(board: B, tile: TodoCardTile): B {
  const old = board.cards.find((c) => c.id === tile.id);
  if (old && old.columnId === tile.columnId) return replaceTile(board, tile);
  const base = old ? board : { ...board, cards: [...board.cards, tile] };
  const next = base.cards.find((c) => c.id !== tile.id && c.columnId === tile.columnId && c.rank > tile.rank);
  const moved = applyMove(base, tile.id, next ? { columnId: tile.columnId, beforeId: next.id } : { columnId: tile.columnId });
  return replaceTile(moved, tile);
}

/** The board after a card of another board landed on it, before the server answers. */
export function insertTile<B extends TileBoard & { id: Uuid }>(board: B, tile: TodoCardTile, move: TodoCardMove): B {
  const base = { ...board, cards: [...board.cards.filter((c) => c.id !== tile.id), { ...tile, boardId: board.id }] };
  return applyMove(base, tile.id, move);
}

/** Drop a card from the board (archived). */
export function removeTile<B extends TileBoard>(board: B, cardId: Uuid): B {
  const cards = board.cards.filter((c) => c.id !== cardId);
  return { ...board, cards, columns: recount(board, cards) };
}

function recount(board: TileBoard, cards: readonly TodoCardTile[]): TodoBoard['columns'] {
  return board.columns.map((col) => ({ ...col, cardCount: cards.filter((c) => c.columnId === col.id).length }));
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

/** The ids of the people a comment names as "@Display Name". */
export function mentionIds(body: string, members: readonly { principalId: Uuid; displayName: string | null }[]): Uuid[] {
  const ids: Uuid[] = [];
  for (const m of members) {
    if (m.displayName && body.includes(`@${m.displayName}`) && !ids.includes(m.principalId)) {
      ids.push(m.principalId);
    }
  }
  return ids;
}

/** An app route of a link ("/meetings/m-1?item=a-1") as router path and query. */
export function splitUrl(url: string): { path: string; query: Record<string, string> } {
  const [path, search = ''] = url.split('?');
  const query: Record<string, string> = {};
  new URLSearchParams(search).forEach((value, key) => (query[key] = value));
  return { path, query };
}
