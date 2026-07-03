import type { StatementLine } from '../budget/budget-tree.api';
import { fintsErrorKey, safeChallengeImage, splitCounterparty } from './konten.util';

const LINE: StatementLine = {
  id: 'l-1',
  accountId: 'a-1',
  amount: '-42.00',
  kind: 'expense',
  currency: 'EUR',
  bookingDate: null,
  valueDate: null,
  purpose: null,
  counterpartyName: null,
  counterpartyIban: null,
  endToEndId: null,
  reference: null,
  matchState: 'unmatched',
  suggestedBudgetId: null,
  suggestedPathKey: null,
  suggestedExpenseId: null,
  createdAt: '2026-05-03T00:00:00Z',
};

describe('konten.util', () => {
  it('splitCounterparty strips an IBAN prefix from the name', () => {
    expect(
      splitCounterparty({
        ...LINE,
        counterpartyIban: 'DE02120300000000202051',
        counterpartyName: 'DE02120300000000202051 Max Muster',
      }),
    ).toEqual({ name: 'Max Muster', iban: 'DE02120300000000202051' });
  });

  it('splitCounterparty extracts an IBAN embedded in the name', () => {
    expect(
      splitCounterparty({
        ...LINE,
        counterpartyName: 'DE02120300000000202051 Erika Muster',
      }),
    ).toEqual({ name: 'Erika Muster', iban: 'DE02120300000000202051' });
    expect(splitCounterparty({ ...LINE, counterpartyName: 'Copyshop' })).toEqual({
      name: 'Copyshop',
      iban: '',
    });
    expect(splitCounterparty(LINE)).toEqual({ name: '', iban: '' });
  });

  it('fintsErrorKey maps known codes and falls back generically', () => {
    expect(fintsErrorKey({ error: { code: 'fints_bank_locked' } })).toBe('fints.errBankLocked');
    expect(fintsErrorKey({ error: { code: 'fints_tan_expired' } })).toBe('fints.errTanExpired');
    expect(fintsErrorKey({ error: { code: 'nope' } })).toBe('fints.errSync');
    expect(fintsErrorKey(undefined)).toBe('fints.errSync');
  });

  it('safeChallengeImage accepts only base64 data-URL raster images', () => {
    expect(safeChallengeImage('data:image/png;base64,QUJD')).toBe('data:image/png;base64,QUJD');
    expect(safeChallengeImage('https://evil.example/x.png')).toBe('');
    expect(safeChallengeImage('')).toBe('');
  });
});
