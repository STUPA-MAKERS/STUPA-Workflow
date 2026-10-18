import { formatBytes } from './format-bytes';

describe('formatBytes', () => {
  it('gives a dash for an invalid size in every style', () => {
    for (const bad of [null, undefined, -1, Number.NaN, Infinity]) {
      expect(formatBytes(bad, 'de-DE')).toBe('—');
      expect(formatBytes(bad, 'de-DE', 'file')).toBe('—');
      expect(formatBytes(bad, 'de-DE', 'fixed')).toBe('—');
    }
  });

  it('formats uploads as whole KB, else MB with at most one decimal', () => {
    expect(formatBytes(0, 'de-DE', 'file')).toBe('0 KB');
    expect(formatBytes(1, 'de-DE', 'file')).toBe('1 KB');
    expect(formatBytes(212 * 1024 + 300, 'de-DE', 'file')).toBe('212 KB');
    expect(formatBytes(1.5 * 1024 * 1024, 'de-DE', 'file')).toBe('1,5 MB');
    expect(formatBytes(1.5 * 1024 * 1024, 'en-GB', 'file')).toBe('1.5 MB');
    expect(formatBytes(50 * 1024 * 1024, 'de-DE', 'file')).toBe('50 MB');
  });

  it('formats storage with one decimal below 10, else whole numbers', () => {
    expect(formatBytes(512, 'de-DE')).toBe('512 B');
    expect(formatBytes(433_061_888, 'de-DE', 'storage')).toBe('413 MB');
    expect(formatBytes(4.2 * 1024 ** 3, 'de-DE')).toBe('4,2 GB');
    expect(formatBytes(4.2 * 1024 ** 3, 'en-GB')).toBe('4.2 GB');
    expect(formatBytes(1024 ** 5 * 3, 'de-DE')).toBe('3.072 TB');
  });

  it('formats the fixed style with one decimal from KB up', () => {
    expect(formatBytes(1023, 'de-DE', 'fixed')).toBe('1.023 B');
    expect(formatBytes(25 * 1024 * 1024, 'de-DE', 'fixed')).toBe('25,0 MB');
    expect(formatBytes(25 * 1024 * 1024, 'en-GB', 'fixed')).toBe('25.0 MB');
  });
});
