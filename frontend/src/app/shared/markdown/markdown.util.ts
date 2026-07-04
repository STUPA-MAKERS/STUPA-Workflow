/**
 * Miniature Markdown renderer — escape-first, therefore XSS-safe: the ENTIRE
 * input is HTML-escaped before any tag is generated, so markup can only come
 * from the generator itself (fixed tags/attributes, link protocols allow-listed).
 *
 * Supported subset (enough for long-text form fields):
 * headings (`#`…, rendered small as h4–h6), `**bold**`, `*italic*`/`_italic_`,
 * `` `code` ``, ``` fenced blocks, `[label](https://…)` links (http/https/mailto),
 * `-`/`*` and `1.` lists, `>` quotes; single line breaks inside a paragraph are
 * preserved as `<br>`.
 */

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Inline markup on already-escaped text: code spans first (protected via
 *  placeholder so bold/italic/link rules cannot touch their content). */
function renderInline(text: string): string {
  const codes: string[] = [];
  let out = text.replace(/`([^`]+)`/g, (_m, code: string) => {
    codes.push(`<code>${code}</code>`);
    return `\u0000${codes.length - 1}\u0000`;
  });
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m: string, label: string, href: string) => {
    // href is escaped text (& → &amp;) — fine for an attribute value.
    if (!/^(https?:\/\/|mailto:)/i.test(href)) return m;
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?:;]|$)/g, '$1<em>$2</em>');
  out = out.replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,!?:;]|$)/g, '$1<em>$2</em>');
  // eslint-disable-next-line no-control-regex -- NUL sentinel (collision-free in escaped text)
  return out.replace(/\u0000(\d+)\u0000/g, (_m, i: string) => codes[Number(i)]);
}

export function markdownToSafeHtml(src: string): string {
  const lines = escapeHtml(src.replace(/\r\n?/g, '\n')).split('\n');
  const out: string[] = [];
  let para: string[] = [];
  let list: { tag: 'ul' | 'ol'; items: string[] } | null = null;
  let quote: string[] = [];
  let fence: string[] | null = null;

  const flushPara = (): void => {
    if (para.length) {
      out.push(`<p>${para.map(renderInline).join('<br>')}</p>`);
      para = [];
    }
  };
  const flushList = (): void => {
    if (list) {
      const items = list.items.map((i) => `<li>${renderInline(i)}</li>`).join('');
      out.push(`<${list.tag}>${items}</${list.tag}>`);
      list = null;
    }
  };
  const flushQuote = (): void => {
    if (quote.length) {
      out.push(`<blockquote>${quote.map(renderInline).join('<br>')}</blockquote>`);
      quote = [];
    }
  };
  const flushAll = (): void => {
    flushPara();
    flushList();
    flushQuote();
  };

  for (const line of lines) {
    if (fence) {
      if (/^```/.test(line.trim())) {
        out.push(`<pre><code>${fence.join('\n')}</code></pre>`);
        fence = null;
      } else {
        fence.push(line);
      }
      continue;
    }
    const t = line.trim();
    if (/^```/.test(t)) {
      flushAll();
      fence = [];
      continue;
    }
    if (!t) {
      flushAll();
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(t);
    if (h) {
      flushAll();
      // Shifted down (h4–h6): headings inside a detail card stay card-sized.
      const lvl = Math.min(h[1].length + 3, 6);
      out.push(`<h${lvl}>${renderInline(h[2])}</h${lvl}>`);
      continue;
    }
    const ul = /^[-*]\s+(.*)$/.exec(t);
    if (ul) {
      flushPara();
      flushQuote();
      if (!list || list.tag !== 'ul') {
        flushList();
        list = { tag: 'ul', items: [] };
      }
      list.items.push(ul[1]);
      continue;
    }
    const ol = /^\d+[.)]\s+(.*)$/.exec(t);
    if (ol) {
      flushPara();
      flushQuote();
      if (!list || list.tag !== 'ol') {
        flushList();
        list = { tag: 'ol', items: [] };
      }
      list.items.push(ol[1]);
      continue;
    }
    // '>' is already escaped at this point.
    const q = /^&gt;\s?(.*)$/.exec(t);
    if (q) {
      flushPara();
      flushList();
      quote.push(q[1]);
      continue;
    }
    flushList();
    flushQuote();
    para.push(t);
  }
  if (fence) out.push(`<pre><code>${fence.join('\n')}</code></pre>`);
  flushAll();
  return out.join('\n');
}
