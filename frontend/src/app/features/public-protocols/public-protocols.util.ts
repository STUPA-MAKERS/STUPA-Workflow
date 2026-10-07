import { DestroyRef, inject } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import type { TranslationKey } from '@core/i18n/translations';
import type { PublicTopSummary, PublicVoteResult } from './public-protocols.models';

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

/**
 * A meeting date (`YYYY-MM-DD`) as a local date at noon. `new Date('2026-09-29')` is
 * midnight UTC, which is the day before west of Greenwich; noon stays on the day.
 */
export function meetingDate(date: string): Date {
  return new Date(`${date}T12:00:00`);
}

/** "Di, 29.09.2026" in the format locale. */
export function longDate(date: string, locale: string): string {
  const d = meetingDate(date);
  if (Number.isNaN(d.getTime())) return '';
  const weekday = d.toLocaleDateString(locale, { weekday: 'short' }).replace('.', '');
  const day = d.toLocaleDateString(locale, { day: '2-digit', month: '2-digit', year: 'numeric' });
  return `${weekday}, ${day}`;
}

/** "02.10.2026" of a timestamp in the format locale, or empty. */
export function shortDate(iso: string | null, locale: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(locale, { day: '2-digit', month: '2-digit', year: 'numeric' });
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
