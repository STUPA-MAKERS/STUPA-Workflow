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
  it('accepts empty guards (no gate)', () => {
    expect(() => validateGuard(null)).not.toThrow();
    expect(() => validateGuard(undefined)).not.toThrow();
  });

  it('accepts whitelist condition + actor operators', () => {
    expect(() => validateGuard({ roleIs: 'stupa' })).not.toThrow();
    expect(() => validateGuard({ deadlinePassed: true })).not.toThrow();
    expect(() => validateGuard({ hasField: 'iban' })).not.toThrow();
    expect(() => validateGuard({ compare: { field: 'amount', op: '>', value: 100 } })).not.toThrow();
  });

  it('rejects unknown operators', () => {
    expect(() => validateGuard({ hackTheGibson: 1 })).toThrow(GuardError);
  });

  it('requires exactly one operator', () => {
    expect(() => validateGuard({ roleIs: 'a', deadlinePassed: true })).toThrow(/exactly one operator/);
  });

  it('forbids actor gates on automatic transitions', () => {
    expect(() => validateGuard({ roleIs: 'x' }, false)).toThrow(/manual/);
    expect(() => validateGuard({ isInCommittee: 'g' }, false)).toThrow(/manual/);
    // Bedingungen sind auf automatischen Übergängen erlaubt.
    expect(() => validateGuard({ deadlinePassed: true }, false)).not.toThrow();
  });

  it('validates the compare structure', () => {
    expect(() => validateGuard({ compare: { field: '', op: '==' } })).toThrow(/field/);
    expect(() => validateGuard({ compare: { field: 'x', op: '~=' } })).toThrow(/unknown compare operator/);
    expect(() => validateGuard({ compare: { field: 'x', op: 'in', value: 'notalist' } })).toThrow(/list value/);
  });

  it('rejects empty operands where a value is required', () => {
    expect(() => validateGuard({ roleIs: '' })).toThrow(/roleIs/);
    expect(() => validateGuard({ budgetIs: '   ' })).toThrow(/budgetIs/);
    expect(isGuardValid({ roleIs: '' })).toBe(false);
    expect(isGuardValid({ roleIs: 'a' })).toBe(true);
  });

  it('checks combinator arity and children', () => {
    expect(() => validateGuard({ not: [{ deadlinePassed: true }, { roleIs: 'x' }] })).toThrow(
      /'not' requires exactly one/,
    );
    expect(() => validateGuard({ not: { deadlinePassed: true } })).not.toThrow();
    expect(() => validateGuard({ and: [] })).toThrow(/at least one/);
    expect(() => validateGuard({ and: ['nope'] })).toThrow(/children must be guard objects/);
  });
});

describe('validateAction (mirror of backend validate_action)', () => {
  it('accepts the four action types with their required fields', () => {
    expect(() => validateAction({ type: 'webhook', webhookId: 'w1' })).not.toThrow();
    expect(() => validateAction({ type: 'notify', recipients: [{ kind: 'applicant' }] })).not.toThrow();
    expect(() => validateAction({ type: 'addToNextSession', gremiumId: 'g1' })).not.toThrow();
    expect(() => validateAction({ type: 'assignBudget', budgetId: 'b1' })).not.toThrow();
  });

  it('rejects missing required fields', () => {
    expect(() => validateAction({ type: 'webhook' })).toThrow(/webhook/);
    expect(() => validateAction({ type: 'notify', recipients: [] })).toThrow(/recipient/);
    expect(() => validateAction({ type: 'notify', recipients: [{ kind: 'gremium' }] })).toThrow(/value/);
    expect(() => validateAction({ type: 'addToNextSession' })).toThrow(/committee/);
    expect(() => validateAction({ type: 'assignBudget' })).toThrow(/budget/);
  });

  it('rejects unknown action types + non-objects', () => {
    expect(() => validateAction({ type: 'rmrf' })).toThrow(/unknown action type/);
    // @ts-expect-error not an object
    expect(() => validateAction(null)).toThrow(GuardError);
  });
});

describe('builder helpers', () => {
  it('buildLeaf + combine compose guards', () => {
    expect(buildLeaf('roleIs', 'stupa')).toEqual({ roleIs: 'stupa' });
    expect(combine('and', [{ roleIs: 'a' }, { deadlinePassed: true }])).toEqual({
      and: [{ roleIs: 'a' }, { deadlinePassed: true }],
    });
    expect(combine('not', [{ deadlinePassed: true }])).toEqual({ not: { deadlinePassed: true } });
  });

  it('describeGuard renders nested + compare guards', () => {
    expect(describeGuard(null)).toBe('—');
    expect(describeGuard({ roleIs: 'stupa' })).toBe('roleIs: "stupa"');
    expect(describeGuard({ and: [{ roleIs: 'a' }, { deadlinePassed: true }] })).toBe(
      'roleIs: "a" ∧ deadlinePassed: true',
    );
    expect(describeGuard({ not: { deadlinePassed: true } })).toBe('¬(deadlinePassed: true)');
    expect(describeGuard({ compare: { field: 'amount', op: '>', value: 100 } })).toBe('amount > 100');
    expect(describeGuard({ a: 1, b: 2 })).toBe('⚠ invalid');
  });
});
