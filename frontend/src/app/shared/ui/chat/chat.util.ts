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
  readonly id: string;
  readonly attachments?: readonly MessageAttachment[] | null;
}

/**
 * The scan states of a background read (`refresh`), put into the list on screen. The
 * read can be older than a send, an edit or a delete that ended while it was in flight,
 * so the list keeps its own messages and only the scan state of their files changes.
 */
export function withScanStates<T extends WithFiles>(current: readonly T[], fresh: readonly WithFiles[]): T[] {
  const states = new Map<string, ScanState>(
    fresh.flatMap((m) => (m.attachments ?? []).map((f) => [f.id, f.scanState] as const)),
  );
  return current.map((m) => {
    const files = m.attachments ?? [];
    if (!files.some((f) => (states.get(f.id) ?? f.scanState) !== f.scanState)) return m;
    return { ...m, attachments: files.map((f) => ({ ...f, scanState: states.get(f.id) ?? f.scanState })) };
  });
}

/** A delivered message joins the list once; a message with its id already there is replaced. */
export function appendOnce<T extends { readonly id: string }>(list: readonly T[], item: T): T[] {
  return list.some((x) => x.id === item.id) ? list.map((x) => (x.id === item.id ? item : x)) : [...list, item];
}

/** Messages of one person within this time form one group: one name, one avatar. */
export const GROUP_WINDOW_MS = 5 * 60_000;

/** A row of the rendered thread. */
export type ChatItem =
  | { readonly kind: 'day'; readonly key: string; readonly label: string }
  | { readonly kind: 'new'; readonly key: string; readonly count: number }
  | { readonly kind: 'event'; readonly key: string; readonly text: string; readonly at: string }
  | {
      readonly kind: 'msg';
      readonly key: string;
      readonly msg: ChatMessage;
      /** The name above the first message of a group of another person. */
      readonly name: string | null;
      /** First message of its group: name and visibility label. */
      readonly head: boolean;
      /** Last message of its group: time and avatar. */
      readonly tail: boolean;
      /** The visibility mark, only where a thread holds both kinds. */
      readonly mark: ChatVisibility | null;
      /** The mark shows its label: first of a group, or the visibility changes in it. */
      readonly markLabel: boolean;
    };

export interface BuildOptions {
  /** Mark internal and public messages. */
  readonly marked: boolean;
  /** Messages of others after this time are new. null: nothing is new. */
  readonly markerAt: string | null;
  /** The label of a day separator. */
  readonly dayLabel: (date: Date) => string;
  /** The shown name of a message's author. */
  readonly name: (msg: ChatMessage) => string | null;
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

type MsgItem = Extract<ChatItem, { readonly kind: 'msg' }>;

type Entry =
  | { readonly kind: 'msg'; readonly msg: ChatMessage }
  | { readonly kind: 'event'; readonly event: ChatEvent };

/** The time of a thread entry. */
function entryAt(entry: Entry): string {
  return entry.kind === 'msg' ? entry.msg.at : entry.event.at;
}

/** The entries of a thread: sent messages and events by time, then the pending messages. */
function threadEntries(
  messages: readonly ChatMessage[],
  events: readonly ChatEvent[],
): readonly Entry[] {
  const timed: readonly Entry[] = [
    ...messages.filter((m) => !isPending(m)).map((msg) => ({ kind: 'msg' as const, msg })),
    ...events.map((event) => ({ kind: 'event' as const, event })),
  ];
  return [
    ...[...timed].sort((a, b) => Date.parse(entryAt(a)) - Date.parse(entryAt(b))),
    ...messages.filter(isPending).map((msg) => ({ kind: 'msg' as const, msg })),
  ];
}

/**
 * The index of the entry that gets the "N neue" separator, or -1: the first message of
 * another person that is newer than the marker, and only when something is new.
 */
function newIndex(entries: readonly Entry[], opts: BuildOptions, count: number): number {
  if (opts.markerAt === null || count <= 0) return -1;
  const marker = Date.parse(opts.markerAt);
  return entries.findIndex(
    (e) =>
      e.kind === 'msg' &&
      !e.msg.own &&
      !isPending(e.msg) &&
      new Date(e.msg.at).getTime() > marker,
  );
}

/**
 * The rows of a thread: day separators, the "N neue" separator, events and messages in
 * groups. Sent messages and events go by time; pending messages come last in their order.
 */
export function buildItems(
  messages: readonly ChatMessage[],
  events: readonly ChatEvent[],
  opts: BuildOptions,
): ChatItem[] {
  const entries = threadEntries(messages, events);
  const count = newCount(messages, opts.markerAt);
  const newAt = newIndex(entries, opts, count);
  const days = entries.map((e) => dayKey(new Date(entryAt(e))));
  const dayBreak = (i: number): boolean => i === 0 || days[i] !== days[i - 1];
  /** The previous message, while nothing stands between it and the message at `i`. */
  const prevMsg = (i: number): ChatMessage | null => {
    const before = entries[i - 1];
    return before?.kind === 'msg' && !dayBreak(i) && i !== newAt ? before.msg : null;
  };
  const joins = (i: number, msg: ChatMessage): boolean => {
    const prev = prevMsg(i);
    return (
      prev !== null &&
      authorKey(prev) === authorKey(msg) &&
      new Date(msg.at).getTime() - Date.parse(prev.at) <= GROUP_WINDOW_MS
    );
  };
  const msgItem = (i: number, msg: ChatMessage): MsgItem => {
    const prev = prevMsg(i);
    const joined = joins(i, msg);
    const next = entries[i + 1];
    const visChanged = prev !== null && (prev.visibility ?? null) !== (msg.visibility ?? null);
    return {
      kind: 'msg',
      key: `msg-${msg.id}`,
      msg,
      name: msg.own ? null : opts.name(msg),
      head: !joined,
      tail: !(next?.kind === 'msg' && joins(i + 1, next.msg)),
      mark: opts.marked ? (msg.visibility ?? null) : null,
      markLabel: !joined || visChanged,
    };
  };
  const row = (entry: Entry, i: number): ChatItem =>
    entry.kind === 'event'
      ? { kind: 'event', key: `ev-${entry.event.id}`, text: entry.event.text, at: entry.event.at }
      : msgItem(i, entry.msg);
  const dayRow = (entry: Entry, i: number): ChatItem => ({
    kind: 'day',
    key: `day-${days[i]}`,
    label: opts.dayLabel(new Date(entryAt(entry))),
  });
  return entries.flatMap((entry, i): readonly ChatItem[] => [
    ...(dayBreak(i) ? [dayRow(entry, i)] : []),
    ...(i === newAt ? [{ kind: 'new' as const, key: 'new', count }] : []),
    row(entry, i),
  ]);
}
