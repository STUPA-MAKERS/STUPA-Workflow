import { placeholdersOf, samePlaceholders } from './placeholders';

describe('placeholders', () => {
  it('lists each name once, sorted', () => {
    expect(placeholdersOf('{n} von {count}, {n}')).toEqual(['count', 'n']);
    expect(placeholdersOf('Keine')).toEqual([]);
  });

  it('compares the sets of two texts', () => {
    expect(samePlaceholders('{count} open', '{count} offen')).toBe(true);
    expect(samePlaceholders('open', '{count} offen')).toBe(false);
    expect(samePlaceholders('{count} {x}', '{count} offen')).toBe(false);
    expect(samePlaceholders('{x}', '{count}')).toBe(false);
  });
});
