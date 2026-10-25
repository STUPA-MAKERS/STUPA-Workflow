import { SimplifyPathPipe, simplifyPathKey } from './budget-path';

/**
 * These pin the PASS-THROUGH deliberately.
 *
 * A path key comes out exactly as it went in, including the shapes a collapsing
 * implementation would shorten. Collapsing numeric prefix chains is unstable — the same
 * path shortens differently depending on how the cost centres happen to be numbered —
 * and these cases keep it from creeping back.
 */
describe('simplifyPathKey', () => {
  /**
   * The first three shapes are the ones that a collapsing implementation shortens; the rest have no
   * chain to collapse.
   */
  it.each([
    'VSM-8-81-810-330',
    'VSM-6-60-120',
    '8-81-810',
    'VSM-800-04',
    'VSM-81-82',
    'VSM-9-81',
    'VSM-1',
    'VSM',
    '',
  ])('returns %p unchanged', (path) => {
    expect(simplifyPathKey(path)).toBe(path);
  });
});

describe('SimplifyPathPipe', () => {
  const pipe = new SimplifyPathPipe();

  it('passes a path through untouched', () => {
    expect(pipe.transform('VSM-8-81-810-330')).toBe('VSM-8-81-810-330');
  });

  it('renders nothing for a missing path, so a cell shows no stray text', () => {
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
    expect(pipe.transform('')).toBe('');
  });
});
