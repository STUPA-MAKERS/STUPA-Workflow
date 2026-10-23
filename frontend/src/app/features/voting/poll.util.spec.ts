import type { PollConfig } from '@core/api/models';
import { de } from '@core/i18n/translations';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import {
  answersComplete,
  dateOptionLabel,
  draftDateLabel,
  draftOptions,
  emptyPollDraft,
  localMoment,
  pollAsElection,
  pollBars,
  pollCaption,
  pollChoiceLabel,
  pollChoiceLimit,
  pollCountText,
  pollDraftValid,
  pollInOf,
  pollLabelOf,
  pollOf,
  pollOptionLabel,
  pollStatus,
  pollTopLine,
  type PollDraft,
} from './poll.util';

/** The German texts with their parameters filled in. */
const t: Translate = (key: TranslationKey, params?: Record<string, string | number>) =>
  Object.entries(params ?? {}).reduce(
    (text, [k, v]) => text.replace(`{${k}}`, String(v)),
    de[key as keyof typeof de] as string,
  );

const TEXT: PollConfig = {
  mode: 'multi',
  options: [
    { id: 'o1', label: 'Pizza' },
    { id: 'o2', label: null },
  ],
  maxChoices: 1,
  secret: true,
};
const DATE: PollConfig = {
  mode: 'date',
  options: [{ id: 'o1', start: '2026-11-03T17:00:00Z', end: '2026-11-03T19:00:00Z' }],
  secret: false,
};

describe('poll.util', () => {
  it('reads the poll of a vote and its limit', () => {
    expect(pollOf(null)).toBeNull();
    expect(pollOf({ kind: 'election' })).toBeNull();
    expect(pollOf({ kind: 'poll' })).toBeNull();
    expect(pollOf({ kind: 'poll', poll: TEXT })).toBe(TEXT);
    expect(pollChoiceLimit({ ...TEXT, mode: 'single' })).toBe(1);
    expect(pollChoiceLimit(TEXT)).toBe(1);
    expect(pollChoiceLimit({ ...TEXT, maxChoices: null })).toBe(2);
    expect(pollAsElection(TEXT)).toEqual({
      seats: 1,
      candidates: [
        { id: 'o1', name: 'Pizza' },
        { id: 'o2', name: 'o2' },
      ],
      secret: true,
    });
  });

  it('labels the options, the captions, the status and the picks', () => {
    // A date shows in the time zone of the meetings, whatever the device: 16:00 UTC is 17:00 in Berlin.
    expect(dateOptionLabel('2026-11-04T16:00:00Z', null, 'de-DE')).toBe('Mi, 4.11. · 17:00');
    expect(dateOptionLabel('2026-11-04T16:00:00Z', null, 'en')).toBe('Wed, 4.11. · 17:00');
    expect(pollOptionLabel(DATE.options[0]!, 'de-DE')).toMatch(/^Di, 3\.11\. · \d\d:00–\d\d:00$/);
    expect(pollLabelOf(TEXT, 'o1', 'de-DE')).toBe('Pizza');
    expect(pollLabelOf(null, 'o9', 'de-DE')).toBe('o9');
    expect(pollCaption(DATE, t)).toBe('Terminumfrage');
    expect(pollCaption({ ...TEXT, mode: 'single' }, t)).toBe('Umfrage · Einzelwahl');
    expect(pollCaption(TEXT, t)).toBe('Umfrage · Mehrfachwahl, höchstens 1');
    expect(pollCaption({ ...TEXT, maxChoices: null }, t)).toBe('Umfrage · Mehrfachwahl');
    expect(pollChoiceLabel(TEXT, [], 'de-DE', t)).toBe('Enthaltung');
    expect(pollChoiceLabel(TEXT, ['o1', 'o2'], 'de-DE', t)).toBe('Pizza, o2');
    expect([0, 1, 3].map((n) => pollCountText(n, t))).toEqual(['Enthaltung', '1 Option', '3 Optionen']);
    expect(pollStatus('open')).toEqual({ kind: 'accent', key: 'poll.status.open' });
    expect(pollStatus('closed')).toEqual({ kind: 'accent', key: 'poll.status.closed' });
    expect(pollStatus('draft')).toBeNull();
  });

  it('needs an answer for every date', () => {
    expect(answersComplete(DATE, null)).toBe(false);
    expect(answersComplete(DATE, {})).toBe(false);
    expect(answersComplete(DATE, { o1: 'no' })).toBe(true);
  });

  it('builds the bars from a stored result, and the top line', () => {
    const bars = pollBars(
      TEXT,
      { counts: { o1: 2 }, abstentions: 3, ballots: 5, order: ['o9', 'o1'], top: ['o1'] },
      {},
      'de-DE',
      t,
    );
    // An order that misses an option falls back to the counts.
    expect(bars.map((b) => [b.id, b.count, b.top])).toEqual([
      ['o1', 2, true],
      ['o2', 0, false],
      ['abstain', 3, false],
    ]);
    expect(pollTopLine(TEXT, bars, t)).toBe('Meiste Stimmen: Pizza');
    const dates = pollBars(
      DATE,
      { counts: { o1: 1 }, abstentions: 0, ballots: 1, order: ['o1'], top: ['o1'] },
      {},
      'de-DE',
      t,
    );
    expect(dates.map((b) => b.maybe)).toEqual([0]);
    expect(pollTopLine(DATE, dates, t)).toMatch(/^Bester Termin: Di, 3\.11\./);
    expect(pollTopLine(DATE, [], t)).toBeNull();
  });

  describe('the editor draft', () => {
    const draft = (over: Partial<PollDraft>): PollDraft => ({ ...emptyPollDraft(), ...over });
    const text = (key: number, label: string) => ({ key, label, date: '', start: '', end: '' });
    const date = (key: number, d: string, start: string, end = '') => ({ key, label: '', date: d, start, end });

    it('keeps the options of each mode apart and checks the bounds', () => {
      const d = draft({ options: [text(1, 'A'), text(2, '  '), date(3, '2026-11-03', '18:00')] });
      expect(draftOptions(d).map((o) => o.key)).toEqual([1]);
      expect(draftOptions({ ...d, mode: 'date' }).map((o) => o.key)).toEqual([3]);
      expect(pollDraftValid(d)).toBe(false);
      expect(pollDraftValid({ ...d, options: [...d.options, text(4, 'B')] })).toBe(true);
      const many = Array.from({ length: 21 }, (_, i) => text(i, `O${i}`));
      expect(pollDraftValid(draft({ options: many }))).toBe(false);
    });

    it('builds the body of the server', () => {
      expect(localMoment('', '18:00')).toBeNull();
      expect(localMoment('2026-13-45', '18:00')).toBeNull();
      expect(localMoment('2026-11-03', '18:00')).toBe(new Date('2026-11-03T18:00').toISOString());
      const options = [text(1, ' A '), text(2, 'B'), date(3, '2026-11-03', '18:00', '20:00'), date(4, '2026-11-04', '17:00')];
      expect(pollInOf(draft({ mode: 'single', options }))).toEqual({
        mode: 'single',
        options: [{ label: 'A' }, { label: 'B' }],
      });
      expect(pollInOf(draft({ mode: 'multi', maxChoices: 5, options }))).toEqual({
        mode: 'multi',
        options: [{ label: 'A' }, { label: 'B' }],
        maxChoices: 2,
      });
      expect(pollInOf(draft({ mode: 'date', options }))).toEqual({
        mode: 'date',
        options: [
          {
            start: new Date('2026-11-03T18:00').toISOString(),
            end: new Date('2026-11-03T20:00').toISOString(),
          },
          { start: new Date('2026-11-04T17:00').toISOString() },
        ],
      });
    });

    it('labels a date of the list', () => {
      expect(draftDateLabel(date(1, '2026-11-03', '18:00', '20:00'), 'de-DE')).toBe('Di, 3.11. · 18:00–20:00');
      expect(draftDateLabel(date(2, '2026-11-03', '18:00'), 'de-DE')).toBe('Di, 3.11. · 18:00');
      expect(draftDateLabel(date(3, '2026-11-03', ''), 'de-DE')).toBe('2026-11-03');
    });
  });
});
