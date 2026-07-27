import { SimplifyPathPipe, simplifyPathKey } from './budget-path';

describe('simplifyPathKey', () => {
  it('collapses numeric prefix chains, keeping the top + leaf segments', () => {
    expect(simplifyPathKey('VSM-8-81-810-330')).toBe('VSM-810-330');
    expect(simplifyPathKey('VSM-6-60-120')).toBe('VSM-60-120');
  });

  it('keeps the top-level segment even when the next is a prefix-extension', () => {
    expect(simplifyPathKey('8-81-810')).toBe('8-810');
  });

  it('leaves non-prefix paths unchanged', () => {
    expect(simplifyPathKey('VSM-800-04')).toBe('VSM-800-04');
    expect(simplifyPathKey('VSM-1')).toBe('VSM-1');
  });

  it('returns a single segment untouched', () => {
    expect(simplifyPathKey('VSM')).toBe('VSM');
  });

  it('does not collapse when the next segment is equal length (not longer)', () => {
    expect(simplifyPathKey('VSM-81-82')).toBe('VSM-81-82');
  });

  it('does not collapse when the next does not start with the current segment', () => {
    expect(simplifyPathKey('VSM-9-81')).toBe('VSM-9-81');
  });

  it('handles an empty string (single empty segment)', () => {
    expect(simplifyPathKey('')).toBe('');
  });
});

describe('SimplifyPathPipe', () => {
  const pipe = new SimplifyPathPipe();

  it('delegates to simplifyPathKey for a non-empty path', () => {
    expect(pipe.transform('VSM-8-81-810-330')).toBe('VSM-810-330');
  });

  it('returns empty string for null', () => {
    expect(pipe.transform(null)).toBe('');
  });

  it('returns empty string for undefined', () => {
    expect(pipe.transform(undefined)).toBe('');
  });

  it('returns empty string for an empty path (falsy short-circuit)', () => {
    expect(pipe.transform('')).toBe('');
  });
});
