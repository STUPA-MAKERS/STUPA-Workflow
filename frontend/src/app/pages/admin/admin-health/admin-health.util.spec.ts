import { TestBed } from '@angular/core/testing';
import { I18nService } from '@core/i18n/i18n.service';
import { checkedAt, formatBytes, formatCount, formatWhen, triggerLabel } from './admin-health.util';

describe('admin-health.util', () => {
  let i18n: I18nService;

  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    i18n = TestBed.inject(I18nService);
  });

  it('names today and yesterday, else the date', () => {
    const now = new Date(2026, 8, 29, 18, 0);
    expect(formatWhen(new Date(2026, 8, 29, 4, 30).toISOString(), i18n, now)).toBe('heute, 04:30');
    expect(formatWhen(new Date(2026, 8, 28, 17, 45).toISOString(), i18n, now)).toBe('gestern, 17:45');
    expect(formatWhen(new Date(2026, 8, 20, 9, 5).toISOString(), i18n, now)).toBe('20.09.2026, 09:05');
    // The default is the current time.
    expect(formatWhen(new Date().toISOString(), i18n)).toMatch(/^heute, /);
  });

  it('formats counts and sizes in the locale', () => {
    expect(formatCount(18412, i18n)).toBe('18.412');
    expect(formatBytes(null, i18n)).toBe('—');
    expect(formatBytes(undefined, i18n)).toBe('—');
    expect(formatBytes(512, i18n)).toBe('512 B');
    expect(formatBytes(433_061_888, i18n)).toBe('413 MB');
    expect(formatBytes(4.2 * 1024 ** 3, i18n)).toBe('4,2 GB');
    expect(formatBytes(1024 ** 5 * 3, i18n)).toBe('3.072 TB');
  });

  it('names the trigger and the time of a stored check', () => {
    expect(triggerLabel('cron', i18n)).toBe('nächtliche Prüfung');
    expect(triggerLabel('manual', i18n)).toBe('manuelle Prüfung');
    expect(triggerLabel('restore', i18n)).toBe('Prüfung nach dem Zurücksetzen');
    const base = {
      id: 'x',
      startedAt: 'a',
      valid: true,
      checked: 1,
      brokenAt: null,
      reason: null,
      trigger: 'cron' as const,
      triggeredBy: null,
    };
    expect(checkedAt({ ...base, finishedAt: 'b' })).toBe('b');
    expect(checkedAt({ ...base, finishedAt: null })).toBe('a');
  });
});
