import type { SelectOption } from '@stupa-makers/ui-kit';

/** The twelve months by name in the given locale; the value is the number of the month. */
export function monthOptions(locale: string): readonly SelectOption[] {
  const name = new Intl.DateTimeFormat(locale, { month: 'long', timeZone: 'UTC' });
  return Array.from({ length: 12 }, (_, i) => ({
    value: String(i + 1),
    label: name.format(new Date(Date.UTC(2024, i, 1))),
  }));
}
