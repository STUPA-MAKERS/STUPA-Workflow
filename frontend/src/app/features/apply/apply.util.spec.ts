import { formatSize, shortRef } from './apply.util';

describe('apply.util', () => {
  it('formats sizes in whole KB and MB with one decimal', () => {
    expect(formatSize(0, 'de-DE')).toBe('0 KB');
    expect(formatSize(512, 'de-DE')).toBe('1 KB');
    expect(formatSize(212 * 1024 + 300, 'de-DE')).toBe('212 KB');
    expect(formatSize(1.5 * 1024 * 1024, 'de-DE')).toBe('1,5 MB');
    expect(formatSize(50 * 1024 * 1024, 'en-GB')).toBe('50 MB');
    expect(formatSize(-1, 'de-DE')).toBe('—');
    expect(formatSize(Number.NaN, 'de-DE')).toBe('—');
  });

  it('gives the 8-character reference in upper case', () => {
    expect(shortRef('3f9a2c71-aaaa-bbbb')).toBe('3F9A2C71');
    expect(shortRef('abc')).toBe('ABC');
    expect(shortRef(null)).toBe('');
  });
});
