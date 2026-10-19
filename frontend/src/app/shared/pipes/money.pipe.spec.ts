import { TestBed } from '@angular/core/testing';
import { I18nService } from '@core/i18n/i18n.service';
import type { Locale } from '@core/i18n/translations';
import { MoneyPipe } from './money.pipe';

function pipeFor(locale: Locale): { pipe: MoneyPipe; i18n: I18nService } {
  return TestBed.runInInjectionContext(() => {
    const i18n = TestBed.inject(I18nService);
    i18n.setLocale(locale);
    return { pipe: new MoneyPipe(), i18n };
  });
}

describe('MoneyPipe', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
  });

  it('formats in the active format locale and follows a switch', () => {
    const { pipe, i18n } = pipeFor('de');
    expect(pipe.transform('119').replace(/\s/g, ' ')).toBe('119,00 €');
    i18n.setLocale('en');
    expect(pipe.transform('119')).toBe('€119.00');
  });

  it('passes the options on', () => {
    const { pipe } = pipeFor('en');
    expect(pipe.transform(1234.56, { whole: true, currency: 'EUR' })).toBe('€1,235');
    expect(pipe.transform(-3, { signed: true })).toBe('−€3.00');
  });

  it('gives an empty text without a number', () => {
    const { pipe } = pipeFor('de');
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform('x')).toBe('');
  });
});
