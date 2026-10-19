/**
 * The one money formatter of the app. Every amount on screen goes through it, in TS through
 * `formatMoney` and in a template through the `money` pipe.
 *
 * It takes the `Intl` format locale, `I18nService.formatLocale()` (`de-DE` / `en-GB`), never
 * the bare UI locale. Money is a decimal string in the API, so the number here is for the
 * display only. A missing value (null, undefined, '', a boolean) or one that is no finite
 * number gives `''`, so a caller decides what to show instead ("—", the raw text, a label).
 */

/** The options of {@link formatMoney}. */
export interface MoneyOptions {
  /** The ISO currency. Null or '' falls back to EUR. */
  currency?: string | null;
  /** Whole currency units: "1.235 €" (charts, the cost-centre tree). */
  whole?: boolean;
  /** Cents only where they are not zero: "42 €", but "1.234,50 €". */
  short?: boolean;
  /**
   * The sign in front of the magnitude: "+12,50 €", "−12,50 €" (a real minus). Zero gets
   * no sign.
   */
  signed?: boolean;
}

/** A value as a finite number, or null for no value or one that is no number. */
export function moneyNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string' || value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** An amount as money in the format locale ("1.250,00 €"), or `''` without a number. */
export function formatMoney(value: unknown, locale: string, options: MoneyOptions = {}): string {
  const n = moneyNumber(value);
  if (n === null) return '';
  const digits: Intl.NumberFormatOptions = options.whole
    ? { maximumFractionDigits: 0 }
    : options.short
      ? { minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2 }
      : {};
  const format = new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: options.currency || 'EUR',
    ...digits,
  });
  if (!options.signed) return format.format(n);
  const sign = n > 0 ? '+' : n < 0 ? '−' : '';
  return sign + format.format(Math.abs(n));
}
