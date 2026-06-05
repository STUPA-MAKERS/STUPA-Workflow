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
});
