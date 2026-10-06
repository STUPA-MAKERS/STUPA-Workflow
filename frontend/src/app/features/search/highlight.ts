/** A piece of a text, and whether it matches the query. */
export interface TextPart {
  text: string;
  hit: boolean;
}

/**
 * Split a text into the parts that match the query and the parts that do not, without
 * regard to case. Every match is marked, so "Radhaus" and "Lastenrad" both show "rad".
 * An empty query gives the whole text as one plain part.
 */
export function highlight(text: string, query: string): TextPart[] {
  const q = query.trim().toLocaleLowerCase();
  if (!q || !text) return [{ text, hit: false }];
  const lower = text.toLocaleLowerCase();
  // A locale lowering that changes the length (rare, for example "İ") would shift every
  // index after it. Then the text stays plain rather than marking the wrong letters.
  if (lower.length !== text.length) return [{ text, hit: false }];
  const parts: TextPart[] = [];
  let from = 0;
  for (let at = lower.indexOf(q); at !== -1; at = lower.indexOf(q, at + q.length)) {
    if (at > from) parts.push({ text: text.slice(from, at), hit: false });
    parts.push({ text: text.slice(at, at + q.length), hit: true });
    from = at + q.length;
  }
  if (from < text.length) parts.push({ text: text.slice(from), hit: false });
  return parts;
}
