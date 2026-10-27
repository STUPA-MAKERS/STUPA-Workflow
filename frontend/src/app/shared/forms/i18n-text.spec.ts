import { i18nLabel, langFieldLabel, resolveI18n, sameI18n, setI18n, trimI18n } from './i18n-text';

describe('resolveI18n', () => {
  const map = { de: 'Titel', en: 'Title' };

  it('returns the requested language', () => {
    expect(resolveI18n(map, 'en')).toBe('Title');
    expect(resolveI18n(map, 'de')).toBe('Titel');
  });

  it('falls back along the chain, then to any value', () => {
    expect(resolveI18n(map, 'fr')).toBe('Title');
    expect(resolveI18n({ de: 'Titel' }, 'fr')).toBe('Titel');
    expect(resolveI18n({ ...map, fr: 'Titre' }, 'fr')).toBe('Titre');
    expect(resolveI18n({ en: 'Title' }, 'de')).toBe('Title');
    expect(resolveI18n({ fr: 'Titre' }, 'en')).toBe('Titre');
  });

  it('returns empty string for missing maps', () => {
    expect(resolveI18n(undefined, 'de')).toBe('');
    expect(resolveI18n(null, 'de')).toBe('');
    expect(resolveI18n({}, 'de')).toBe('');
  });

  /** The key exists (so `lang in map`), but the value is nullish, so the ?? guard gives ''. */
  it('coalesces a present-but-nullish requested-language value to empty string', () => {
    const nullish = { en: undefined } as unknown as Record<string, string>;
    expect(resolveI18n(nullish, 'en')).toBe('');
  });

  /**
   * The requested 'en' is missing and de is present but nullish. The result is '', and the lookup
   * does not fall through to fr.
   */
  it('coalesces a present-but-nullish de fallback value to empty string', () => {
    const nullish = { de: undefined, fr: 'Titre' } as unknown as Record<string, string>;
    expect(resolveI18n(nullish, 'en')).toBe('');
  });

  /** The requested 'en' and 'de' are missing, so the nullish first value hits the final ??. */
  it('coalesces a nullish first value to empty string', () => {
    const nullish = { fr: undefined } as unknown as Record<string, string>;
    expect(resolveI18n(nullish, 'en')).toBe('');
  });
});

describe('i18nLabel', () => {
  it('takes the first non-empty label of the chain, then the fallback', () => {
    expect(i18nLabel({ de: 'Kasse', en: 'Treasury' }, 'fr', 'k')).toBe('Treasury');
    expect(i18nLabel({ de: 'Kasse', en: '' }, 'fr', 'k')).toBe('Kasse');
    expect(i18nLabel({ en: 'Treasury' }, 'de', 'k')).toBe('k');
    expect(i18nLabel(null, 'en', 'k')).toBe('k');
  });
});

describe('the map helpers', () => {
  it('labels a field with its language code', () => {
    expect(langFieldLabel('Titel', 'pt-BR')).toBe('Titel (PT-BR)');
  });

  it('sets one language and drops an empty extra language', () => {
    expect(setI18n({ de: 'a' }, 'fr', 'b')).toEqual({ de: 'a', fr: 'b' });
    expect(setI18n({ de: 'a', fr: 'b' }, 'fr', '')).toEqual({ de: 'a' });
    expect(setI18n({ de: 'a', en: 'b' }, 'en', '')).toEqual({ de: 'a', en: '' });
    expect(setI18n(null, 'de', '')).toEqual({ de: '' });
  });

  it('compares two maps with a missing entry equal to an empty one', () => {
    expect(sameI18n({ de: 'a', en: '' }, { de: 'a' })).toBe(true);
    expect(sameI18n({ de: 'a' }, { de: 'a', fr: 'b' })).toBe(false);
    expect(sameI18n(null, undefined)).toBe(true);
  });

  it('trims the texts and drops the empty ones', () => {
    expect(trimI18n({ de: ' a ', en: ' ', fr: 'b' })).toEqual({ de: 'a', fr: 'b' });
    expect(trimI18n(undefined)).toEqual({});
  });
});
