/**
 * Miniature Markdown renderer. It escapes first, so it is safe against XSS. The renderer
 * escapes the WHOLE input before it makes any tag. Markup can come from the generator
 * only. The generator writes fixed tags and attributes and allows a fixed list of link
 * protocols.
 *
 * The supported subset is enough for a long-text form field. It covers headings (`#` and
 * more), which render small as h4 to h6. It covers `**bold**`, `*italic*`, `_italic_` and
 * `` `code` ``. It covers fenced code blocks and `>` quotes. It covers a
 * `[label](https://…)` link with the http, https or mailto protocol. It covers `-` and `*`
 * lists and `1.` lists. A single line break inside a paragraph stays as a `<br>`.
 */

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Apply the inline markup to text that is already escaped. The renderer handles a code
 *  span first and replaces it with a placeholder. The bold, italic and link rules then
 *  cannot touch the content of a code span. */
function renderInline(text: string): string {
  const codes: string[] = [];
  let out = text.replace(/`([^`]+)`/g, (_m, code: string) => {
    codes.push(`<code>${code}</code>`);
    return `\u0000${codes.length - 1}\u0000`;
  });
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m: string, label: string, href: string) => {
    // The href holds escaped text with an escaped ampersand. It is safe as an attribute.
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
      // Shift the level down to h4 or lower. A heading inside a detail card stays small.
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
    // The escape step already replaced the '>' character with its HTML entity.
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
