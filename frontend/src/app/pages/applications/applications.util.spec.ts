import {
  applicationTitle,
  formatBytes,
  formatFieldValue,
  scanBadgeVariant,
} from './applications.util';
import type { ScanState } from '@core/api/models';

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

describe('scanBadgeVariant', () => {
  it('maps each scan state to a badge variant', () => {
    expect(scanBadgeVariant('scanning')).toBe('warning');
    expect(scanBadgeVariant('clean')).toBe('success');
    expect(scanBadgeVariant('quarantined')).toBe('danger');
  });

  it('falls back to neutral for an unknown/pending scan state', () => {
    // covers the `default` arm of the switch (e.g. "pending" before scanning starts)
    expect(scanBadgeVariant('pending' as ScanState)).toBe('neutral');
  });
});

describe('formatBytes', () => {
  it('formats bytes/KB/MB with a binary base', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(1048576)).toBe('1.0 MB');
  });

  it('climbs through GB and TB units (loop body)', () => {
    // 1 GiB = 1024^3 → unit index walks KB→MB→GB
    expect(formatBytes(1024 ** 3)).toBe('1.0 GB');
    // 1 TiB = 1024^4 → walks to the last unit (loop stops at units.length - 1)
    expect(formatBytes(1024 ** 4)).toBe('1.0 TB');
    // beyond TB the unit stays at TB (loop guard `unit < units.length - 1`)
    expect(formatBytes(1024 ** 5)).toBe('1024.0 TB');
  });

  it('returns a dash for invalid sizes', () => {
    expect(formatBytes(-1)).toBe('—');
    expect(formatBytes(NaN)).toBe('—');
    expect(formatBytes(Infinity)).toBe('—');
  });
});
