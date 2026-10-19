import { formatMoney, moneyNumber } from './format-money';

const plain = (s: string): string => s.replace(/\s/g, ' ');

describe('formatMoney', () => {
  it('formats euro in both locales', () => {
    expect(plain(formatMoney('1250', 'de-DE'))).toBe('1.250,00 €');
    expect(formatMoney(12, 'en-GB')).toBe('€12.00');
    expect(plain(formatMoney(-42.5, 'de-DE'))).toBe('-42,50 €');
  });

  it('takes the currency and falls back to EUR', () => {
    expect(formatMoney(5, 'en-GB', { currency: 'USD' })).toBe('US$5.00');
    expect(plain(formatMoney(5, 'de-DE', { currency: null }))).toBe('5,00 €');
    expect(plain(formatMoney(5, 'de-DE', { currency: '' }))).toBe('5,00 €');
  });

  it('gives an empty text without a number', () => {
    for (const v of [null, undefined, '', '  ', 'abc', true, Infinity, NaN, {}]) {
      expect(formatMoney(v, 'de-DE')).toBe('');
    }
  });

  it('rounds to whole units', () => {
    expect(plain(formatMoney(1234.56, 'de-DE', { whole: true }))).toBe('1.235 €');
    expect(formatMoney(2500, 'en-GB', { whole: true })).toBe('€2,500');
  });

  it('shows cents only where they are not zero', () => {
    expect(plain(formatMoney(42, 'de-DE', { short: true }))).toBe('42 €');
    expect(plain(formatMoney('1234.5', 'de-DE', { short: true }))).toBe('1.234,50 €');
  });

  it('puts the sign in front of the magnitude', () => {
    expect(plain(formatMoney(-350, 'de-DE', { signed: true }))).toBe('−350,00 €');
    expect(formatMoney('12.5', 'en-GB', { signed: true })).toBe('+€12.50');
    expect(plain(formatMoney(0, 'de-DE', { signed: true }))).toBe('0,00 €');
  });

  it('reads a number from a value', () => {
    expect(moneyNumber('1.5')).toBe(1.5);
    expect(moneyNumber(3)).toBe(3);
    expect(moneyNumber(' ')).toBeNull();
    expect(moneyNumber(NaN)).toBeNull();
    expect(moneyNumber(false)).toBeNull();
  });
});
