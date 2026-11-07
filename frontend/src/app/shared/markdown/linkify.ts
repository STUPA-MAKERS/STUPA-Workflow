/**
 * Bare URLs in rendered, escaped HTML become links. The Markdown renderer and the chat
 * share this one implementation.
 */

/** A URL in escaped text. It ends before white space, a tag or an escaped quote or
 *  angle bracket, so no quote ever reaches an href. */
const URL_RE = /https?:\/\/(?:(?!&(?:quot|#39|lt|gt);)[^\s<])+/g;
/** Characters and entities at the end of a match that close the sentence, not the URL. */
const TRAILING = /(?:[.,;:!?)\]]|&gt;|&quot;|&#39;)$/;

/** Cut the punctuation that follows a URL in a sentence. */
function trimUrl(url: string): string {
  return TRAILING.test(url) ? trimUrl(url.replace(TRAILING, '')) : url;
}

/** How a piece of HTML changes the depth of link and code elements: +1 opens, -1 closes. */
function depthStep(part: string): number {
  if (!part.startsWith('<')) return 0;
  if (/^<(a|code|pre)\b/.test(part)) return 1;
  return /^<\/(a|code|pre)>/.test(part) ? -1 : 0;
}

/**
 * The pieces of HTML split at its tags, each with the depth of link and code elements
 * after it. A text piece inside a link or a code element has a depth above 0.
 */
export function tagPieces(
  html: string,
): readonly { readonly part: string; readonly depth: number }[] {
  const parts = html.split(/(<[^>]+>)/);
  const depths = parts.reduce<readonly number[]>(
    (acc, part) => [...acc, (acc.at(-1) ?? 0) + depthStep(part)],
    [],
  );
  return parts.map((part, i) => ({ part, depth: depths[i] }));
}

/**
 * Turn the bare URLs of rendered, escaped HTML into links. Text inside a link or a code
 * element stays as it is. The link shows the whole URL; it is never shortened.
 */
export function linkify(html: string): string {
  return tagPieces(html)
    .map(({ part, depth }) => {
      if (part.startsWith('<') || depth > 0) return part;
      return part.replace(URL_RE, (match) => {
        const url = trimUrl(match);
        const rest = match.slice(url.length);
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>${rest}`;
      });
    })
    .join('');
}
