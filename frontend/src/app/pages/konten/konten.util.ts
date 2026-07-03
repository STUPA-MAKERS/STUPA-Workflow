import type { TranslationKey } from '@core/i18n/translations';
import type { StatementLine } from '../budget/budget-tree.api';
import { problemCode } from '../budget/expense-display.util';

/** Split a counterparty into name + IBAN; banks sometimes prefix the name with the IBAN. */
export function splitCounterparty(l: StatementLine): { name: string; iban: string } {
  let iban = (l.counterpartyIban ?? '').trim();
  let name = (l.counterpartyName ?? '').trim();
  if (iban && name.startsWith(iban)) name = name.slice(iban.length).trim();
  else if (!iban) {
    const m = /^([A-Z]{2}\d{13,30})(.*)$/.exec(name);
    if (m) {
      iban = m[1];
      name = m[2].trim();
    }
  }
  return { name, iban };
}

const FINTS_ERROR_KEYS: Record<string, TranslationKey> = {
  fints_not_configured: 'fints.errNotConfigured',
  fints_no_credential: 'fints.errNoCredential',
  fints_pin_undecryptable: 'fints.errPin',
  fints_tan_expired: 'fints.errTanExpired',
  fints_bank_locked: 'fints.errBankLocked',
  fints_auth_rejected: 'fints.errAuthRejected',
};

/** Toast i18n key for a FinTS problem+json error (generic sync error fallback). */
export function fintsErrorKey(err: unknown): TranslationKey {
  const code = problemCode(err);
  return (code && FINTS_ERROR_KEYS[code]) || 'fints.errSync';
}

/** Only inline data-URL raster images may be shown as TAN challenge (no remote URLs). */
export function safeChallengeImage(img: string): string {
  return /^data:image\/(png|jpe?g|gif|webp);base64,/i.test(img) ? img : '';
}
