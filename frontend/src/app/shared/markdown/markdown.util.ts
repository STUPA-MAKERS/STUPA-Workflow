/**
 * The Markdown renderer of the app. It escapes first, so it is safe against XSS. The
 * renderer escapes the WHOLE input before it makes any tag. Markup can come from the
 * generator only. The generator writes fixed tags and attributes, allows a fixed list of
 * link protocols and builds an image source only from a validated uuid.
 *
 * Blocks: headings (`#` to `######`, shifted by `headingOffset`), fenced code, `>` quotes
 * with blocks of their own, GitHub and protocol callouts (`> [!NOTE]`, `> [!abstimmung]`,
 * …), `-`/`*` lists, `1.` lists, task items (`- [ ]`, `- [x]`), GFM pipe tables with
 * alignment, horizontal rules (`---`, `***`, `___`) and paragraphs. A single line break
 * inside a paragraph stays as a `<br>`.
 *
 * Inline: backslash escapes (`\*`), a backslash at the end of a line as a line break,
 * `**bold**`, `*italic*`, `_italic_`, `~~strike~~`, `` `code` ``, a link with the http,
 * https or mailto protocol or an app path (`/…`), and an image. An image renders only
 * when its destination is the canonical path `/api/media/images/<uuid>`. Every other
 * destination renders as its alt text, so no external image loads (tracking pixels).
 */

import { linkify } from './linkify';

/** The canonical image path. Group 1 is the lowercase uuid. */
const IMAGE_PATH_RE =
  /^\/api\/media\/images\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/;

/** The control characters except tab and line feed (and carriage return, which becomes
 *  a line feed first). */
// eslint-disable-next-line no-control-regex -- control characters are the point
const CONTROL_RE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g;

export interface MarkdownOptions {
  /** The number of levels that a heading moves down. The default 3 renders `#` as h4.
   *  A full-size document uses 0. */
  readonly headingOffset?: number;
  /**
   * The URL of an image from its uuid. The default is the canonical path, which needs a
   * session. `null` renders the alt text instead of an image (anonymous contexts).
   */
  readonly imageSrc?: ((id: string) => string) | null;
}

/** The default image source: the canonical path, served to any authenticated session. */
export const defaultImageSrc = (id: string): string => `/api/media/images/${id}`;

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * The kind of a link target, or `null` when the target is not allowed. `external` is an
 * http, https or mailto URL and opens in a new tab. `internal` is an app path (`/…`, not
 * `//…`) or an anchor (`#…`) and stays in the tab. Every other scheme (`javascript:`,
 * `data:`, `vbscript:`, …) is refused.
 *
 * The text is escaped already, so a raw `"`, `<`, `>` or `'` arrives as an entity. The
 * check rejects both forms, a backslash and every whitespace or control character, so no
 * attribute break-out can happen even without a sanitizer.
 */
function hrefKind(url: string): 'external' | 'internal' | null {
  if (/["'<>\\]|&(?:quot|lt|gt|#39|#x27);/i.test(url)) return null;
  // eslint-disable-next-line no-control-regex -- control characters are the point
  if (/[\s\x00-\x1f\x7f]/.test(url)) return null;
  if (/^(https?:\/\/[^/]|mailto:)/i.test(url)) return 'external';
  if (/^(\/(?!\/)|#)/.test(url)) return 'internal';
  return null;
}

/**
 * Replace each `[label](dest)` (or `![alt](dest)` when `bang` is set) with the result
 * of `render`. The destination may hold balanced parentheses, as in a Wikipedia URL. A
 * `null` result keeps the source text.
 */
function replaceRefs(
  text: string,
  bang: boolean,
  render: (label: string, dest: string) => string | null,
): string {
  let out = '';
  let i = 0;
  while (i < text.length) {
    const open = bang ? text.startsWith('![', i) : text[i] === '[';
    const start = i + (bang ? 2 : 1);
    const close = open ? text.indexOf(']', start) : -1;
    const label = close >= 0 ? text.slice(start, close) : '';
    const dest = close >= 0 && text[close + 1] === '(' ? destination(text, close + 2) : null;
    const html = dest !== null && !label.includes('[') ? render(label, dest.url) : null;
    if (html === null || dest === null) {
      out += text[i];
      i++;
      continue;
    }
    out += html;
    i = dest.end;
  }
  return out;
}

/** The destination from `from` to its closing parenthesis, or `null` when it has none. */
function destination(
  text: string,
  from: number,
): { readonly url: string; readonly end: number } | null {
  let depth = 0;
  for (let j = from; j < text.length; j++) {
    const c = text[j];
    if (/\s/.test(c)) return null;
    if (c === '(') depth++;
    else if (c === ')') {
      if (depth === 0) return { url: text.slice(from, j), end: j + 1 };
      depth--;
    }
  }
  return null;
}

/** Callout kind → title and CSS modifier: the GitHub kinds and the protocol kinds. */
const CALLOUT_TITLES: Record<string, string> = {
  note: 'Note',
  tip: 'Tip',
  important: 'Important',
  warning: 'Warning',
  caution: 'Caution',
  abstimmung: 'Abstimmung',
  beschluss: 'Beschluss',
  aufgabe: 'Aufgabe',
  frist: 'Frist',
};

/** The inline renderer of one options set. */
type Inline = (text: string) => string;

/**
 * Apply the inline markup to text that is already escaped. Code spans, images and links
 * become placeholders first. The emphasis rules then cannot touch a code span or an
 * attribute value.
 *
 * A fragment can hold the placeholder of an earlier fragment, so the fill happens when the fragment
 * is stashed and the final restore is one pass. The alt text and the source are escaped again,
 * because the source is the output of a consumer function and must never break out of the
 * attribute.
 */
function inlineRenderer(imageSrc: ((id: string) => string) | null): Inline {
  return (text: string): string => {
    const parts: string[] = [];
    const texts: string[] = [];
    // eslint-disable-next-line no-control-regex -- NUL sentinel (the source has no control characters)
    const sentinel = /\u0000(\d+)\u0000/g;
    const fill = (s: string, plain = false): string =>
      s.replace(sentinel, (_m, i: string) => (plain ? texts : parts)[Number(i)] ?? '');
    const stash = (html: string, plain = html): string => {
      parts.push(fill(html));
      texts.push(fill(plain, true));
      return `\u0000${parts.length - 1}\u0000`;
    };
    const emphasis = (s: string): string =>
      s
        .replace(/~~([^~\n]+)~~/g, '<del>$1</del>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[\s(>])\*([^*\n]+)\*(?=[\s).,!?:;<]|$)/g, '$1<em>$2</em>')
        .replace(/(^|[\s(>])_([^_\n]+)_(?=[\s).,!?:;<]|$)/g, '$1<em>$2</em>');

    const coded = text.replace(/`([^`]+)`/g, (_m, code: string) =>
      stash(`<code>${code}</code>`, code),
    );
    const escaped = coded
      .replace(/\\$/, '')
      .replace(/\\(&amp;|&lt;|&gt;|&quot;|&#39;|[!-/:-@[-`{-~])/g, (_m, c: string) => stash(c));
    const imaged = replaceRefs(escaped, true, (alt, dest) => {
      const id = IMAGE_PATH_RE.exec(dest)?.[1];
      if (!id || !imageSrc) return alt ? stash(alt) : '';
      const src = escapeHtml(imageSrc(id));
      const plain = fill(alt, true);
      return stash(`<img src="${src}" alt="${plain}" loading="lazy" decoding="async">`, plain);
    });
    const linked = replaceRefs(imaged, false, (label, href) => {
      const kind = label ? hrefKind(href) : null;
      if (!kind) return null;
      const attrs = kind === 'external' ? ' target="_blank" rel="noopener noreferrer"' : '';
      return stash(`<a href="${href}"${attrs}>${emphasis(label)}</a>`, label);
    });
    return fill(emphasis(linked));
  };
}

/** The cells of a pipe-table row (`| a | b |`). An escaped pipe (`\|`) stays in its cell. */
function tableCells(line: string): readonly string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/(^|[^\\])\|$/, '$1')
    .split(/(?<!\\)\|/)
    .map((c) => c.trim().replace(/\\\|/g, '|'));
}

/** The alignment of each column from a separator row, or `null` when it is none. */
function tableAlign(line: string): readonly string[] | null {
  if (!line.includes('-')) return null;
  const cells = tableCells(line);
  if (!cells.every((c) => /^:?-+:?$/.test(c))) return null;
  if (!line.includes('|') && cells.length < 2) return null;
  return cells.map((c) => {
    if (c.startsWith(':') && c.endsWith(':')) return 'center';
    if (c.endsWith(':')) return 'right';
    return c.startsWith(':') ? 'left' : '';
  });
}

function renderTable(
  head: readonly string[],
  align: readonly string[],
  rows: readonly (readonly string[])[],
  inline: Inline,
): string {
  const cell = (tag: 'th' | 'td', text: string, col: number): string => {
    const cls = align[col] ? ` class="mdv__al--${align[col]}"` : '';
    return `<${tag}${cls}>${inline(text)}</${tag}>`;
  };
  const row = (cells: readonly string[], tag: 'th' | 'td'): string =>
    `<tr>${align.map((_a, i) => cell(tag, cells[i] ?? '', i)).join('')}</tr>`;
  const body = rows.map((r) => row(r, 'td')).join('');
  return (
    `<div class="mdv__table"><table><thead>${row(head, 'th')}</thead>` +
    `<tbody>${body}</tbody></table></div>`
  );
}

/**
 * A group of consecutive `>` lines: a callout or otherwise a plain blockquote. A plain
 * blockquote holds blocks of its own (paragraphs, headings, lists, a nested quote), so
 * a quoted mail keeps its paragraphs. `blocks` renders lines that are escaped already.
 */
function renderQuote(
  lines: readonly string[],
  inline: Inline,
  blocks: (lines: readonly string[]) => string,
): string {
  const marker = /^\[!(\w+)\]\s*(.*)$/.exec(lines[0].trim());
  const kind = marker ? marker[1].toLowerCase() : '';
  if (marker && kind in CALLOUT_TITLES) {
    const first = marker[2].trim();
    const body = [...(first ? [first] : []), ...lines.slice(1)];
    const inner = body.length ? `<p>${body.map(inline).join('<br>')}</p>` : '';
    return (
      `<div class="callout callout--${kind}">` +
      `<p class="callout__title">${CALLOUT_TITLES[kind]}</p>${inner}</div>`
    );
  }
  return `<blockquote>${blocks(lines)}</blockquote>`;
}

/** One list item. A task item (`[ ]`, `[x]`) gets a disabled checkbox. */
function renderItem(text: string, inline: Inline): string {
  const task = /^\[([ xX])\]\s+(.*)$/.exec(text);
  if (!task) return `<li>${inline(text)}</li>`;
  const checked = task[1] === ' ' ? '' : ' checked';
  return (
    `<li class="mdv__task"><input type="checkbox" disabled${checked}> ` +
    `${inline(task[2])}</li>`
  );
}

/**
 * Control characters are removed first, because the NUL character is the placeholder sentinel of
 * the inline renderer and a source that holds one could forge a placeholder.
 */
export function markdownToSafeHtml(src: string, opts: MarkdownOptions = {}): string {
  const offset = opts.headingOffset ?? 3;
  const inline = inlineRenderer(opts.imageSrc === undefined ? defaultImageSrc : opts.imageSrc);
  const clean = src.replace(/\r\n?/g, '\n').replace(CONTROL_RE, '');
  return linkify(renderBlocks(escapeHtml(clean).split('\n'), offset, inline));
}

/** An open list: its tag and the source text of its items. */
interface OpenList {
  readonly tag: 'ul' | 'ol';
  readonly items: readonly string[];
}

/**
 * The state of the block renderer after a line: the finished blocks, the open paragraph,
 * list, quote and code fence, and the number of lines a table took ahead.
 */
interface BlockState {
  readonly out: readonly string[];
  readonly para: readonly string[];
  readonly list: OpenList | null;
  readonly quote: readonly string[];
  readonly fence: readonly string[] | null;
  readonly skip: number;
}

/** The settings of one render: the heading offset and the inline renderer. */
interface BlockContext {
  readonly offset: number;
  readonly inline: Inline;
}

/** The state with `html` added to the finished blocks. */
function emit(s: BlockState, html: string): BlockState {
  return { ...s, out: [...s.out, html] };
}

/** Closes the open paragraph. */
function flushPara(s: BlockState, ctx: BlockContext): BlockState {
  if (!s.para.length) return s;
  return { ...emit(s, `<p>${s.para.map(ctx.inline).join('<br>')}</p>`), para: [] };
}

/** Closes the open list. */
function flushList(s: BlockState, ctx: BlockContext): BlockState {
  if (!s.list) return s;
  const items = s.list.items.map((i) => renderItem(i, ctx.inline)).join('');
  return { ...emit(s, `<${s.list.tag}>${items}</${s.list.tag}>`), list: null };
}

/** Closes the open quote. A blockquote renders its lines again. */
function flushQuote(s: BlockState, ctx: BlockContext): BlockState {
  const blocks = (inner: readonly string[]): string => renderBlocks(inner, ctx.offset, ctx.inline);
  return s.quote.length ? { ...emit(s, renderQuote(s.quote, ctx.inline, blocks)), quote: [] } : s;
}

/** Closes the open paragraph, list and quote. */
function flushAll(s: BlockState, ctx: BlockContext): BlockState {
  return flushQuote(flushList(flushPara(s, ctx), ctx), ctx);
}

/** Adds a list item; a list of the other tag closes first. */
function pushItem(s: BlockState, ctx: BlockContext, tag: 'ul' | 'ol', text: string): BlockState {
  const open = flushQuote(flushPara(s, ctx), ctx);
  const items = open.list?.tag === tag ? open.list.items : [];
  const base = open.list?.tag === tag ? open : flushList(open, ctx);
  return { ...base, list: { tag, items: [...items, text] } };
}

/** The code block of a fence. */
function fenceHtml(fence: readonly string[]): string {
  return `<pre><code>${fence.join('\n')}</code></pre>`;
}

/** The state after a line inside a code fence: the closing fence ends it. */
function fenceStep(s: BlockState, fence: readonly string[], line: string): BlockState {
  return /^```/.test(line.trim())
    ? { ...emit(s, fenceHtml(fence)), fence: null }
    : { ...s, fence: [...fence, line] };
}

/**
 * The table that starts at line `i`, with the rows that follow its separator row, or `null`
 * when the line is not the head of a table.
 */
function tableAt(
  lines: readonly string[],
  i: number,
): { readonly html: (inline: Inline) => string; readonly taken: number } | null {
  const t = lines[i].trim();
  const align = t.includes('|') && i + 1 < lines.length ? tableAlign(lines[i + 1]) : null;
  const head = align ? tableCells(t) : null;
  if (!align || head?.length !== align.length) return null;
  const rest = lines.slice(i + 2);
  const end = rest.findIndex((l) => !(l.trim() && l.includes('|')));
  const rows = (end < 0 ? rest : rest.slice(0, end)).map(tableCells);
  return { html: (inline) => renderTable(head, align, rows, inline), taken: 1 + rows.length };
}

/** The state after the line `i` outside a code fence. */
function lineStep(
  s: BlockState,
  ctx: BlockContext,
  lines: readonly string[],
  i: number,
): BlockState {
  const t = lines[i].trim();
  if (/^```/.test(t)) return { ...flushAll(s, ctx), fence: [] };
  if (!t) return flushAll(s, ctx);
  const h = /^(#{1,6})\s+(.*)$/.exec(t);
  if (h) {
    const lvl = Math.min(h[1].length + ctx.offset, 6);
    return emit(flushAll(s, ctx), `<h${lvl}>${ctx.inline(h[2])}</h${lvl}>`);
  }
  if (/^([-*_])(\s*\1){2,}$/.test(t)) return emit(flushAll(s, ctx), '<hr>');
  const table = tableAt(lines, i);
  if (table) return { ...emit(flushAll(s, ctx), table.html(ctx.inline)), skip: table.taken };
  const ul = /^[-*+]\s+(.*)$/.exec(t);
  if (ul) return pushItem(s, ctx, 'ul', ul[1]);
  const ol = /^\d+[.)]\s+(.*)$/.exec(t);
  if (ol) return pushItem(s, ctx, 'ol', ol[1]);
  const q = /^&gt;\s?(.*)$/.exec(t);
  if (q) {
    const open = flushList(flushPara(s, ctx), ctx);
    return { ...open, quote: [...open.quote, q[1]] };
  }
  const open = flushQuote(flushList(s, ctx), ctx);
  return { ...open, para: [...open.para, t] };
}

/** The blocks of lines that are escaped already. A blockquote renders its lines again. */
function renderBlocks(lines: readonly string[], offset: number, inline: Inline): string {
  const ctx: BlockContext = { offset, inline };
  const start: BlockState = { out: [], para: [], list: null, quote: [], fence: null, skip: 0 };
  const step = (s: BlockState, line: string, i: number): BlockState => {
    if (s.skip > 0) return { ...s, skip: s.skip - 1 };
    return s.fence ? fenceStep(s, s.fence, line) : lineStep(s, ctx, lines, i);
  };
  const end = lines.reduce(step, start);
  const closed = end.fence ? { ...emit(end, fenceHtml(end.fence)), fence: null } : end;
  return flushAll(closed, ctx).out.join('\n');
}
