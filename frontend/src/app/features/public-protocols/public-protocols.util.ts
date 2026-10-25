import { DestroyRef, inject } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import type { TranslationKey } from '@core/i18n/translations';
import { normalizeQuestion } from '../meetings/vote-result/vote-result';
import type { PublicDecision, PublicTopSummary, PublicVoteResult } from './public-protocols.models';

/** The parts of a semester key: `ws-2026` → winter 2026/27, `ss-2026` → summer 2026. */
export interface SemesterParts {
  kind: 'ws' | 'ss';
  year: number;
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
export function topCounts(tops: readonly PublicTopSummary[]): { decisions: number; nonPublic: number } {
  let decisions = 0;
  let nonPublic = 0;
  for (const top of tops) {
    if (top.nonPublic) nonPublic++;
    else decisions += top.results.length;
  }
  return { decisions, nonPublic };
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
export function orderedCounts(counts: Record<string, number>): { option: string; count: number }[] {
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
  | { kind: 'text'; markdown: string }
  | { kind: 'decision'; decision: PublicDecision };

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
export function topParts(markdown: string, decisions: readonly PublicDecision[]): TopPart[] {
  const open = decisions.filter((d) => d.inText);
  const parts: TopPart[] = [];
  let text: string[] = [];
  const flush = (): void => {
    const md = text.join('\n').trim();
    if (md) parts.push({ kind: 'text', markdown: md });
    text = [];
  };
  const lines = markdown.split('\n');
  let fence = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.startsWith('```')) fence = !fence;
    const head = fence ? null : CALLOUT_HEAD.exec(line);
    if (!head) {
      text.push(lines[i]);
      continue;
    }
    let end = i + 1;
    while (end < lines.length && lines[end].trim().startsWith('>')) end++;
    const question = normalizeQuestion(head[1]);
    const at = open.findIndex((d) => normalizeQuestion(headQuestion(d)) === question);
    if (at === -1) {
      text.push(...lines.slice(i, end));
    } else {
      const [decision] = open.splice(at, 1);
      flush();
      parts.push({ kind: 'decision', decision });
      if (decision.kind !== 'election') {
        const rest = lines
          .slice(i + 1, end)
          .map((l) => l.trim().replace(/^>\s?/, ''))
          .filter((l) => l && !TALLY_LINE.test(l) && !CONDITION_LINE.test(l));
        text.push(...rest);
        if (rest.length) flush();
      }
    }
    i = end - 1;
  }
  flush();
  return parts;
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
