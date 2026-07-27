import { TestBed } from '@angular/core/testing';
import { LocalizedDatePipe } from './localized-date.pipe';
import { I18nService } from './i18n.service';
import type { Locale } from './translations';

/** Run the pipe in an injection context with the chosen locale. */
function pipeFor(locale: Locale): LocalizedDatePipe {
  return TestBed.runInInjectionContext(() => {
    const i18n = TestBed.inject(I18nService);
    i18n.setLocale(locale);
    return new LocalizedDatePipe();
  });
}

describe('LocalizedDatePipe', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
  });

  it('returns an empty string for null, undefined and empty input', () => {
    const pipe = pipeFor('de');
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
    expect(pipe.transform('')).toBe('');
  });

  it('returns an empty string for an unparseable date', () => {
    const pipe = pipeFor('de');
    expect(pipe.transform('not-a-date')).toBe('');
    expect(pipe.transform(NaN)).toBe('');
  });

  it('formats a Date instance directly (no re-construction)', () => {
    const pipe = pipeFor('de');
    const date = new Date('2026-06-16T09:05:00Z');
    const out = pipe.transform(date, 'mediumDate');
    // The de-DE medium date contains the year. The rest depends on the locale data.
    expect(out).toContain('2026');
    expect(out).not.toBe('');
  });

  it('parses string and number inputs into dates', () => {
    const pipe = pipeFor('de');
    expect(pipe.transform('2026-06-16T09:05:00Z', 'mediumDate')).toContain('2026');
    const epoch = new Date('2026-06-16T09:05:00Z').getTime();
    expect(pipe.transform(epoch, 'mediumDate')).toContain('2026');
  });

  it('uses en-US formatting for the English locale', () => {
    const pipe = pipeFor('en');
    const out = pipe.transform('2026-01-05T12:00:00Z', 'mediumDate');
    // The en-US medium date shows the month name in English (for example "Jan 5, 2026").
    expect(out).toMatch(/Jan/);
  });

  it('uses de-DE formatting for the German locale', () => {
    const pipe = pipeFor('de');
    const out = pipe.transform('2026-01-05T12:00:00Z', 'mediumDate');
    // de-DE puts the day before the month and joins them with dots (for example "05.01.2026").
    expect(out).toMatch(/\d{2}\.\d{2}\.\d{4}/);
  });

  it('defaults to the medium format (date + time) when none is given', () => {
    const pipe = pipeFor('de');
    const def = pipe.transform('2026-06-16T09:05:00Z');
    const explicit = pipe.transform('2026-06-16T09:05:00Z', 'medium');
    expect(def).toBe(explicit);
    // The medium format includes a time part (":").
    expect(def).toContain(':');
  });

  it('supports every declared format preset', () => {
    const pipe = pipeFor('de');
    const v = '2026-06-16T09:05:00Z';
    for (const fmt of ['short', 'medium', 'mediumDate', 'long', 'time'] as const) {
      expect(pipe.transform(v, fmt)).not.toBe('');
    }
    // The time preset drops the year.
    expect(pipe.transform(v, 'time')).not.toContain('2026');
    // The mediumDate preset drops the time separator.
    expect(pipe.transform(v, 'mediumDate')).not.toContain(':');
  });
});
