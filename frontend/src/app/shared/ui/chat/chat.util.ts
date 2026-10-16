import type { ChatEvent, ChatMessage, ChatVisibility } from './chat.models';

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
    // A group is one person within the window; a change of visibility does not break it.
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

/** A URL in escaped text. It ends before white space or a tag. */
const URL_RE = /https?:\/\/[^\s<]+/g;
/** Characters and entities at the end of a match that close the sentence, not the URL. */
const TRAILING = /(?:[.,;:!?)\]]|&gt;|&quot;|&#39;)$/;

/** Cut the punctuation that follows a URL in a sentence. */
function trimUrl(url: string): string {
  let out = url;
  while (TRAILING.test(out)) out = out.replace(TRAILING, '');
  return out;
}

/**
 * Turn the bare URLs of rendered, escaped HTML into links. Text inside a link or a code
 * element stays as it is. The link shows the whole URL; it is never shortened.
 */
export function linkify(html: string): string {
  let depth = 0;
  return html
    .split(/(<[^>]+>)/)
    .map((part) => {
      if (part.startsWith('<')) {
        if (/^<(a|code|pre)\b/.test(part)) depth++;
        else if (/^<\/(a|code|pre)>/.test(part)) depth--;
        return part;
      }
      if (depth > 0) return part;
      return part.replace(URL_RE, (match) => {
        const url = trimUrl(match);
        const rest = match.slice(url.length);
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>${rest}`;
      });
    })
    .join('');
}
