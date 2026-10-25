import { formatDateRangeValue, formatFieldValue, formatIsoDate } from '@shared/forms/answer-format';
import { applicationTitle, formatBytes, isRejection, transitionLooks } from './applications.util';
import type { Transition } from '@core/api/models';

describe('applicationTitle', () => {
  it('prefers the first non-empty known title field', () => {
    expect(applicationTitle({ title: 'Fest' }, 'fallback')).toBe('Fest');
    expect(applicationTitle({ name: 'Beamer' }, 'fallback')).toBe('Beamer');
    expect(applicationTitle({ title: '  ', name: 'Beamer' }, 'fallback')).toBe('Beamer');
  });

  it('uses the fallback for missing/non-string titles or null data', () => {
    expect(applicationTitle({}, 'Ohne Titel')).toBe('Ohne Titel');
    expect(applicationTitle({ title: 42 }, 'Ohne Titel')).toBe('Ohne Titel');
    expect(applicationTitle(null, 'Ohne Titel')).toBe('Ohne Titel');
  });

  it('trims surrounding whitespace', () => {
    expect(applicationTitle({ title: '  Fest  ' }, 'fallback')).toBe('Fest');
  });
});

describe('formatFieldValue', () => {
  it('renders scalars directly', () => {
    expect(formatFieldValue('x')).toBe('x');
    expect(formatFieldValue(250)).toBe('250');
    expect(formatFieldValue(true)).toBe('true');
  });

  it('renders empty for null/undefined', () => {
    expect(formatFieldValue(null)).toBe('');
    expect(formatFieldValue(undefined)).toBe('');
  });

  it('JSON-stringifies objects and arrays', () => {
    expect(formatFieldValue({ a: 1 })).toBe('{"a":1}');
    expect(formatFieldValue([1, 2])).toBe('[1,2]');
  });
});

describe('formatIsoDate', () => {
  it('formats an ISO day in the active locale', () => {
    expect(formatIsoDate('2026-07-01', 'de')).toBe('01.07.2026');
    // en-GB, not en-US: 1 July reads as 01/07/2026, never as 07/01/2026.
    expect(formatIsoDate('2026-07-01', 'en')).toBe('01/07/2026');
  });

  it('keeps the entered day west of UTC', () => {
    // A date-only answer carries no zone. Read and printed in UTC it stays the
    // day the applicant entered, in every timezone.
    expect(formatIsoDate('2026-01-01', 'de')).toBe('01.01.2026');
    expect(formatIsoDate('2026-07-01T00:00:00Z', 'de')).toBe('01.07.2026');
  });

  it('keeps an unparsable or empty value instead of printing an invalid date', () => {
    expect(formatIsoDate('irgendwann', 'de')).toBe('irgendwann');
    expect(formatIsoDate('   ', 'de')).toBe('');
  });

  it('falls back to the plain value formatter for a non-string', () => {
    expect(formatIsoDate(42, 'de')).toBe('42');
    expect(formatIsoDate(null, 'de')).toBe('');
    expect(formatIsoDate({ a: 1 }, 'de')).toBe('{"a":1}');
  });
});

describe('formatDateRangeValue', () => {
  it('formats a full range as one span', () => {
    expect(formatDateRangeValue({ from: '2026-07-01', to: '2026-07-02' }, 'de')).toBe(
      '01.07.2026 \u2013 02.07.2026',
    );
  });

  it('formats a full range day-first under the English UI', () => {
    expect(formatDateRangeValue({ from: '2026-07-01', to: '2026-07-02' }, 'en')).toBe(
      '01/07/2026 \u2013 02/07/2026',
    );
  });

  it('shows the half a half-filled range has', () => {
    expect(formatDateRangeValue({ from: '2026-07-01' }, 'de')).toBe('01.07.2026');
    expect(formatDateRangeValue({ to: '2026-07-02' }, 'de')).toBe('02.07.2026');
    expect(formatDateRangeValue({ from: '  ', to: '2026-07-02' }, 'de')).toBe('02.07.2026');
  });

  it('gives an empty text for a range without an end', () => {
    expect(formatDateRangeValue({}, 'de')).toBe('');
    expect(formatDateRangeValue({ from: null, to: null }, 'de')).toBe('');
  });

  it('falls back to the plain value formatter for a non-object', () => {
    expect(formatDateRangeValue('2026-07-01', 'de')).toBe('2026-07-01');
    expect(formatDateRangeValue([1, 2], 'de')).toBe('[1,2]');
    expect(formatDateRangeValue(null, 'de')).toBe('');
  });
});

describe('formatBytes', () => {
  it('formats bytes/KB/MB with a binary base in the locale', () => {
    expect(formatBytes(0, 'de')).toBe('0 B');
    expect(formatBytes(512, 'de')).toBe('512 B');
    expect(formatBytes(1024, 'de')).toBe('1,0 KB');
    expect(formatBytes(1536, 'de')).toBe('1,5 KB');
    expect(formatBytes(1536, 'en')).toBe('1.5 KB');
    expect(formatBytes(1048576, 'de')).toBe('1,0 MB');
  });

  it('climbs through GB and TB units (loop body)', () => {
    // 1 GiB is 1024^3, so the unit index walks KB to MB to GB.
    expect(formatBytes(1024 ** 3, 'de')).toBe('1,0 GB');
    // 1 TiB is 1024^4, so the loop walks to the last unit.
    expect(formatBytes(1024 ** 4, 'de')).toBe('1,0 TB');
    // Above TB the unit stays at TB, because of the `unit < units.length - 1` guard.
    expect(formatBytes(1024 ** 5, 'de')).toBe('1.024,0 TB');
  });

  it('returns a dash for invalid sizes', () => {
    expect(formatBytes(-1, 'de')).toBe('—');
    expect(formatBytes(NaN, 'de')).toBe('—');
    expect(formatBytes(Infinity, 'de')).toBe('—');
  });
});

describe('transitionLooks', () => {
  const t = (id: string, color: string | null): Transition => ({
    id,
    fromStateId: 's1',
    toStateId: 's2',
    label: id,
    color,
    addsToAgenda: false,
    agendaGremiumId: null,
  });

  it('makes the first non-red transition the main action and the red ones danger', () => {
    const looks = transitionLooks([t('reject', '#d9534f'), t('agenda', null), t('more', '#e8a33d')]);
    expect([...looks]).toEqual([
      ['reject', 'danger'],
      ['agenda', 'fill'],
      ['more', 'tonal'],
    ]);
  });

  it('reads a red colour as a rejection and anything else as not', () => {
    expect(isRejection({ color: '#c0392b' })).toBe(true);
    expect(isRejection({ color: '#72a384' })).toBe(false);
    expect(isRejection({ color: null })).toBe(false);
  });
});
