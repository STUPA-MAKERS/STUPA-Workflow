import { de } from '@core/i18n/translations';
import type { TranslationKey } from '@core/i18n/translations';
import {
  MAX_CONDITIONS,
  MAX_CONDITION_LENGTH,
  cleanConditions,
  conditionCount,
  decisionHistoryLine,
  decisionQuestion,
  draftError,
  emptyDraft,
  formatDiff,
  formatMoney,
  toProposal,
} from './decision.util';

/** The DE catalog with `{param}` replacement, as the I18nService does it. */
const t = (key: TranslationKey, params?: Record<string, string | number>): string =>
  Object.entries(params ?? {}).reduce(
    (text, [k, v]) => text.replaceAll(`{${k}}`, String(v)),
    de[key] as string,
  );

/** Intl puts a no-break space before the euro sign. */
const norm = (s: string) => s.replace(/\u00a0/g, ' ');

describe('decision.util', () => {
  it('starts a draft switched off with the requested amount', () => {
    expect(emptyDraft('1250.00')).toEqual({ enabled: false, amount: '1250.00', conditions: [] });
    expect(emptyDraft(null).amount).toBe('');
    expect(emptyDraft(undefined).amount).toBe('');
  });

  it('cleans the conditions', () => {
    expect(cleanConditions(['  a ', '', '   ', 'b'])).toEqual(['a', 'b']);
  });

  describe('draftError', () => {
    const on = (amount: string, conditions: string[] = []) => ({ enabled: true, amount, conditions });

    it('has no error when switched off or valid', () => {
      expect(draftError({ enabled: false, amount: 'x', conditions: [] }, '10')).toBeNull();
      expect(draftError(on('8.5', ['a']), '10')).toBeNull();
      expect(draftError(on(''), '10')).toBeNull();
    });

    it.each([['0'], ['-1'], ['1.001'], ['abc']])('refuses the amount %s', (amount) => {
      expect(draftError(on(amount), '10')).toBe('decision.error.amountInvalid');
    });

    it('refuses an amount without a requested amount and one above it', () => {
      expect(draftError(on('5'), null)).toBe('decision.error.amountInvalid');
      expect(draftError(on('10.01'), '10')).toBe('decision.error.amountExceeds');
    });

    it('refuses too many and too long conditions', () => {
      const many = Array.from({ length: MAX_CONDITIONS + 1 }, (_, i) => `c${i}`);
      expect(draftError(on('', many), '10')).toBe('decision.error.conditionCount');
      expect(draftError(on('', ['x'.repeat(MAX_CONDITION_LENGTH + 1)]), '10')).toBe(
        'decision.error.conditionLength',
      );
    });
  });

  describe('toProposal', () => {
    it('gives null when off or without a deviation', () => {
      expect(toProposal({ enabled: false, amount: '5', conditions: ['a'] }, '10')).toBeNull();
      expect(toProposal({ enabled: true, amount: '10.00', conditions: [' '] }, '10')).toBeNull();
    });

    it('sends a deviating amount and the clean conditions', () => {
      expect(toProposal({ enabled: true, amount: '8', conditions: [' a ', ''] }, '10')).toEqual({
        approvedAmount: '8',
        conditions: ['a'],
      });
      expect(toProposal({ enabled: true, amount: '', conditions: ['a'] }, '10')).toEqual({
        approvedAmount: null,
        conditions: ['a'],
      });
    });
  });

  it('formats money and the difference', () => {
    expect(norm(formatMoney('1250', 'de-DE'))).toBe('1.250,00 €');
    expect(norm(formatMoney(5, 'de-DE', null))).toBe('5,00 €');
    expect(formatMoney(null, 'de-DE')).toBe('');
    expect(formatMoney('x', 'de-DE')).toBe('');
    expect(norm(formatDiff('1250', '900', 'de-DE'))).toBe('−350,00 €');
    expect(norm(formatDiff('900', '1250', 'de-DE'))).toBe('+350,00 €');
    expect(formatDiff('10', '10', 'de-DE')).toBe('');
    expect(formatDiff(null, '10', 'de-DE')).toBe('');
  });

  it('counts the conditions in words', () => {
    expect(conditionCount(1, t)).toBe('1 Auflage');
    expect(conditionCount(3, t)).toBe('3 Auflagen');
  });

  describe('decisionQuestion', () => {
    it('keeps the plain question without a proposal', () => {
      expect(decisionQuestion('Party', null, '10', 'de-DE', t)).toBe(
        'Soll der Antrag „Party“ wie beschrieben gefördert werden?',
      );
    });

    it('names the amount and the conditions', () => {
      expect(
        norm(decisionQuestion('Hütte', { approvedAmount: '900', conditions: ['a', 'b'] }, '1250', 'de-DE', t)),
      ).toBe('Soll der Antrag „Hütte“ mit 900,00 € (beantragt 1.250,00 €) und 2 Auflagen gefördert werden?');
      expect(norm(decisionQuestion('Hütte', { approvedAmount: '900', conditions: [] }, '1250', 'de-DE', t))).toBe(
        'Soll der Antrag „Hütte“ mit 900,00 € (beantragt 1.250,00 €) gefördert werden?',
      );
      expect(decisionQuestion('Hütte', { approvedAmount: null, conditions: ['a'] }, '1250', 'de-DE', t)).toBe(
        'Soll der Antrag „Hütte“ mit 1 Auflage gefördert werden?',
      );
    });
  });

  describe('decisionHistoryLine', () => {
    const base = { requestedAmount: '1250', approvedAmount: '900', amountDeviates: true, conditionCount: 0 };

    it('names the amounts and the conditions', () => {
      expect(norm(decisionHistoryLine(base, 'de-DE', 'EUR', t) ?? '')).toBe(
        'Mit Abweichungen: 900,00 € statt 1.250,00 €',
      );
      expect(norm(decisionHistoryLine({ ...base, conditionCount: 2 }, 'de-DE', 'EUR', t) ?? '')).toBe(
        'Mit Abweichungen: 900,00 € statt 1.250,00 €, 2 Auflagen',
      );
      expect(
        decisionHistoryLine({ ...base, amountDeviates: false, conditionCount: 1 }, 'de-DE', 'EUR', t),
      ).toBe('Mit Abweichungen: 1 Auflage');
    });

    it('gives null for a decision as requested', () => {
      expect(decisionHistoryLine({ ...base, amountDeviates: false }, 'de-DE', 'EUR', t)).toBeNull();
    });
  });
});
