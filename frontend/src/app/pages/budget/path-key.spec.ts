import { simplifyPathKey } from './budget-tree.api';

describe('simplifyPathKey', () => {
  it('collapses numeric prefix chains, keeping the top segment', () => {
    expect(simplifyPathKey('VSM-8-81-810-330')).toBe('VSM-810-330');
    expect(simplifyPathKey('VSM-6-60-120')).toBe('VSM-60-120');
  });

  it('leaves non-prefix paths unchanged', () => {
    expect(simplifyPathKey('VSM-800-04')).toBe('VSM-800-04');
    expect(simplifyPathKey('VSM')).toBe('VSM');
    expect(simplifyPathKey('VSM-1')).toBe('VSM-1');
  });
});
