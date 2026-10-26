/** A `{name}` placeholder that `I18nService.translate` fills from its params. */
const PLACEHOLDER = /\{(\w+)\}/g;

/** The placeholder names of `text`, sorted and without repeats. */
export function placeholdersOf(text: string): string[] {
  return [...new Set([...text.matchAll(PLACEHOLDER)].map((m) => m[1]))].sort();
}

/**
 * True when `text` holds exactly the placeholders of `reference`. An override that loses
 * `{count}` hides the number, and an unknown one shows literally, so the admin page and the
 * server refuse both.
 */
export function samePlaceholders(text: string, reference: string): boolean {
  const a = placeholdersOf(text);
  const b = placeholdersOf(reference);
  return a.length === b.length && a.every((name, i) => name === b[i]);
}
