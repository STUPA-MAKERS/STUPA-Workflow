import type { MarkdownFormat } from '@stupa-makers/ui-kit/markdown-editor';

/** A text with a selection, as a textarea holds it. */
export interface RawText {
  text: string;
  start: number;
  end: number;
}

const MARKS: Partial<Record<MarkdownFormat, string>> = { bold: '**', italic: '*' };
const PREFIXES: Partial<Record<MarkdownFormat, string>> = { heading: '## ', bulletList: '- ' };

/**
 * Switch a format in the Markdown source, as the format bar does in the formatted view.
 *
 * Bold and italic put the marks around the selection, or remove them when the selection
 * already has them. An empty selection gets an empty pair with the cursor between the
 * marks. A heading and a list put their prefix before each selected line, or remove it
 * when every line already has it.
 */
export function applyRawFormat(raw: RawText, format: MarkdownFormat): RawText {
  const mark = MARKS[format];
  if (mark) return toggleMark(raw, mark);
  return togglePrefix(raw, PREFIXES[format] ?? '');
}

function toggleMark({ text, start, end }: RawText, mark: string): RawText {
  const n = mark.length;
  const stars = Math.min(starsBefore(text, start), starsAfter(text, end));
  const has = n === 2 ? stars >= 2 : stars % 2 === 1;
  if (has) {
    return {
      text: text.slice(0, start - n) + text.slice(start, end) + text.slice(end + n),
      start: start - n,
      end: end - n,
    };
  }
  return {
    text: text.slice(0, start) + mark + text.slice(start, end) + mark + text.slice(end),
    start: start + n,
    end: end + n,
  };
}

function starsBefore(text: string, at: number): number {
  let i = at;
  while (i > 0 && text[i - 1] === '*') i--;
  return at - i;
}

function starsAfter(text: string, at: number): number {
  let i = at;
  while (i < text.length && text[i] === '*') i++;
  return i - at;
}

function togglePrefix({ text, start, end }: RawText, prefix: string): RawText {
  const from = text.lastIndexOf('\n', start - 1) + 1;
  const nl = text.indexOf('\n', end);
  const to = nl < 0 ? text.length : nl;
  const lines = text.slice(from, to).split('\n');
  const remove = lines.every((l) => l.startsWith(prefix));
  const next = lines.map((l) => (remove ? l.slice(prefix.length) : prefix + l));
  const shift = remove ? -prefix.length : prefix.length;
  const block = next.join('\n');
  return {
    text: text.slice(0, from) + block + text.slice(to),
    start: Math.max(from, start + shift),
    end: from + block.length - (to - end),
  };
}

/**
 * Insert an empty GFM table with a header row at the cursor of the Markdown source, as
 * "Tabelle einfügen" does in the formatted view. The table stands as a block of its own,
 * with an empty line before and after it, and the cursor goes into its first cell.
 */
export function insertRawTable({ text, end }: RawText, rows = 3, cols = 3): RawText {
  const row = `|${'  |'.repeat(cols)}`;
  const delimiter = `|${' --- |'.repeat(cols)}`;
  const table = [row, delimiter, ...Array.from({ length: rows - 1 }, () => row)].join('\n');
  const before = text.slice(0, end);
  const after = text.slice(end);
  const lead = !before ? '' : before.endsWith('\n\n') ? '' : before.endsWith('\n') ? '\n' : '\n\n';
  const tail = !after ? '\n' : after.startsWith('\n\n') ? '' : after.startsWith('\n') ? '\n' : '\n\n';
  const next = before + lead + table + tail + after;
  const cell = before.length + lead.length + 2;
  return { text: next, start: cell, end: cell };
}
