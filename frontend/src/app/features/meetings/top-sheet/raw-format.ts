import type { MarkdownFormat } from '@stupa-makers/ui-kit/markdown-editor';

/** A text with a selection, as a textarea holds it. */
export interface RawText {
  readonly text: string;
  readonly start: number;
  readonly end: number;
}

const MARKS: Partial<Record<MarkdownFormat, string>> = { bold: '**', italic: '*', blackout: '%%' };
const PREFIXES: Partial<Record<MarkdownFormat, string>> = { heading: '## ', bulletList: '- ' };

/**
 * Switch a format in the Markdown source, as the format bar does in the formatted view.
 *
 * Bold and italic put the marks around the selection, or remove them when the selection
 * already has them. An empty selection gets an empty pair with the cursor between the
 * marks. A heading and a list put their prefix before each selected line, or remove it
 * when every line already has it.
 *
 * Blackout (000690): a selection in one line gets the marker `%%…%%`. A selection over more
 * than one line, a caret in an empty line, and a caret in a block switch a block: the fence
 * lines `%%` go around the selected lines, or the fence lines of the block go away.
 */
export function applyRawFormat(raw: RawText, format: MarkdownFormat): RawText {
  if (format === 'blackout' && !hasInlineMark(raw)) {
    const block = enclosingBlock(raw);
    if (block) return removeBlock(raw, block);
    if (wantsBlock(raw)) return addBlock(raw);
  }
  const mark = MARKS[format];
  if (mark) return toggleMark(raw, mark);
  return togglePrefix(raw, PREFIXES[format] ?? '');
}

function toggleMark({ text, start, end }: RawText, mark: string): RawText {
  const n = mark.length;
  const stars = Math.min(starsBefore(text, start), starsAfter(text, end));
  const has =
    mark === '%%'
      ? text.slice(start - 2, start) === '%%' && text.slice(end, end + 2) === '%%'
      : n === 2
        ? stars >= 2
        : stars % 2 === 1;
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

/** A fence line of a blackout block: only `%%`. */
const FENCE_RE = /^[ \t]*%%[ \t]*$/;

/** The offsets of the start of each line, and the lines. */
function linesOf(text: string): { readonly lines: readonly string[]; readonly starts: readonly number[] } {
  const lines = text.split('\n');
  const starts = lines.reduce<readonly number[]>(
    (acc, _l, i) => (i === 0 ? [0] : [...acc, acc[i - 1] + lines[i - 1].length + 1]),
    [],
  );
  return { lines, starts };
}

/** The line index of an offset. */
function lineAt(starts: readonly number[], at: number): number {
  const after = starts.findIndex((s) => s > at);
  return (after < 0 ? starts.length : after) - 1;
}

/** True if the selection in one line has the marker `%%…%%` around it. */
function hasInlineMark({ text, start, end }: RawText): boolean {
  return (
    !text.slice(start, end).includes('\n') &&
    text.slice(start - 2, start) === '%%' &&
    text.slice(end, end + 2) === '%%'
  );
}

/** True if the selection spans more than one line, or the caret is in an empty line. */
function wantsBlock({ text, start, end }: RawText): boolean {
  if (text.slice(start, end).includes('\n')) return true;
  const { lines, starts } = linesOf(text);
  return start === end && !lines[lineAt(starts, start)].trim();
}

/**
 * The fence lines of the block that holds the selection, else `null`. Fence lines pair up
 * from the top, outside code, as the renderers read them.
 */
function enclosingBlock({ text, start, end }: RawText): { readonly open: number; readonly close: number } | null {
  const { lines, starts } = linesOf(text);
  const first = lineAt(starts, start);
  const last = lineAt(starts, end);
  const pairs = lines.reduce<{ readonly code: boolean; readonly open: number | null; readonly found: readonly [number, number][] }>(
    (acc, line, i) => {
      if (/^\s*(```|~~~)/.test(line)) return { ...acc, code: !acc.code };
      if (acc.code || !FENCE_RE.test(line)) return acc;
      return acc.open === null ? { ...acc, open: i } : { ...acc, open: null, found: [...acc.found, [acc.open, i]] };
    },
    { code: false, open: null, found: [] },
  ).found;
  const hit = pairs.find(([o, c]) => o <= first && last <= c);
  return hit ? { open: hit[0], close: hit[1] } : null;
}

/** Remove the two fence lines of a block, and keep the selection on the same text. */
function removeBlock({ text, start, end }: RawText, block: { readonly open: number; readonly close: number }): RawText {
  const { lines, starts } = linesOf(text);
  const openAt = starts[block.open];
  const openLen = lines[block.open].length + 1;
  const closeAt = starts[block.close];
  const closeLen = lines[block.close].length + 1;
  const kept = lines.filter((_l, i) => i !== block.open && i !== block.close).join('\n');
  const shift = (at: number): number => {
    if (at <= openAt) return at;
    if (at < openAt + openLen) return openAt;
    if (at <= closeAt) return at - openLen;
    return Math.max(closeAt - openLen, at - openLen - closeLen);
  };
  return { text: kept, start: shift(start), end: Math.min(kept.length, shift(end)) };
}

/** Put the fence lines `%%` around the lines of the selection. */
function addBlock({ text, start, end }: RawText): RawText {
  const from = text.lastIndexOf('\n', start - 1) + 1;
  const nl = text.indexOf('\n', end > start && text[end - 1] === '\n' ? end - 1 : end);
  const to = nl < 0 ? text.length : nl;
  const block = `%%\n${text.slice(from, to)}\n%%`;
  return { text: text.slice(0, from) + block + text.slice(to), start: start + 3, end: end + 3 };
}

function starsBefore(text: string, at: number): number {
  return /\*+$/.exec(text.slice(0, Math.max(0, at)))?.[0].length ?? 0;
}

function starsAfter(text: string, at: number): number {
  return /^\*+/.exec(text.slice(Math.max(0, at)))?.[0].length ?? 0;
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

/** The time zone of a protocol: the times in the PDF and in the notes are local times. */
export const PROTOCOL_TZ = 'Europe/Berlin';

/** The current time of the protocol time zone as `HH:MM`. */
export function protocolNow(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('de-DE', {
    timeZone: PROTOCOL_TZ,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(now);
}

/**
 * Insert a time note `> [!anmerkung HH:MM] ` as a block of its own after the line of the
 * caret. The caret goes to the end of the new line, where the text of the note starts.
 */
export function insertRawTimeNote({ text, end }: RawText, time: string): RawText {
  const lineEnd = text.indexOf('\n', end);
  const cut = lineEnd < 0 ? text.length : lineEnd;
  const before = text.slice(0, cut);
  const after = text.slice(cut);
  const line = `> [!anmerkung ${time}] `;
  const lead = !before ? '' : before.endsWith('\n\n') ? '' : before.endsWith('\n') ? '\n' : '\n\n';
  const tail = !after ? '' : after.startsWith('\n\n') ? '' : after.startsWith('\n') ? '\n' : '\n\n';
  const caret = before.length + lead.length + line.length;
  return { text: before + lead + line + tail + after, start: caret, end: caret };
}

/**
 * Insert an inline reference (an embedded PDF) at the caret, in place of the selection,
 * with a space on each side where the text has none. The caret goes behind it.
 */
export function insertRawInline({ text, start, end }: RawText, reference: string): RawText {
  const before = text.slice(0, start);
  const after = text.slice(end);
  const lead = before && !/\s$/.test(before) ? ' ' : '';
  const trail = /^\s/.test(after) ? '' : ' ';
  const insert = `${lead}${reference}${trail}`;
  const caret = start + insert.length;
  return { text: before + insert + after, start: caret, end: caret };
}
