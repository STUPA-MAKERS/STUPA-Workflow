/**
 * Pure, DI-free helpers for the protocol editor.
 *
 *  - Snippet builders produce markdown references to applications and votes.
 *    The pytex renderer resolves them as shortcodes (`:::antrag` / `:::vote`).
 *  - `renderMarkdown` is a minimal, dependency-free Markdown→HTML renderer for
 *    the live preview. It escapes ALL HTML entities FIRST, so no raw HTML from
 *    the editor reaches the output. Angular also sanitizes the `innerHTML`.
 */

import type { MeetingVote } from '@core/api/models';

/** Escape HTML entities (XSS: editor input is never trustworthy). */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Markdown snippet referencing an application (pytex shortcode `:::antrag`). */
export function antragSnippet(applicationId: string, title: string | null): string {
  const heading = title?.trim() ? title.trim() : applicationId;
  return `\n:::antrag{#${applicationId}}\n### ${heading}\n:::\n`;
}

/**
 * TOP snippet from an agenda item: numbered TOP heading, plus the application
 * reference for application-bound TOPs. Freetext TOPs carry only the heading.
 */
export function topSnippet(
  position: number,
  title: string | null,
  applicationId: string | null,
): string {
  const heading = title?.trim() ? title.trim() : (applicationId ?? `TOP ${position}`);
  const ref = applicationId ? `\n:::antrag{#${applicationId}}\n:::\n` : '';
  return `\n## TOP ${position}: ${heading}\n${ref}`;
}

/**
 * Markdown snippet that embeds a vote result: a readable tally table
 * (option → count) AND the `:::vote` shortcode. pytex attaches the canonical
 * evaluation to that shortcode.
 */
export function voteSnippet(vote: MeetingVote): string {
  const lines: string[] = [`\n:::vote{#${vote.id}}`];
  const heading =
    vote.title?.trim() || vote.question?.trim() || vote.applicationId || 'Beschluss';
  lines.push(`### ${heading}`);
  if (vote.counts && Object.keys(vote.counts).length > 0) {
    lines.push('', '| Option | Stimmen |', '| --- | --- |');
    for (const [option, count] of Object.entries(vote.counts)) {
      lines.push(`| ${option} | ${count} |`);
    }
  }
  if (vote.result) lines.push('', `**Ergebnis:** ${vote.result}`);
  lines.push(':::', '');
  return `\n${lines.join('\n')}`;
}

/** Insert markdown at the caret position (or append at the end). */
export function insertAt(text: string, snippet: string, caret: number | null): string {
  if (caret === null || caret < 0 || caret > text.length) return text + snippet;
  return text.slice(0, caret) + snippet + text.slice(caret);
}

/**
 * Allow only links with a safe scheme. This blocks the `javascript:` vector.
 *
 * Second line of defense: the check looks for characters that can break out of
 * the `href="…"` attribute. It runs before the interpolation. `inline` already
 * escaped the text, so a raw `"`, `<`, `>` or `'` arrives as an entity. The
 * check rejects both forms. No attribute break-out can happen, even without
 * the Angular innerHTML sanitization.
 */
function safeUrl(url: string): boolean {
  if (!/^(https?:\/\/|mailto:|\/)/i.test(url)) return false;
  if (/["'<>]|&(?:quot|lt|gt|#39|#x27);/i.test(url)) return false;
  // eslint-disable-next-line no-control-regex
  if (/[\s\x00-\x1f\x7f]/.test(url)) return false;
  return true;
}

function inline(text: string): string {
  // Order: code first (protects its content), then links, bold before italic.
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label: string, url: string) =>
      safeUrl(url)
        ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
        : match,
    )
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

/** Trim the cells of a pipe-table row (`| a | b |`). */
function tableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim());
}

/** Separator row of a pipe table? (`| --- | :--: |`). */
function isTableSeparator(line: string): boolean {
  return /^\|?[\s:|-]+\|?$/.test(line.trim()) && line.includes('-') && line.includes('|');
}

// GitHub callout kinds (`> [!NOTE]` …) → title + CSS modifier.
const CALLOUT_TITLES: Record<string, string> = {
  note: 'Note',
  tip: 'Tip',
  important: 'Important',
  warning: 'Warning',
  caution: 'Caution',
};

/**
 * Render a group of consecutive `>` lines: a GitHub callout
 * (`> [!NOTE]`/`[!TIP]`/…) or otherwise a plain blockquote. The renderer
 * handles every line inline.
 */
function renderQuote(lines: string[]): string {
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
  return `<blockquote>${lines.map(inline).join('<br>')}</blockquote>`;
}

/**
 * Minimal, dependency-free Markdown→HTML renderer for the preview. See the file
 * header. It supports headings, bold, italic, code, links, ordered and unordered
 * lists, quotes, pipe tables, horizontal rules and paragraphs. That is enough
 * for meeting minutes, including the `voteSnippet` tally tables.
 */
export function renderMarkdown(markdown: string): string {
  const lines = (markdown ?? '').replace(/\r\n/g, '\n').split('\n');
  const html: string[] = [];
  let list: 'ul' | 'ol' | null = null;
  let paragraph: string[] = [];

  const flushParagraph = (): void => {
    if (paragraph.length) {
      html.push(`<p>${paragraph.map(inline).join('<br>')}</p>`);
      paragraph = [];
    }
  };
  const closeList = (): void => {
    if (list) {
      html.push(`</${list}>`);
      list = null;
    }
  };
  const openList = (kind: 'ul' | 'ol'): void => {
    if (list !== kind) {
      closeList();
      html.push(`<${kind}>`);
      list = kind;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    const ordered = /^\d+\.\s+(.*)$/.exec(line);
    const unordered = /^[-*]\s+(.*)$/.exec(line);
    const quote = /^>\s?(.*)$/.exec(line);
    const isHr = /^([-*_])\1{2,}$/.test(line.trim());
    const isTableHead =
      line.trim().startsWith('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1]);

    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
    } else if (isHr) {
      flushParagraph();
      closeList();
      html.push('<hr>');
    } else if (isTableHead) {
      flushParagraph();
      closeList();
      const head = tableCells(line);
      i += 2; // skip header + separator row
      const body: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        body.push(tableCells(lines[i]));
        i++;
      }
      i--; // the for loop increments again
      const thead = `<thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead>`;
      const rows = body
        .map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`)
        .join('');
      html.push(`<table>${thead}<tbody>${rows}</tbody></table>`);
    } else if (ordered) {
      flushParagraph();
      openList('ol');
      html.push(`<li>${inline(ordered[1])}</li>`);
    } else if (unordered) {
      flushParagraph();
      openList('ul');
      html.push(`<li>${inline(unordered[1])}</li>`);
    } else if (quote) {
      flushParagraph();
      closeList();
      // Collect consecutive `>` lines (callouts + multi-line quotes).
      const quoteLines: string[] = [quote[1]];
      while (i + 1 < lines.length) {
        const m = /^>\s?(.*)$/.exec(lines[i + 1].trimEnd());
        if (!m) break;
        quoteLines.push(m[1]);
        i++;
      }
      html.push(renderQuote(quoteLines));
    } else if (line.trim() === '') {
      flushParagraph();
      closeList();
    } else {
      closeList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  closeList();
  return html.join('\n');
}
