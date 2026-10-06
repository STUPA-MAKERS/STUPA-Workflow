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

  it('calls a tie and every other result a rejection (O18)', () => {
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

  it('normalizes the text of a question', () => {
    expect(normalizeQuestion(' **A\\_b**  `c` ')).toBe('a_b c');
  });
});
