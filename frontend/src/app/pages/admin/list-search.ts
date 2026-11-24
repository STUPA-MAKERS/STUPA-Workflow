import { computed, signal, type Signal } from '@angular/core';
import type { ListRow, LoadState } from '@stupa-makers/ui-kit';

/** One shown text of a row; `null` and `undefined` count as no text. */
export type SearchText = string | null | undefined;

/**
 * The search of a Verwaltung list page that holds all its rows (§002691). The search pill of
 * the records screen writes {@link ListSearch.text}; a row stays when each word of the text
 * occurs in one of its shown texts, without regard to case.
 */
export interface ListSearch {
  /** The text in the search pill. */
  readonly text: Signal<string>;
  /** The words of the search, in lower case; empty without a search. */
  readonly words: Signal<readonly string[]>;
  /** Set the text (the `valueChange` of the pill). */
  set(text: string): void;
  /** True when the texts hold each word, or when there is no search. */
  matches(texts: readonly SearchText[]): boolean;
  /** The items whose texts match, in their order. */
  filter<T>(items: readonly T[], texts: (item: T) => readonly SearchText[]): readonly T[];
}

/** Split a search into its words, in lower case. */
export function searchWords(text: string): readonly string[] {
  return text
    .trim()
    .toLocaleLowerCase()
    .split(/\s+/)
    .filter((w) => w.length > 0);
}

/** True when the texts together hold each of the words. */
export function textsMatch(words: readonly string[], texts: readonly SearchText[]): boolean {
  if (!words.length) return true;
  const hay = texts
    .filter((t): t is string => !!t)
    .join('\n')
    .toLocaleLowerCase();
  return words.every((w) => hay.includes(w));
}

/** Make the search of a list page. */
export function listSearch(): ListSearch {
  const text = signal('');
  const words = computed(() => searchWords(text()));
  return {
    text: text.asReadonly(),
    words,
    set: (value: string) => text.set(value ?? ''),
    matches: (texts) => textsMatch(words(), texts),
    filter: (items, texts) => items.filter((item) => textsMatch(words(), texts(item))),
  };
}

/**
 * The rows of a records screen after the search: a search without hits shows the face
 * "Keine Treffer" instead of the empty state of the page. Other states pass unchanged.
 */
export function searchedRows(
  rows: LoadState<readonly ListRow[]>,
  search: ListSearch,
  noHits: string,
): LoadState<readonly ListRow[]> {
  if (!search.words().length) return rows;
  if (rows.state === 'empty') return { state: 'empty', icon: 'searchOff', heading: noHits };
  return rows;
}

/** The number of hits for the pill, or `null` without a search or while the rows load. */
export function hitCount(rows: LoadState<readonly ListRow[]>, search: ListSearch): number | null {
  if (!search.words().length) return null;
  if (rows.state === 'ready') return rows.data.length;
  if (rows.state === 'empty') return 0;
  return null;
}
