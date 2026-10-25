import type { MessageAttachment, ScanState } from '@core/api/models';
import type { ChatAttachment, ChatEvent, ChatMessage, ChatVisibility } from './chat.models';

/** The most files one message carries; the server checks it again. */
export const CHAT_MAX_FILES = 5;

/** The download of a message file: streamed through the API (`base` = `API_BASE_URL`). */
export function chatFileUrl(base: string, id: string): string {
  return `${base}/attachments/${id}/download`;
}

/** The files of a message on the wire, as the chat shows them. */
export function toChatAttachments(
  base: string,
  files: readonly MessageAttachment[] | null | undefined,
): ChatAttachment[] {
  return (files ?? []).map((f) => ({
    id: f.id,
    filename: f.filename,
    mime: f.mime,
    size: f.size,
    scanState: f.scanState,
    url: chatFileUrl(base, f.id),
  }));
}

/** A message on the wire with files: a comment, a note or a card comment. */
interface WithFiles {
  id: string;
  attachments?: readonly MessageAttachment[] | null;
}

/**
 * The scan states of a background read (`refresh`), put into the list on screen. The
 * read can be older than a send, an edit or a delete that ended while it was in flight,
 * so the list keeps its own messages and only the scan state of their files changes.
 */
export function withScanStates<T extends WithFiles>(current: readonly T[], fresh: readonly WithFiles[]): T[] {
  const states = new Map<string, ScanState>();
  for (const m of fresh) for (const f of m.attachments ?? []) states.set(f.id, f.scanState);
  return current.map((m) => {
    const files = m.attachments ?? [];
    if (!files.some((f) => (states.get(f.id) ?? f.scanState) !== f.scanState)) return m;
    return { ...m, attachments: files.map((f) => ({ ...f, scanState: states.get(f.id) ?? f.scanState })) };
  });
}

/** A delivered message joins the list once; a message with its id already there is replaced. */
export function appendOnce<T extends { id: string }>(list: readonly T[], item: T): T[] {
  return list.some((x) => x.id === item.id) ? list.map((x) => (x.id === item.id ? item : x)) : [...list, item];
}

/** Messages of one person within this time form one group: one name, one avatar. */
export const GROUP_WINDOW_MS = 5 * 60_000;

/** A row of the rendered thread. */
export type ChatItem =
  | { kind: 'day'; key: string; label: string }
  | { kind: 'new'; key: string; count: number }
  | { kind: 'event'; key: string; text: string; at: string }
  | {
      kind: 'msg';
      key: string;
      msg: ChatMessage;
      /** The name above the first message of a group of another person. */
      name: string | null;
      /** First message of its group: name and visibility label. */
      head: boolean;
      /** Last message of its group: time and avatar. */
      tail: boolean;
      /** The visibility mark, only where a thread holds both kinds. */
      mark: ChatVisibility | null;
      /** The mark shows its label: first of a group, or the visibility changes in it. */
      markLabel: boolean;
    };

export interface BuildOptions {
  /** Mark internal and public messages. */
  marked: boolean;
  /** Messages of others after this time are new. null: nothing is new. */
  markerAt: string | null;
  /** The label of a day separator. */
  dayLabel: (date: Date) => string;
  /** The shown name of a message's author. */
  name: (msg: ChatMessage) => string | null;
}

/** A message the server has not confirmed yet. */
export function isPending(msg: ChatMessage): boolean {
  return msg.state === 'sending' || msg.state === 'failed';
}

/** The local calendar day of a date, as `YYYY-M-D`. */
export function dayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

/** Who wrote a message, for the grouping. */
function authorKey(msg: ChatMessage): string {
  if (msg.own) return 'own';
  return `${msg.author?.principalId ?? ''}|${msg.authorLabel ?? msg.author?.displayName ?? ''}`;
}

/** The number of messages of others that are newer than `after`. */
export function newCount(messages: readonly ChatMessage[], after: string | null): number {
  if (after === null) return 0;
  const t = Date.parse(after);
  return messages.filter((m) => !m.own && !isPending(m) && Date.parse(m.at) > t).length;
}

type MsgItem = Extract<ChatItem, { kind: 'msg' }>;

type Entry = { kind: 'msg'; msg: ChatMessage } | { kind: 'event'; event: ChatEvent };

/**
 * The rows of a thread: day separators, the "N neue" separator, events and messages in
 * groups. Sent messages and events go by time; pending messages come last in their order.
 */
export function buildItems(
  messages: readonly ChatMessage[],
  events: readonly ChatEvent[],
  opts: BuildOptions,
): ChatItem[] {
  const timed: Entry[] = [
    ...messages.filter((m) => !isPending(m)).map((msg) => ({ kind: 'msg' as const, msg })),
    ...events.map((event) => ({ kind: 'event' as const, event })),
  ];
  const at = (e: Entry) => Date.parse(e.kind === 'msg' ? e.msg.at : e.event.at);
  timed.sort((a, b) => at(a) - at(b));
  const entries: Entry[] = [
    ...timed,
    ...messages.filter(isPending).map((msg) => ({ kind: 'msg' as const, msg })),
  ];

  const count = newCount(messages, opts.markerAt);
  const marker = opts.markerAt === null ? null : Date.parse(opts.markerAt);
  let newShown = false;
  let lastDay: string | null = null;
  /** The previous message row, while nothing stands between it and the next one. */
  let prev: MsgItem | null = null;
  const items: ChatItem[] = [];

  for (const entry of entries) {
    const time = new Date(entry.kind === 'msg' ? entry.msg.at : entry.event.at);
    const day = dayKey(time);
    if (day !== lastDay) {
      items.push({ kind: 'day', key: `day-${day}`, label: opts.dayLabel(time) });
      lastDay = day;
      prev = null;
    }
    if (entry.kind === 'event') {
      items.push({ kind: 'event', key: `ev-${entry.event.id}`, text: entry.event.text, at: entry.event.at });
      prev = null;
      continue;
    }
    const msg = entry.msg;
    if (
      !newShown &&
      marker !== null &&
      count > 0 &&
      !msg.own &&
      !isPending(msg) &&
      time.getTime() > marker
    ) {
      items.push({ kind: 'new', key: 'new', count });
      newShown = true;
      prev = null;
    }
    const joins =
      prev !== null &&
      authorKey(prev.msg) === authorKey(msg) &&
      time.getTime() - Date.parse(prev.msg.at) <= GROUP_WINDOW_MS;
    if (prev !== null && joins) prev.tail = false;
    const visChanged = prev !== null && (prev.msg.visibility ?? null) !== (msg.visibility ?? null);
    const item: MsgItem = {
      kind: 'msg',
      key: `msg-${msg.id}`,
      msg,
      name: msg.own ? null : opts.name(msg),
      head: !joins,
      tail: true,
      mark: opts.marked ? (msg.visibility ?? null) : null,
      markLabel: !joins || visChanged,
    };
    items.push(item);
    prev = item;
  }
  return items;
}
