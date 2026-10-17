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
