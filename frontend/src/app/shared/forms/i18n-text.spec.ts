import { resolveI18n } from './i18n-text';

describe('resolveI18n', () => {
  const map = { de: 'Titel', en: 'Title' };

  it('returns the requested language', () => {
    expect(resolveI18n(map, 'en')).toBe('Title');
    expect(resolveI18n(map, 'de')).toBe('Titel');
  });

  it('falls back to de, then to any value', () => {
    expect(resolveI18n(map, 'fr')).toBe('Titel');
    expect(resolveI18n({ fr: 'Titre' }, 'en')).toBe('Titre');
  });

  it('returns empty string for missing maps', () => {
    expect(resolveI18n(undefined, 'de')).toBe('');
    expect(resolveI18n(null, 'de')).toBe('');
    expect(resolveI18n({}, 'de')).toBe('');
  });

  it('coalesces a present-but-nullish requested-language value to empty string', () => {
    // key exists (so `lang in map`) but value is null/undefined → '' via ?? guard.
    const nullish = { en: undefined } as unknown as Record<string, string>;
    expect(resolveI18n(nullish, 'en')).toBe('');
  });

  it('coalesces a present-but-nullish de fallback value to empty string', () => {
    const nullish = { de: undefined, fr: 'Titre' } as unknown as Record<string, string>;
    // requested 'en' missing → de present but nullish → '' (does NOT fall through to fr).
    expect(resolveI18n(nullish, 'en')).toBe('');
  });

  it('coalesces a nullish first value to empty string', () => {
    const nullish = { fr: undefined } as unknown as Record<string, string>;
    // requested 'en' missing, no 'de' → first value is nullish → '' via final ??.
    expect(resolveI18n(nullish, 'en')).toBe('');
  });
});
