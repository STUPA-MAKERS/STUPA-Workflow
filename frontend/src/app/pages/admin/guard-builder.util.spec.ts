import {
  buildLeaf,
  combine,
  GuardError,
  isGuardValid,
  validateAction,
  validateGuard,
} from './guard-builder.util';

/**
 * The reason a guard was rejected, as the key and parameters it carries.
 *
 * A `GuardError` holds a key and not a sentence, so a test names the reason rather than
 * matching on wording that only the catalog decides.
 */
function reason(fn: () => void): { key: string; params?: Record<string, string | number> } {
  try {
    fn();
  } catch (err) {
    const e = err as GuardError;
    return { key: e.key, params: e.params };
  }
  throw new Error('expected a GuardError, but nothing was thrown');
}

describe('validateGuard (mirror of backend validate_guard)', () => {
  it('accepts empty guards (no gate)', () => {
    expect(() => validateGuard(null)).not.toThrow();
    expect(() => validateGuard(undefined)).not.toThrow();
  });

  it('accepts whitelist condition + actor operators', () => {
    expect(() => validateGuard({ roleIs: 'stupa' })).not.toThrow();
    expect(() => validateGuard({ deadlinePassed: true })).not.toThrow();
    expect(() => validateGuard({ hasField: 'iban' })).not.toThrow();
    expect(() =>
      validateGuard({ compare: { field: 'amount', op: '>', value: 100 } }),
    ).not.toThrow();
    // These conditions are also allowed on automatic transitions.
    expect(() => validateGuard({ applicationTypeIs: 'qsm' }, false)).not.toThrow();
    expect(() => validateGuard({ attachmentPresent: true }, false)).not.toThrow();
  });

  it('requires a non-empty application type key', () => {
    expect(reason(() => validateGuard({ applicationTypeIs: '' }))).toEqual({
      key: 'admin.flow.err.guardNeedsValue',
      params: { op: 'applicationTypeIs' },
    });
  });

  it('rejects unknown operators', () => {
    expect(() => validateGuard({ hackTheGibson: 1 })).toThrow(GuardError);
  });

  it('requires exactly one operator', () => {
    expect(reason(() => validateGuard({ roleIs: 'a', deadlinePassed: true })).key).toBe(
      'admin.flow.err.guardOneOperator',
    );
  });

  it('forbids actor gates on automatic transitions', () => {
    expect(reason(() => validateGuard({ roleIs: 'x' }, false))).toEqual({
      key: 'admin.flow.err.guardActorManualOnly',
      params: { op: 'roleIs' },
    });
    expect(reason(() => validateGuard({ isInCommittee: 'g' }, false)).key).toBe(
      'admin.flow.err.guardActorManualOnly',
    );
    // Conditions are allowed on automatic transitions.
    expect(() => validateGuard({ deadlinePassed: true }, false)).not.toThrow();
  });

  it('validates the compare structure', () => {
    expect(reason(() => validateGuard({ compare: { field: '', op: '==' } })).key).toBe(
      'admin.flow.err.compareField',
    );
    expect(reason(() => validateGuard({ compare: { field: 'x', op: '~=' } }))).toEqual({
      key: 'admin.flow.err.compareUnknownOp',
      params: { op: '~=' },
    });
    expect(
      reason(() => validateGuard({ compare: { field: 'x', op: 'in', value: 'notalist' } })).key,
    ).toBe('admin.flow.err.compareInList');
    // compare value is not an object at all
    expect(reason(() => validateGuard({ compare: 'oops' })).key).toBe(
      'admin.flow.err.compareShape',
    );
    // op missing → not a string
    expect(reason(() => validateGuard({ compare: { field: 'x' } })).key).toBe(
      'admin.flow.err.compareUnknownOp',
    );
    // `in` with a proper list passes
    expect(() => validateGuard({ compare: { field: 'x', op: 'in', value: [1, 2] } })).not.toThrow();
  });

  it('validates nested combinator children with actor restrictions', () => {
    // actor op nested under and on an automatic transition is rejected
    expect(reason(() => validateGuard({ and: [{ roleIs: 'x' }] }, false)).key).toBe(
      'admin.flow.err.guardActorManualOnly',
    );
    // condition op nested under or is fine even on automatic transitions
    expect(() =>
      validateGuard({ or: [{ deadlinePassed: true }, { hasField: 'iban' }] }, false),
    ).not.toThrow();
    // A guard with no operator at all names the empty operator list rather than leaving a gap.
    expect(reason(() => validateGuard({}))).toEqual({
      key: 'admin.flow.err.guardOneOperator',
      params: { ops: '—' },
    });
  });

  it('rejects empty operands where a value is required', () => {
    expect(reason(() => validateGuard({ roleIs: '' }))).toEqual({
      key: 'admin.flow.err.guardNeedsValue',
      params: { op: 'roleIs' },
    });
    expect(reason(() => validateGuard({ budgetIs: '   ' }))).toEqual({
      key: 'admin.flow.err.guardNeedsValue',
      params: { op: 'budgetIs' },
    });
    expect(isGuardValid({ roleIs: '' })).toBe(false);
    expect(isGuardValid({ roleIs: 'a' })).toBe(true);
  });

  it('checks combinator arity and children', () => {
    expect(
      reason(() => validateGuard({ not: [{ deadlinePassed: true }, { roleIs: 'x' }] })).key,
    ).toBe('admin.flow.err.guardNotOneChild');
    expect(() => validateGuard({ not: { deadlinePassed: true } })).not.toThrow();
    expect(reason(() => validateGuard({ and: [] }))).toEqual({
      key: 'admin.flow.err.guardNeedsChild',
      params: { op: 'and' },
    });
    expect(reason(() => validateGuard({ and: ['nope'] })).key).toBe('admin.flow.err.guardChildren');
  });
});

describe('validateAction (mirror of backend validate_action)', () => {
  it('accepts the four action types with their required fields', () => {
    expect(() => validateAction({ type: 'webhook', webhookId: 'w1' })).not.toThrow();
    expect(() =>
      validateAction({ type: 'notify', recipients: [{ kind: 'applicant' }] }),
    ).not.toThrow();
    expect(() => validateAction({ type: 'addToNextSession', gremiumId: 'g1' })).not.toThrow();
    expect(() => validateAction({ type: 'assignBudget', budgetId: 'b1' })).not.toThrow();
    expect(() => validateAction({ type: 'assignBudgetFromField', field: 'ziel_ks' })).not.toThrow();
  });

  it('rejects missing required fields', () => {
    expect(reason(() => validateAction({ type: 'webhook' })).key).toBe(
      'admin.flow.err.actionWebhook',
    );
    expect(reason(() => validateAction({ type: 'notify', recipients: [] })).key).toBe(
      'admin.flow.err.notifyRecipients',
    );
    expect(
      reason(() => validateAction({ type: 'notify', recipients: [{ kind: 'gremium' }] })),
    ).toEqual({ key: 'admin.flow.err.notifyRecipientValue', params: { kind: 'gremium' } });
    // The gremium of addToNextSession is optional; a present but empty one is wrong.
    expect(() => validateAction({ type: 'addToNextSession' })).not.toThrow();
    expect(reason(() => validateAction({ type: 'addToNextSession', gremiumId: '' })).key).toBe(
      'admin.flow.err.actionGremium',
    );
    expect(reason(() => validateAction({ type: 'assignBudget' })).key).toBe(
      'admin.flow.err.actionBudget',
    );
    expect(reason(() => validateAction({ type: 'assignBudgetFromField' })).key).toBe(
      'admin.flow.err.actionField',
    );
  });

  it('rejects unknown action types + non-objects', () => {
    expect(reason(() => validateAction({ type: 'rmrf' }))).toEqual({
      key: 'admin.flow.err.actionUnknownType',
      params: { type: 'rmrf' },
    });
    // @ts-expect-error not an object
    expect(() => validateAction(null)).toThrow(GuardError);
    // @ts-expect-error array is not a record
    expect(reason(() => validateAction([])).key).toBe('admin.flow.err.actionShape');
    // missing/non-string type
    // @ts-expect-error no type field
    expect(reason(() => validateAction({})).key).toBe('admin.flow.err.actionUnknownType');
  });

  it('accepts a notify recipient with a ref + applicant without one', () => {
    expect(() =>
      validateAction({
        type: 'notify',
        recipients: [
          { kind: 'gremium', ref: 'g1' },
          { kind: 'applicant' },
          { kind: 'email', ref: 'a@b.c' },
          { kind: 'role', ref: 'r1' },
        ],
      }),
    ).not.toThrow();
  });

  it('rejects notify recipients that are non-objects or have an unknown kind', () => {
    expect(reason(() => validateAction({ type: 'notify', recipients: ['nope'] })).key).toBe(
      'admin.flow.err.notifyRecipientInvalid',
    );
    expect(
      reason(() => validateAction({ type: 'notify', recipients: [{ kind: 'wat' }] })).key,
    ).toBe('admin.flow.err.notifyRecipientInvalid');
    // recipients not an array at all
    expect(reason(() => validateAction({ type: 'notify', recipients: 'x' })).key).toBe(
      'admin.flow.err.notifyRecipients',
    );
  });
});

describe('flow variant B (gremium from the cost center)', () => {
  it('accepts the new guard operators with a boolean only', () => {
    expect(() => validateGuard({ budgetHasDecisionGremium: true }, false)).not.toThrow();
    expect(() => validateGuard({ budgetHasDecisionGremium: false }, false)).not.toThrow();
    expect(() => validateGuard({ isInVoteGremium: true })).not.toThrow();
    expect(reason(() => validateGuard({ isInVoteGremium: 'yes' }))).toEqual({
      key: 'admin.flow.err.guardNeedsBool',
      params: { op: 'isInVoteGremium' },
    });
    expect(reason(() => validateGuard({ deadlinePassed: 1 })).key).toBe(
      'admin.flow.err.guardNeedsBool',
    );
  });

  it('allows isInVoteGremium on manual transitions only (actor gate)', () => {
    expect(reason(() => validateGuard({ isInVoteGremium: true }, false))).toEqual({
      key: 'admin.flow.err.guardActorManualOnly',
      params: { op: 'isInVoteGremium' },
    });
  });

  it('checks assignBudgetFromApplicantGremium: parentId optional, never empty', () => {
    expect(() => validateAction({ type: 'assignBudgetFromApplicantGremium' })).not.toThrow();
    expect(() =>
      validateAction({ type: 'assignBudgetFromApplicantGremium', parentId: 'b1' }),
    ).not.toThrow();
    expect(
      reason(() => validateAction({ type: 'assignBudgetFromApplicantGremium', parentId: ' ' }))
        .key,
    ).toBe('admin.flow.err.actionParent');
  });

  it('checks assignBudgetFromMap: a field and a non-empty value → cost center map', () => {
    expect(() =>
      validateAction({ type: 'assignBudgetFromMap', field: 'fs', map: { a: 'b1', b: 'b2' } }),
    ).not.toThrow();
    expect(reason(() => validateAction({ type: 'assignBudgetFromMap', map: { a: 'b1' } })).key).toBe(
      'admin.flow.err.actionField',
    );
    expect(reason(() => validateAction({ type: 'assignBudgetFromMap', field: 'fs' })).key).toBe(
      'admin.flow.err.actionMapEmpty',
    );
    expect(
      reason(() => validateAction({ type: 'assignBudgetFromMap', field: 'fs', map: {} })).key,
    ).toBe('admin.flow.err.actionMapEmpty');
    expect(
      reason(() => validateAction({ type: 'assignBudgetFromMap', field: 'fs', map: ['b1'] })).key,
    ).toBe('admin.flow.err.actionMapEmpty');
    expect(
      reason(() => validateAction({ type: 'assignBudgetFromMap', field: 'fs', map: { ' ': 'b1' } }))
        .key,
    ).toBe('admin.flow.err.actionMapValue');
    expect(
      reason(() => validateAction({ type: 'assignBudgetFromMap', field: 'fs', map: { a: '' } })),
    ).toEqual({ key: 'admin.flow.err.actionMapBudget', params: { value: 'a' } });
  });

  it('takes the recipient kinds voteGremium and budgetGremium without a ref', () => {
    expect(() =>
      validateAction({
        type: 'notify',
        recipients: [{ kind: 'voteGremium' }, { kind: 'budgetGremium' }],
      }),
    ).not.toThrow();
    expect(
      reason(() =>
        validateAction({ type: 'notify', recipients: [{ kind: 'voteGremium', ref: 'g1' }] }),
      ),
    ).toEqual({ key: 'admin.flow.err.notifyRecipientNoRef', params: { kind: 'voteGremium' } });
    expect(
      reason(() =>
        validateAction({ type: 'notify', recipients: [{ kind: 'applicant', ref: 'x' }] }),
      ).key,
    ).toBe('admin.flow.err.notifyRecipientNoRef');
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

  it('combine wraps `not` with the first child and isGuardValid swallows errors', () => {
    expect(combine('or', [{ roleIs: 'a' }])).toEqual({ or: [{ roleIs: 'a' }] });
    expect(isGuardValid(null)).toBe(true);
    expect(isGuardValid({ roleIs: 'x' }, false)).toBe(false);
  });
});
