import {
  buildLeaf,
  combine,
  describeGuard,
  GuardError,
  isGuardValid,
  validateAction,
  validateGuard,
} from './guard-builder.util';

describe('validateGuard (mirror of backend validate_guard)', () => {
  it('accepts an empty/null guard (no gate)', () => {
    expect(() => validateGuard(null)).not.toThrow();
    expect(() => validateGuard(undefined)).not.toThrow();
  });

  it('accepts whitelist leaf operators', () => {
    expect(() => validateGuard({ roleIs: 'stupa' })).not.toThrow();
    expect(() => validateGuard({ fieldsComplete: true })).not.toThrow();
    expect(() => validateGuard({ manual: true })).not.toThrow();
  });

  it('rejects an unknown operator', () => {
    expect(() => validateGuard({ hackTheGibson: 1 })).toThrow(GuardError);
  });

  it('rejects a guard with more than one operator', () => {
    expect(() => validateGuard({ roleIs: 'a', manual: true })).toThrow(/exactly one operator/);
  });

  it('validates voteResult values against the whitelist', () => {
    expect(() => validateGuard({ voteResult: 'passed' })).not.toThrow();
    expect(() => validateGuard({ voteResult: 'maybe' })).toThrow(/invalid voteResult/);
  });

  it('rejects empty roleIs/permissionIs operands (server would reject too)', () => {
    expect(() => validateGuard({ roleIs: '' })).toThrow(/roleIs/);
    expect(() => validateGuard({ roleIs: null })).toThrow(/roleIs/);
    expect(() => validateGuard({ permissionIs: '   ' })).toThrow(/permissionIs/);
    expect(() => validateGuard({ permissionIs: undefined })).toThrow(/permissionIs/);
    // non-empty stays valid
    expect(() => validateGuard({ roleIs: 'stupa' })).not.toThrow();
    expect(isGuardValid({ roleIs: '' })).toBe(false);
  });

  it("requires 'not' to have exactly one child", () => {
    expect(() => validateGuard({ not: [{ manual: true }, { roleIs: 'x' }] })).toThrow(
      /'not' requires exactly one/,
    );
    expect(() => validateGuard({ not: { manual: true } })).not.toThrow();
  });

  it("requires 'and'/'or' to have at least one child and validates recursively", () => {
    expect(() => validateGuard({ and: [] })).toThrow(/at least one/);
    expect(() => validateGuard({ and: [{ roleIs: 'a' }, { voteResult: 'nope' }] })).toThrow(
      /invalid voteResult/,
    );
    expect(() =>
      validateGuard({ or: [{ roleIs: 'a' }, { and: [{ manual: true }] }] }),
    ).not.toThrow();
  });

  it('rejects non-object children', () => {
    expect(() => validateGuard({ and: ['nope'] })).toThrow(/children must be guard objects/);
  });

  it('isGuardValid is the boolean form', () => {
    expect(isGuardValid({ roleIs: 'a' })).toBe(true);
    expect(isGuardValid({ bogus: 1 })).toBe(false);
  });
});

describe('validateAction (mirror of backend validate_action)', () => {
  it('accepts whitelist action types', () => {
    expect(() => validateAction({ type: 'notify' })).not.toThrow();
    expect(() => validateAction({ type: 'openVote', voteConfigId: 'x' })).not.toThrow();
  });

  it('rejects unknown action types', () => {
    expect(() => validateAction({ type: 'rmrf' })).toThrow(/unknown action type/);
  });

  it('rejects non-objects', () => {
    expect(() => validateAction(null)).toThrow(GuardError);
  });
});

describe('guard builders + describe', () => {
  it('buildLeaf produces a single-operator guard', () => {
    expect(buildLeaf('roleIs', 'stupa')).toEqual({ roleIs: 'stupa' });
  });

  it('combine builds and/or/not', () => {
    expect(combine('and', [{ roleIs: 'a' }, { manual: true }])).toEqual({
      and: [{ roleIs: 'a' }, { manual: true }],
    });
    expect(combine('not', [{ manual: true }])).toEqual({ not: { manual: true } });
  });

  it('describeGuard renders nested guards', () => {
    expect(describeGuard(null)).toBe('—');
    expect(describeGuard({ roleIs: 'stupa' })).toBe('roleIs: "stupa"');
    expect(describeGuard({ and: [{ roleIs: 'a' }, { manual: true }] })).toBe(
      'roleIs: "a" ∧ manual: true',
    );
    expect(describeGuard({ not: { manual: true } })).toBe('¬(manual: true)');
    expect(describeGuard({ a: 1, b: 2 })).toBe('⚠ invalid');
  });
});
