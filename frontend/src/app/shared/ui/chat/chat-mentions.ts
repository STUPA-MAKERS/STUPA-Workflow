import { computed, signal } from '@angular/core';
import type { PersonRef } from '@core/api/models';

/** A person the composer offers after "@": someone who can read the thread. */
export interface ChatPerson {
  principalId: string;
  displayName: string;
}

/** The most people the picker lists at once. */
export const MENTION_MAX_OPTIONS = 6;
/** The longest text after "@" that still counts as a search, in characters. */
const MAX_QUERY = 40;

/** The people of a reference list that have an id and a name. */
export function chatPeople(refs: readonly PersonRef[] | null | undefined): ChatPerson[] {
  const out: ChatPerson[] = [];
  for (const r of refs ?? []) {
    if (r.principalId && r.displayName)
      out.push({ principalId: r.principalId, displayName: r.displayName });
  }
  return out;
}

/** A name for the search: lower case, without accents; the dotless "ı" reads as "i". */
function fold(s: string): string {
  return s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().replace(/ı/g, 'i');
}

/**
 * The open "@" search before the caret: where the "@" stands and the text after it.
 * The "@" starts a word (start of the text, after white space or an opening bracket),
 * and the search holds no line break and no second "@". null: no search is open.
 */
export function mentionQuery(text: string, caret: number): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const at = before.lastIndexOf('@');
  if (at < 0) return null;
  if (at > 0 && !/[\s([{]/.test(before[at - 1])) return null;
  const query = before.slice(at + 1);
  if (query.length > MAX_QUERY || /[\n@]/.test(query) || /^\s/.test(query)) return null;
  return { start: at, query };
}

/**
 * The people that match a search, best first. A name that starts with the search comes
 * before a name with a later word that starts with it; case and accents do not count.
 */
export function matchPeople(
  people: readonly ChatPerson[],
  query: string,
  max = MENTION_MAX_OPTIONS,
): ChatPerson[] {
  const q = fold(query.trimEnd());
  const ranked: { p: ChatPerson; rank: number }[] = [];
  for (const p of people) {
    const name = fold(p.displayName);
    let rank = -1;
    if (name.startsWith(q)) rank = 0;
    else if (name.split(/\s+/).some((w) => w.startsWith(q))) rank = 1;
    else if (q.length > 1 && name.includes(q)) rank = 2;
    if (rank >= 0) ranked.push({ p, rank });
  }
  ranked.sort(
    (a, b) =>
      a.rank - b.rank ||
      a.p.displayName.localeCompare(b.p.displayName) ||
      a.p.principalId.localeCompare(b.p.principalId),
  );
  return ranked.slice(0, max).map((r) => r.p);
}

/** Put "@Name " in place of the search from `start` to the caret. */
export function insertMention(
  text: string,
  start: number,
  caret: number,
  name: string,
): { text: string; caret: number } {
  const after = text.slice(caret);
  const insert = `@${name}${after.startsWith(' ') ? '' : ' '}`;
  const next = text.slice(0, start) + insert + after;
  return { text: next, caret: start + insert.length + (after.startsWith(' ') ? 1 : 0) };
}

/**
 * The names longest first, so "@Anna Maria" wins over "@Anna" at the same place. Of two
 * people with the same name, a person in `picked` comes first.
 */
function byLength(people: readonly ChatPerson[], picked: readonly string[]): ChatPerson[] {
  const rank = (p: ChatPerson): number => (picked.includes(p.principalId) ? 0 : 1);
  return [...people].sort(
    (a, b) => b.displayName.length - a.displayName.length || rank(a) - rank(b),
  );
}

/** A name ends at the end of the text or before a character that is no letter or digit. */
function endsName(text: string, at: number): boolean {
  return at >= text.length || !/[\p{L}\p{N}]/u.test(text[at]);
}

/**
 * The ids of the people that a text names as "@Display Name", in the order of the text.
 * The longer name wins where two names start alike; each person counts once. Where two
 * people have the same name, the one in `picked` (chosen in the list) wins.
 */
export function mentionIds(
  body: string,
  people: readonly ChatPerson[],
  picked: readonly string[] = [],
): string[] {
  const found: { at: number; id: string }[] = [];
  const taken: [number, number][] = [];
  for (const p of byLength(people, picked)) {
    const token = `@${p.displayName}`;
    let at = body.indexOf(token);
    while (at >= 0) {
      const end = at + token.length;
      const free = (at === 0 || !/[\p{L}\p{N}]/u.test(body[at - 1])) && endsName(body, end);
      if (free && !taken.some(([s, e]) => at < e && end > s)) {
        taken.push([at, end]);
        found.push({ at, id: p.principalId });
      }
      at = body.indexOf(token, at + 1);
    }
  }
  found.sort((a, b) => a.at - b.at);
  return [...new Set(found.map((f) => f.id))];
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Mark the "@Name" of the mentioned people in rendered, escaped HTML. Text inside a link
 * or a code element stays as it is; the names are escaped like the text, so the mark
 * wraps only text and adds no markup of the author.
 */
export function highlightMentions(html: string, names: readonly string[]): string {
  const wanted = [...new Set(names.filter((n) => n.trim()))].sort((a, b) => b.length - a.length);
  if (!wanted.length) return html;
  const re = new RegExp(
    `(^|[^\\p{L}\\p{N}])@(${wanted.map((n) => escapeRe(escapeHtml(n))).join('|')})(?![\\p{L}\\p{N}])`,
    'gu',
  );
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
      return part.replace(
        re,
        (_m, lead: string, name: string) => `${lead}<span class="chat__mention">@${name}</span>`,
      );
    })
    .join('');
}

/**
 * The "@" picker of one text box. The chat keeps one for the composer and one for the
 * edit. `update` reads the text and the caret after each input or caret move; `key`
 * takes the arrows, Enter, Tab and Escape while the list is open.
 */
export class MentionPicker {
  private readonly people = signal<readonly ChatPerson[]>([]);
  private readonly search = signal<{ start: number; query: string } | null>(null);
  /** Escape closed the list for this "@": it opens again at the next "@". */
  private dismissedAt: number | null = null;
  /** The ids of the people chosen in the list since the last `reset`. */
  private chosen: string[] = [];
  readonly active = signal(0);

  readonly options = computed(() => {
    const s = this.search();
    return s ? matchPeople(this.people(), s.query) : [];
  });
  readonly open = computed(() => this.options().length > 0);

  constructor(readonly listId: string) {}

  setPeople(people: readonly ChatPerson[]): void {
    this.people.set(people);
  }

  optionId(i: number): string {
    return `${this.listId}-${i}`;
  }

  update(text: string, caret: number): void {
    const found = this.people().length ? mentionQuery(text, caret) : null;
    // "@Name " after a whole name is a finished mention, not a search for a longer name.
    const done = found !== null && /\s$/.test(found.query) && this.isName(found.query.trim());
    const s = done ? null : found;
    if (s === null || s.start !== this.dismissedAt) this.dismissedAt = null;
    const next = s && s.start !== this.dismissedAt ? s : null;
    const prev = this.search();
    if (prev?.start !== next?.start || prev?.query !== next?.query) this.active.set(0);
    this.search.set(next);
  }

  private isName(query: string): boolean {
    const q = fold(query);
    return this.people().some((p) => fold(p.displayName) === q);
  }

  close(): void {
    this.search.set(null);
  }

  /** The ids of the people chosen in the list, for `mentionIds`. */
  picked(): readonly string[] {
    return this.chosen;
  }

  /**
   * Close the list and forget the chosen people: the text box starts a new message. An
   * edit keeps the people that the message mentions, so their names stay with them.
   */
  reset(keep: readonly string[] = []): void {
    this.close();
    this.chosen = [...keep];
  }

  /**
   * A key while the list is open. Returns the person that Enter or Tab chose, 'handled'
   * for a key the list took, or null for a key that goes on to the text box.
   */
  key(event: KeyboardEvent): ChatPerson | 'handled' | null {
    if (!this.open() || event.isComposing) return null;
    const n = this.options().length;
    switch (event.key) {
      case 'ArrowDown':
        this.active.set((this.active() + 1) % n);
        return 'handled';
      case 'ArrowUp':
        this.active.set((this.active() - 1 + n) % n);
        return 'handled';
      case 'Enter':
      case 'Tab':
        if (event.shiftKey) return null;
        return this.options()[Math.min(this.active(), n - 1)];
      case 'Escape':
        this.dismissedAt = this.search()?.start ?? null;
        this.close();
        return 'handled';
      default:
        return null;
    }
  }

  /** The text with the chosen person in place of the search, and the new caret. */
  apply(text: string, person: ChatPerson): { text: string; caret: number } | null {
    const s = this.search();
    if (!s) return null;
    this.close();
    if (!this.chosen.includes(person.principalId)) this.chosen.push(person.principalId);
    return insertMention(text, s.start, s.start + 1 + s.query.length, person.displayName);
  }
}
