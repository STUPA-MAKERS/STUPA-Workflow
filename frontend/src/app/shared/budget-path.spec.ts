import { SimplifyPathPipe, simplifyPathKey } from './budget-path';

/**
 * These pin the PASS-THROUGH deliberately.
 *
 * The function used to collapse numeric prefix chains, and the committee dropped that as
 * too unstable — the same path shortened differently depending on how the cost centres
 * happened to be numbered. Keeping the old cases would test behaviour nobody wants;
 * deleting the file would let the collapsing creep back unnoticed. So the tests assert
 * that the path comes out exactly as it went in, including the cases the old
 * implementation would have shortened.
 */
describe('simplifyPathKey', () => {
  it.each([
    // Each of these was collapsed by the previous implementation.
    'VSM-8-81-810-330',
    'VSM-6-60-120',
    '8-81-810',
    // These were already left alone, and still are.
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
