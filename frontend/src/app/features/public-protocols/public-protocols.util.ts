import { DestroyRef, inject } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import type { TranslationKey } from '@core/i18n/translations';
import { normalizeQuestion } from '../meetings/vote-result/vote-result';
import type { PublicDecision, PublicTopSummary, PublicVoteResult } from './public-protocols.models';

/** The parts of a semester key: `ws-2026` → winter 2026/27, `ss-2026` → summer 2026. */
export interface SemesterParts {
  readonly kind: 'ws' | 'ss';
  readonly year: number;
}

/** Read a semester key. An unknown key gives `null`. */
export function parseSemester(key: string): SemesterParts | null {
  const m = /^(ws|ss)-(\d{4})$/.exec(key);
  if (!m) return null;
  return { kind: m[1] as 'ws' | 'ss', year: Number(m[2]) };
}

/**
 * The label of a semester, with the translation function of the page:
 * "Wintersemester 2026/27", "Sommersemester 2026". An unknown key stays as it is.
 */
export function semesterLabel(
  key: string,
  t: (key: TranslationKey, params?: Record<string, string | number>) => string,
): string {
  const s = parseSemester(key);
  if (!s) return key;
  if (s.kind === 'ss') return t('publicProtocols.semester.ss', { year: s.year });
  const next = String((s.year + 1) % 100).padStart(2, '0');
  return t('publicProtocols.semester.ws', { year: s.year, next });
}

/** The i18n key of a decision result. */
export function resultKey(result: PublicVoteResult): TranslationKey {
  return `vote.result.${result}` as TranslationKey;
}

/** The number of decisions and of skipped non-public items of a protocol. */
export function topCounts(tops: readonly PublicTopSummary[]): { readonly decisions: number; readonly nonPublic: number } {
  const hidden = tops.filter((top) => top.nonPublic);
  const decisions = tops
    .filter((top) => !top.nonPublic)
    .reduce((sum, top) => sum + top.results.length, 0);
  return { decisions, nonPublic: hidden.length };
}

/** The order of the vote options in a decision: yes, no, abstain, then the rest. */
const OPTION_ORDER = ['ja', 'yes', 'nein', 'no', 'enthaltung', 'abstain'];

/** The i18n key of a known vote option, or `null` for another one. */
export function optionKey(option: string): TranslationKey | null {
  switch (option.toLocaleLowerCase()) {
    case 'ja':
    case 'yes':
      return 'vote.option.yes';
    case 'nein':
    case 'no':
      return 'vote.option.no';
    case 'enthaltung':
    case 'abstain':
      return 'vote.option.abstain';
    default:
      return null;
  }
}

/** The counts of a decision in a stable order. */
export function orderedCounts(counts: Record<string, number>): readonly { readonly option: string; readonly count: number }[] {
  const rank = (o: string) => {
    const at = OPTION_ORDER.indexOf(o.toLocaleLowerCase());
    return at === -1 ? OPTION_ORDER.length : at;
  };
  return Object.entries(counts)
    .map(([option, count]) => ({ option, count }))
    .sort((a, b) => rank(a.option) - rank(b.option));
}

/** A part of the text of an agenda item: Markdown, or a decision that stood in it. */
export type TopPart =
  | { readonly kind: 'text'; readonly markdown: string }
  | { readonly kind: 'decision'; readonly decision: PublicDecision };

/** The head line of a vote callout; group 1 is the question. */
const CALLOUT_HEAD = /^>\s?\[!abstimmung\]\s*(.*)$/i;
/** The tally line of a vote callout (`yes: 5, no: 0, abstain: 1`). */
const TALLY_LINE = /^[\p{L}_\\]+:\s*\d+(\s*,\s*[\p{L}_\\]+:\s*\d+)*$/u;
/** A condition line of a vote callout; the decision box lists the conditions. */
const CONDITION_LINE = /^Auflage \d+:/;

/**
 * The question of a decision as the head line of its callout names it. Without a
 * question the server writes "Beschlussfrage" (a motion) or "Wahlgang" (an election),
 * and a runoff names its round (`build_vote_snippet`, `build_election_snippet`).
 */
function headQuestion(d: PublicDecision): string {
  const election = d.kind === 'election';
  const q = d.question?.trim() || (election ? 'Wahlgang' : 'Beschlussfrage');
  const round = d.round ?? 1;
  return election && round > 1 ? `${q} (${round}. Wahlgang)` : q;
}

/**
 * Split the text of an agenda item at the vote callouts (`> [!abstimmung] **Frage**`)
 * of its decisions with `inText`. The page shows such a callout as the same decision box
 * as a decision outside the text, with translated labels and the result, instead of the
 * raw tally line. A callout line that the box does not show (a note) stays as text below
 * the box. A callout without a matching decision stays Markdown.
 */
export function topParts(markdown: string, decisions: readonly PublicDecision[]): readonly TopPart[] {
  const lines = markdown.split('\n');
  const start: TopScan = { fence: false, skip: 0, blocks: [] };
  const { blocks } = lines.reduce((scan, _, i) => scanLine(scan, lines, i), start);
  const begin: TopSplit = { parts: [], text: [], open: decisions.filter((d) => d.inText) };
  const done = blocks.reduce(splitBlock, begin);
  return withText(done.parts, done.text);
}

/** A line of the text of an agenda item, or a vote callout with all its lines. */
type TopBlock =
  | { readonly kind: 'line'; readonly line: string }
  | { readonly kind: 'callout'; readonly question: string; readonly lines: readonly string[] };

/** The state of the line scan of `topParts`. A callout skips its lines up to `skip`. */
interface TopScan {
  readonly fence: boolean;
  readonly skip: number;
  readonly blocks: readonly TopBlock[];
}

/** The state of the split of `topParts`: the parts, the text not yet a part, the decisions left. */
interface TopSplit {
  readonly parts: readonly TopPart[];
  readonly text: readonly string[];
  readonly open: readonly PublicDecision[];
}

/**
 * Reads line `i`. A code fence (```) turns the callout detection off up to its end, and a
 * callout takes all the `>` lines that follow its head.
 */
function scanLine(scan: TopScan, lines: readonly string[], i: number): TopScan {
  if (i < scan.skip) return scan;
  const line = lines[i].trim();
  const fence = line.startsWith('```') ? !scan.fence : scan.fence;
  const head = fence ? null : CALLOUT_HEAD.exec(line);
  if (!head) return { ...scan, fence, blocks: [...scan.blocks, { kind: 'line', line: lines[i] }] };
  const after = lines.slice(i + 1).findIndex((l) => !l.trim().startsWith('>'));
  const end = after === -1 ? lines.length : i + 1 + after;
  const callout: TopBlock = { kind: 'callout', question: head[1], lines: lines.slice(i, end) };
  return { fence, skip: end, blocks: [...scan.blocks, callout] };
}

/**
 * Adds a block to the split. A callout of a decision left becomes a decision part; the
 * callout lines that the box does not show stay as text below it.
 */
function splitBlock(split: TopSplit, block: TopBlock): TopSplit {
  if (block.kind === 'line') return { ...split, text: [...split.text, block.line] };
  const question = normalizeQuestion(block.question);
  const at = split.open.findIndex((d) => normalizeQuestion(headQuestion(d)) === question);
  if (at === -1) return { ...split, text: [...split.text, ...block.lines] };
  const decision = split.open[at];
  const open = split.open.filter((_, k) => k !== at);
  const parts: readonly TopPart[] = [
    ...withText(split.parts, split.text),
    { kind: 'decision', decision },
  ];
  const rest =
    decision.kind === 'election'
      ? []
      : block.lines
          .slice(1)
          .map((l) => l.trim().replace(/^>\s?/, ''))
          .filter((l) => l && !TALLY_LINE.test(l) && !CONDITION_LINE.test(l));
  return { parts: withText(parts, rest), text: [], open };
}

/** The parts with the text as one more Markdown part, unless the text is blank. */
function withText(parts: readonly TopPart[], text: readonly string[]): readonly TopPart[] {
  const markdown = text.join('\n').trim();
  return markdown ? [...parts, { kind: 'text', markdown }] : parts;
}

/**
 * Keep search engines away from the page while it lives (`<meta name="robots"
 * content="noindex">`). The public protocol pages are reachable without a login, but
 * they are not meant for an index. Call it in the constructor of a page component.
 */
export function useNoindex(): void {
  const meta = inject(Meta);
  meta.updateTag({ name: 'robots', content: 'noindex' });
  inject(DestroyRef).onDestroy(() => meta.removeTag('name="robots"'));
}
