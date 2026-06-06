import { applicationTitle, formatFieldValue, stateBadgeVariant } from './applications.util';

describe('stateBadgeVariant', () => {
  it('maps the backend state categories', () => {
    expect(stateBadgeVariant('open')).toBe('info');
    expect(stateBadgeVariant('running')).toBe('warning');
    expect(stateBadgeVariant('closed')).toBe('neutral');
  });

  it('falls back to neutral for unknown/empty categories', () => {
    expect(stateBadgeVariant(undefined)).toBe('neutral');
    expect(stateBadgeVariant(null)).toBe('neutral');
    expect(stateBadgeVariant('weird')).toBe('neutral');
  });
});

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
