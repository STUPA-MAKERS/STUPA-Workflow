import { CATALOG } from '@core/i18n/translations';
import { defaultSubmittedText, submittedMarkdown } from './submitted-texts';

describe('submitted texts', () => {
  it('gives the built-in text of each kind and language', () => {
    expect(defaultSubmittedText('internal', 'de')).toBe(CATALOG.de['apply.submitted.body']);
    expect(defaultSubmittedText('external', 'en')).toBe(CATALOG.en['apply.confirm.body']);
  });

  it('falls back to German and then to an empty text when a catalogue lacks the key', () => {
    const en = CATALOG.en;
    const de = CATALOG.de;
    const keepEn = en['apply.confirm.body'];
    const keepDe = de['apply.confirm.body'];
    try {
      delete en['apply.confirm.body'];
      expect(defaultSubmittedText('external', 'en')).toBe(keepDe);
      delete de['apply.confirm.body'];
      expect(defaultSubmittedText('external', 'en')).toBe('');
    } finally {
      en['apply.confirm.body'] = keepEn;
      de['apply.confirm.body'] = keepDe;
    }
  });

  it('takes the configured text of exactly the language, else the built-in one', () => {
    const map = { de: ' **Hallo** ', en: '' };
    expect(submittedMarkdown(map, 'internal', 'de')).toBe('**Hallo**');
    expect(submittedMarkdown(map, 'internal', 'en')).toBe(CATALOG.en['apply.submitted.body']);
    expect(submittedMarkdown({ de: 'x' }, 'external', 'en')).toBe(CATALOG.en['apply.confirm.body']);
    expect(submittedMarkdown(null, 'external', 'de')).toBe(CATALOG.de['apply.confirm.body']);
  });
});
