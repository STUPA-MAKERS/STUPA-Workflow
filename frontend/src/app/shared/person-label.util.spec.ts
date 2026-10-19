import { de, type Translate } from '@core/i18n/translations';
import { personLabel, personName } from './person-label.util';

const t: Translate = (key) => de[key];

describe('personLabel', () => {
  it('prefers the name, then the e-mail', () => {
    expect(personLabel({ displayName: 'Anna Antrag', email: 'anna@example.org' }, t)).toBe(
      'Anna Antrag',
    );
    expect(personLabel({ displayName: '', email: 'anna@example.org' }, t)).toBe('anna@example.org');
    expect(personLabel({ displayName: null, email: 'anna@example.org' }, t)).toBe(
      'anna@example.org',
    );
  });

  it('gives the fallback of the page for a person without name and e-mail', () => {
    expect(personLabel({ displayName: null, email: null }, t)).toBe('Ohne Namen');
    expect(personLabel(null, t, { fallback: 'admin.users.merge.unnamed' })).toBe(
      'Konto ohne Namen',
    );
    expect(personLabel(undefined, t, { fallbackText: '—' })).toBe('—');
    expect(personLabel({ displayName: '', email: '' }, t, { fallbackText: '' })).toBe('');
  });

  it('takes the I18nService as the translator', () => {
    const i18n = { translate: jest.fn(t) };
    expect(personLabel({}, i18n, { fallback: 'admin.gremien.unknownMember' })).toBe('(ohne Namen)');
    expect(i18n.translate).toHaveBeenCalledWith('admin.gremien.unknownMember');
  });
});

describe('personName', () => {
  it('names a person reference, a deleted one "Gelöschte Person"', () => {
    expect(personName({ principalId: 'p-1', displayName: 'Selin Yıldız' }, t)).toBe('Selin Yıldız');
    expect(personName({ principalId: null, displayName: null }, t)).toBe('Gelöschte Person');
    expect(personName(null, t)).toBe('Gelöschte Person');
  });
});
