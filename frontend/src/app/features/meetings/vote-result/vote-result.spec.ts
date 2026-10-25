import { de } from '@core/i18n/translations';
import type { TranslationKey } from '@core/i18n/translations';
import { vote } from '../../../../testing/meeting-fixtures';
import { normalizeQuestion, voteResultInfo, voteResultResolver } from './vote-result';

/** The German catalog with `{param}` filled in. */
function t(key: TranslationKey, params: Record<string, string | number> = {}): string {
  const text = (de as Record<string, string>)[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, k: string) => String(params[k] ?? ''));
}

const closed = vote({
  status: 'closed',
  result: 'passed',
  counts: { yes: 15, no: 3, abstain: 2 },
  majorityRule: 'simple',
  closedAt: '2026-09-29T16:52:00Z',
});

describe('voteResultInfo', () => {
  it('captions a decision with the close time and the majority rule', () => {
    const info = voteResultInfo(closed, t, 'de');
    expect(info.caption).toMatch(/^Beschluss · \d\d:52 · Einfache Mehrheit$/);
    expect(info.result).toEqual({ label: 'Angenommen', tone: 'passed' });
    expect(info.labels).toEqual({ yes: 'Ja', no: 'Nein', abstain: 'Enthaltung', result: 'Ergebnis' });
  });

  it('calls a tie and every other result a rejection', () => {
    for (const result of ['tie', 'rejected', null]) {
      expect(voteResultInfo({ ...closed, result }, t, 'de').result).toEqual({ label: 'Abgelehnt', tone: 'rejected' });
    }
  });

  it('leaves out what it does not know and names no result before the close', () => {
    const info = voteResultInfo(vote({ status: 'open' }), t, 'de');
    expect(info.caption).toBe('Beschluss');
    expect(info.result).toBeNull();
  });
});

describe('voteResultResolver', () => {
  it('finds a closed vote of the meeting by its question, also when escaped or bold', () => {
    const resolve = voteResultResolver(
      [closed, vote({ id: 'v-2', status: 'open', question: 'Offen?' })],
      t,
      'de',
    );
    expect(resolve('Wird der Nachtragshaushalt beschlossen?')?.result?.label).toBe('Angenommen');
    expect(resolve('**Wird  der Nachtragshaushalt beschlossen?**')?.result?.label).toBe('Angenommen');
    // An open vote and a vote of another meeting stay plain.
    expect(resolve('Offen?')).toBeNull();
    expect(resolve('Ganz andere Frage?')).toBeNull();
  });

  it('falls back to the title of a vote without a question, as the snippet does', () => {
    const resolve = voteResultResolver([{ ...closed, question: null, title: 'Antrag A' }], t, 'de');
    expect(resolve('Antrag A')).not.toBeNull();
    expect(voteResultResolver([{ ...closed, question: null, title: null }], t, 'de')('Beschlussfrage')).toBeNull();
  });

  it('keeps the two rounds of an election apart', () => {
    const election = {
      ...closed,
      kind: 'election' as const,
      question: 'Vorsitz',
      result: 'runoff',
      election: { seats: 1, candidates: [], secret: true },
    } as unknown as typeof closed;
    const runoff = { ...election, id: 'v-run', round: 2, result: 'elected' } as typeof closed;
    const resolve = voteResultResolver([election, runoff], t, 'de');
    expect(resolve('Vorsitz')?.result?.label).not.toBe(resolve('Vorsitz (2. Wahlgang)')?.result?.label);
    expect(resolve('Vorsitz (2. Wahlgang)')).not.toBeNull();
  });

  it('tells two polls with one question apart by the kind line of the card', () => {
    const base = { ...closed, kind: 'poll' as const, question: 'Test für TOP', result: null };
    const multi = {
      ...base,
      id: 'p-multi',
      poll: { mode: 'multi', maxChoices: 2, options: [], secret: false },
    } as unknown as typeof closed;
    const date = {
      ...base,
      id: 'p-date',
      poll: { mode: 'date', maxChoices: null, options: [], secret: false },
    } as unknown as typeof closed;
    const resolve = voteResultResolver([date, multi], t, 'de');
    expect(resolve('Test für TOP', ['Terminumfrage'])?.caption).toMatch(/^Terminumfrage/);
    expect(resolve('Test für TOP', ['Umfrage · Mehrfachwahl, höchstens 2'])?.caption).toMatch(/Mehrfachwahl/);
    // Without a matching kind line the last vote wins.
    expect(resolve('Test für TOP')?.caption).toMatch(/Mehrfachwahl/);
  });

  it('tells an election from a poll with the same question by its kind line', () => {
    const base = { ...closed, question: 'Test für TOP', result: null };
    const election = {
      ...base,
      id: 'e-1',
      kind: 'election' as const,
      result: 'elected',
      election: { seats: 2, candidates: [], secret: false },
    } as unknown as typeof closed;
    const poll = {
      ...base,
      id: 'p-multi',
      kind: 'poll' as const,
      poll: { mode: 'multi', maxChoices: 2, options: [], secret: false },
    } as unknown as typeof closed;
    const resolve = voteResultResolver([election, poll], t, 'de');
    expect(resolve('Test für TOP', ['Wahl · 2 Posten'])?.caption).toMatch(/^Wahl/);
    expect(resolve('Test für TOP', ['Umfrage · Mehrfachwahl, höchstens 2'])?.caption).toMatch(/^Umfrage/);
  });

  it('normalizes the text of a question', () => {
    expect(normalizeQuestion(' **A\\_b**  `c` ')).toBe('a_b c');
  });
});
