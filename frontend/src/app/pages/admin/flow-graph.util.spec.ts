import type { FlowGraph } from './admin.models';
import {
  type FlowValidationResult,
  autoLayout,
  blankState,
  blankTransition,
  emptyFlowGraph,
  normalizeFlowGraph,
  validateFlowGraph,
} from './flow-graph.util';

/** Errors are keys plus parameters, so a test names the reason and not its wording. */
function keys(result: FlowValidationResult): string[] {
  return result.errors.map((e) => e.key);
}

function graph(overrides: Partial<FlowGraph> = {}): FlowGraph {
  return {
    states: [
      { key: 'draft', label: { de: 'Entwurf', en: 'Draft' }, isInitial: true },
      { key: 'review', label: { de: 'Prüfung', en: 'Review' } },
      { key: 'done', label: { de: 'Fertig', en: 'Done' }, color: '#5cb85c' },
    ],
    transitions: [
      { from: 'draft', to: 'review', actions: [] },
      {
        from: 'review',
        to: 'done',
        guard: { compare: { field: 'amount', op: '>=', value: 0 } },
        actions: [{ type: 'notify', recipients: [{ kind: 'applicant' }] }],
      },
    ],
    ...overrides,
  };
}

describe('validateFlowGraph', () => {
  it('accepts a well-formed graph', () => {
    expect(validateFlowGraph(graph())).toEqual({ valid: true, errors: [] });
  });

  it('rejects an empty graph', () => {
    const r = validateFlowGraph(emptyFlowGraph());
    expect(r.valid).toBe(false);
    expect(keys(r)).toContain('admin.flow.err.noStates');
  });

  it('requires exactly one initial state', () => {
    const none = validateFlowGraph(graph({ states: [{ key: 'a', label: { de: 'A' } }] }));
    expect(keys(none)).toContain('admin.flow.err.noInitial');

    const many = validateFlowGraph({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' }, isInitial: true },
      ],
      transitions: [{ from: 'a', to: 'b' }],
    });
    expect(keys(many)).toContain('admin.flow.err.multipleInitial');
  });

  it('detects duplicate state keys', () => {
    const r = validateFlowGraph({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'a', label: { de: 'A2' } },
      ],
      transitions: [],
    });
    expect(r.errors).toContainEqual({
      key: 'admin.flow.err.duplicateKeys',
      params: { keys: 'a' },
    });
  });

  it('flags invalid key syntax', () => {
    const r = validateFlowGraph({
      states: [{ key: 'Not Valid', label: { de: 'x' }, isInitial: true }],
      transitions: [],
    });
    expect(keys(r)).toContain('admin.flow.err.invalidKey');
  });

  it('detects dangling transition refs', () => {
    const r = validateFlowGraph(graph({ transitions: [{ from: 'draft', to: 'ghost' }] }));
    expect(keys(r)).toContain('admin.flow.err.unknownTo');
  });

  it('detects unreachable states', () => {
    const r = validateFlowGraph(
      graph({ transitions: [{ from: 'draft', to: 'review' }] }), // 'done' stays unreachable
    );
    expect(r.errors).toContainEqual({
      key: 'admin.flow.err.unreachable',
      params: { keys: 'done' },
    });
  });

  /**
   * An automatic non-branch exit fires at once and bypasses the vote. A manual exit that aborts the
   * vote stays allowed.
   */
  it('rejects automatic exits from vote states', () => {
    const g = graph({
      states: [
        { key: 'draft', label: { de: 'Entwurf' }, isInitial: true },
        { key: 'voting', label: { de: 'Abstimmung' }, kind: 'vote', config: { gremiumId: 'g-1' } },
        { key: 'passed', label: { de: 'Angenommen' } },
        { key: 'failed', label: { de: 'Abgelehnt' } },
      ],
      transitions: [
        { from: 'draft', to: 'voting' },
        { from: 'voting', to: 'passed', branch: 'pass' },
        { from: 'voting', to: 'failed', branch: 'fail' },
        { from: 'voting', to: 'passed', automatic: true },
      ],
    });
    const v = validateFlowGraph(g);
    expect(v.valid).toBe(false);
    expect(keys(v)).toContain('admin.flow.err.voteNoAutomatic');
    g.transitions = g.transitions.filter((t) => !t.automatic);
    g.transitions.push({ from: 'voting', to: 'failed' });
    expect(validateFlowGraph(g).valid).toBe(true);
  });

  it('rejects guards/actions outside the whitelist', () => {
    const badGuard = validateFlowGraph(
      graph({ transitions: [{ from: 'draft', to: 'review', guard: { bogus: 1 } }] }),
    );
    expect(badGuard.valid).toBe(false);

    const badAction = validateFlowGraph(
      graph({ transitions: [{ from: 'draft', to: 'review', actions: [{ type: 'rmrf' }] }] }),
    );
    expect(badAction.valid).toBe(false);
  });

  /**
   * The target "review" is a normal state, so the check rejects the graph. The same action passes
   * when the target state has kind 'vote'.
   */
  it('requires addToNextSession to lead into a vote state', () => {
    const bad = validateFlowGraph(
      graph({
        transitions: [
          { from: 'draft', to: 'review', actions: [{ type: 'addToNextSession', gremiumId: 'g1' }] },
          { from: 'review', to: 'done' },
        ],
      }),
    );
    expect(bad.valid).toBe(false);
    expect(keys(bad)).toContain('admin.flow.err.sessionNeedsVote');

    const ok = validateFlowGraph({
      states: [
        { key: 'draft', label: { de: 'D' }, isInitial: true },
        { key: 'voting', label: { de: 'V' }, kind: 'vote', config: { gremiumId: 'g1' } },
        { key: 'passed', label: { de: 'P' } },
        { key: 'failed', label: { de: 'F' } },
      ],
      transitions: [
        { from: 'draft', to: 'voting', actions: [{ type: 'addToNextSession', gremiumId: 'g1' }] },
        { from: 'voting', to: 'passed', branch: 'pass' },
        { from: 'voting', to: 'failed', branch: 'fail' },
      ],
    });
    expect(ok.valid).toBe(true);
  });

  /** Without config.gremiumId and with only one outgoing branch, both errors fire. */
  it('flags a vote state missing branches and missing committee', () => {
    const r = validateFlowGraph({
      states: [
        { key: 'draft', label: { de: 'D' }, isInitial: true },
        { key: 'voting', label: { de: 'V' }, kind: 'vote' },
        { key: 'passed', label: { de: 'P' } },
      ],
      transitions: [
        { from: 'draft', to: 'voting' },
        { from: 'voting', to: 'passed', branch: 'pass' },
      ],
    });
    expect(r.valid).toBe(false);
    expect(keys(r)).toContain('admin.flow.err.voteNeedsGremium');
    expect(keys(r)).toContain('admin.flow.err.voteBranches');
  });

  /**
   * The check reports the duplicate. It skips the reachability test, because that test runs only
   * when the duplicate count is zero.
   */
  it('skips reachability check while there are duplicate keys', () => {
    const r = validateFlowGraph({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'a', label: { de: 'A2' } },
        { key: 'orphan', label: { de: 'O' } },
      ],
      transitions: [],
    });
    expect(keys(r)).toContain('admin.flow.err.duplicateKeys');
    expect(keys(r)).not.toContain('admin.flow.err.unreachable');
  });
});

describe('graph ↔ JSON round-trip', () => {
  it('normalize strips empty optionals but keeps schema fields', () => {
    const n = normalizeFlowGraph(graph());
    expect(n.states[0]).toEqual({
      key: 'draft',
      label: { de: 'Entwurf', en: 'Draft' },
      isInitial: true,
    });
    expect(n.transitions[0]).toEqual({ from: 'draft', to: 'review' });
  });

  it('keeps a transition color through normalize', () => {
    const g = graph({
      transitions: [{ from: 'draft', to: 'review', color: '#16a34a' }],
    });
    expect(normalizeFlowGraph(g).transitions[0]).toEqual({
      from: 'draft',
      to: 'review',
      color: '#16a34a',
    });
  });

  it('persists a non-empty layout', () => {
    const g = graph({ layout: { positions: { draft: { x: 0, y: 0 } } } });
    expect(normalizeFlowGraph(g).layout).toEqual({ positions: { draft: { x: 0, y: 0 } } });
  });

  it('keeps every optional state/transition field through normalize', () => {
    const g: FlowGraph = {
      states: [
        {
          key: 'draft',
          label: { de: 'E' },
          color: '#abc',
          editAllowed: false,
          isInitial: true,
          isTerminal: true,
          kind: 'vote',
          config: { gremiumId: 'g1' },
        },
      ],
      transitions: [
        {
          from: 'draft',
          to: 'draft',
          label: { de: 'x' },
          color: '#def',
          guard: { roleIs: 'stupa' },
          actions: [{ type: 'notify', recipients: [{ kind: 'applicant' }] }],
          order: 3,
          automatic: true,
          branch: 'pass',
          requiresAction: false,
        },
      ],
    };
    const n = normalizeFlowGraph(g);
    expect(n.states[0]).toEqual({
      key: 'draft',
      label: { de: 'E' },
      color: '#abc',
      editAllowed: false,
      isInitial: true,
      isTerminal: true,
      kind: 'vote',
      config: { gremiumId: 'g1' },
    });
    expect(n.transitions[0]).toEqual({
      from: 'draft',
      to: 'draft',
      label: { de: 'x' },
      color: '#def',
      guard: { roleIs: 'stupa' },
      actions: [{ type: 'notify', recipients: [{ kind: 'applicant' }] }],
      order: 3,
      automatic: true,
      branch: 'pass',
      requiresAction: false,
    });
  });

  /**
   * The group keeps the live key 'a' and drops the dead 'ghost'. It also references a real sibling
   * group, itself and a missing group. normalizeFlowGraph drops a group with no states and no
   * sub-groups. An empty positions object drops layout.positions, so only the groups remain.
   */
  it('normalizes groups: prunes dead state refs, self/missing groupIds and empty groups', () => {
    const g: FlowGraph = {
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' } },
      ],
      transitions: [{ from: 'a', to: 'b' }],
      layout: {
        positions: {},
        groups: [
          {
            id: 'g1',
            name: 'G1',
            stateKeys: ['a', 'ghost'],
            groupIds: ['g2', 'g1', 'missing'],
            color: '#111',
          },
          { id: 'g2', name: 'G2', stateKeys: ['b'] },
          { id: 'gEmpty', name: 'Empty', stateKeys: ['ghost'] },
        ],
      },
    };
    const n = normalizeFlowGraph(g);
    expect(n.layout?.groups).toEqual([
      { id: 'g1', name: 'G1', stateKeys: ['a'], groupIds: ['g2'], color: '#111' },
      { id: 'g2', name: 'G2', stateKeys: ['b'] },
    ]);
    expect(n.layout?.positions).toBeUndefined();
  });

  it('omits the layout entirely when there are no positions and no groups', () => {
    const g: FlowGraph = {
      states: [{ key: 'a', label: { de: 'A' }, isInitial: true }],
      transitions: [],
      layout: { positions: {}, groups: [] },
    };
    expect(normalizeFlowGraph(g).layout).toBeUndefined();
  });
});

describe('autoLayout', () => {
  it('assigns layered positions and keeps existing ones', () => {
    const g = autoLayout(graph({ layout: { positions: { draft: { x: 5, y: 5 } } } }));
    expect(g.layout!.positions!['draft']).toEqual({ x: 5, y: 5 });
    expect(g.layout!.positions!['review'].x).toBeGreaterThan(0);
    expect(g.layout!.positions!['done'].x).toBeGreaterThan(g.layout!.positions!['review'].x);
  });

  /**
   * The shortcut a→d still keeps d in layer 2. The columns are a | b,c | d, because the layout uses
   * the longest path, not BFS. b and c share the column without overlap. The layout centers the
   * single-node layers (a, d) against the two-node layer.
   */
  it('layers by longest path and centers small layers (diamond)', () => {
    const g = autoLayout({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' } },
        { key: 'c', label: { de: 'C' } },
        { key: 'd', label: { de: 'D' } },
      ],
      transitions: [
        { from: 'a', to: 'b' },
        { from: 'a', to: 'c' },
        { from: 'b', to: 'd' },
        { from: 'c', to: 'd' },
        { from: 'a', to: 'd' },
      ],
    });
    const p = g.layout!.positions!;
    expect(p['b'].x).toBe(p['c'].x);
    expect(p['d'].x).toBeGreaterThan(p['b'].x);
    expect(p['b'].y).not.toBe(p['c'].y);
    const mid = (p['b'].y + p['c'].y) / 2;
    expect(p['a'].y).toBe(mid);
    expect(p['d'].y).toBe(mid);
  });
});

describe('autoLayout edge cases', () => {
  /**
   * The orphan has no incoming edge, so the layout puts it at maxDepth + 1, past the column of b.
   */
  it('places unreachable states behind the deepest layer and ignores self-loops', () => {
    const g = autoLayout({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' } },
        { key: 'orphan', label: { de: 'O' } },
      ],
      transitions: [
        { from: 'a', to: 'b' },
        { from: 'b', to: 'b' }, // self-loop is layout-neutral
        { from: 'a', to: 'ghost' }, // the layout ignores this dangling target
      ],
    });
    const p = g.layout!.positions!;
    expect(p['orphan'].x).toBeGreaterThan(p['b'].x);
  });

  it('falls back to the first state when no initial is marked', () => {
    const g = autoLayout({
      states: [
        { key: 'a', label: { de: 'A' } },
        { key: 'b', label: { de: 'B' } },
      ],
      transitions: [{ from: 'a', to: 'b' }],
    });
    const p = g.layout!.positions!;
    expect(p['a'].x).toBeLessThan(p['b'].x);
  });

  it('handles a completely empty graph without throwing', () => {
    const g = autoLayout(emptyFlowGraph());
    expect(g.layout?.positions).toEqual({});
  });

  /** validate, normalize, serialize and autoLayout all default transitions to []. */
  it('tolerates a graph whose transitions array is omitted (undefined)', () => {
    const noTransitions = {
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' } },
      ],
    } as unknown as FlowGraph;
    expect(keys(validateFlowGraph(noTransitions))).toContain('admin.flow.err.unreachable');
    expect(normalizeFlowGraph(noTransitions).transitions).toEqual([]);
    const laid = autoLayout(noTransitions);
    expect(laid.layout!.positions!['a']).toBeDefined();
    expect(laid.layout!.positions!['b']).toBeDefined();
  });
});

describe('factories', () => {
  it('blankState/blankTransition produce editable shells', () => {
    expect(blankState('s', true)).toEqual({
      key: 's',
      label: { de: '', en: '' },
      isInitial: true,
      editAllowed: true,
    });
    expect(blankTransition('a', 'b')).toEqual({ from: 'a', to: 'b', actions: [] });
  });

  it('blankState/blankTransition apply their default arguments', () => {
    expect(blankState()).toEqual({
      key: '',
      label: { de: '', en: '' },
      isInitial: false,
      editAllowed: true,
    });
    expect(blankTransition()).toEqual({ from: '', to: '', actions: [] });
  });
});

describe('validateFlowGraph defensive defaults', () => {
  it('treats a graph with no states field as empty (states ?? [])', () => {
    const noStates = {} as unknown as FlowGraph;
    const r = validateFlowGraph(noStates);
    expect(r.valid).toBe(false);
    expect(keys(r)).toContain('admin.flow.err.noStates');
  });
});

describe('validateFlowGraph — vote state with the gremium from the cost center', () => {
  function voteGraph(config: Record<string, unknown>, actions: FlowGraph['transitions'][number]['actions'] = []): FlowGraph {
    return {
      states: [
        { key: 'draft', label: { de: 'E' }, isInitial: true },
        { key: 'vote', label: { de: 'V' }, kind: 'vote', config },
        { key: 'ok', label: { de: 'O' } },
        { key: 'no', label: { de: 'N' } },
      ],
      transitions: [
        { from: 'draft', to: 'vote', actions },
        { from: 'vote', to: 'ok', branch: 'pass' },
        { from: 'vote', to: 'no', branch: 'fail' },
      ],
    };
  }

  it('accepts gremiumSource "budget" alone and a fixed gremiumId alone', () => {
    expect(validateFlowGraph(voteGraph({ gremiumSource: 'budget' })).valid).toBe(true);
    expect(validateFlowGraph(voteGraph({ gremiumId: 'g1' })).valid).toBe(true);
  });

  it('rejects both, neither and an unknown source', () => {
    expect(keys(validateFlowGraph(voteGraph({ gremiumId: 'g1', gremiumSource: 'budget' })))).toEqual([
      'admin.flow.err.voteGremiumBoth',
    ]);
    expect(keys(validateFlowGraph(voteGraph({})))).toEqual(['admin.flow.err.voteNeedsGremium']);
    expect(keys(validateFlowGraph(voteGraph({ gremiumSource: 'meeting' })))).toEqual([
      'admin.flow.err.voteGremiumSource',
    ]);
  });

  it('takes addToNextSession without a gremium into a vote state', () => {
    expect(
      validateFlowGraph(voteGraph({ gremiumSource: 'budget' }, [{ type: 'addToNextSession' }])).valid,
    ).toBe(true);
  });

  /** Into a vote state with a fixed gremium the action stays allowed. */
  it('rejects a cost-center action on a transition into a budget vote state', () => {
    for (const action of [
      { type: 'assignBudget' as const, budgetId: 'b1' },
      { type: 'assignBudgetFromField' as const, field: 'ks' },
      { type: 'assignBudgetFromApplicantGremium' as const },
      { type: 'assignBudgetFromMap' as const, field: 'fs', map: { a: 'b1' } },
    ]) {
      const r = validateFlowGraph(voteGraph({ gremiumSource: 'budget' }, [action]));
      expect(r.errors).toEqual([
        { key: 'admin.flow.err.assignIntoBudgetVote', params: { from: 'draft', to: 'vote' } },
      ]);
    }
    expect(
      validateFlowGraph(voteGraph({ gremiumId: 'g1' }, [{ type: 'assignBudget', budgetId: 'b1' }]))
        .valid,
    ).toBe(true);
  });

  it('decides "both" by key presence and needs a non-empty fixed id, as the backend', () => {
    expect(keys(validateFlowGraph(voteGraph({ gremiumId: '', gremiumSource: 'budget' })))).toEqual([
      'admin.flow.err.voteGremiumBoth',
    ]);
    expect(keys(validateFlowGraph(voteGraph({ gremiumId: '' })))).toEqual([
      'admin.flow.err.voteNeedsGremium',
    ]);
    expect(keys(validateFlowGraph(voteGraph({ gremiumId: 7 })))).toEqual([
      'admin.flow.err.voteNeedsGremium',
    ]);
  });

  it('rejects gremiumSource "budget" on the initial state', () => {
    const graph = voteGraph({ gremiumSource: 'budget' });
    graph.states[0].isInitial = false;
    graph.states[1].isInitial = true;
    graph.transitions.push({ from: 'vote', to: 'draft' });
    expect(keys(validateFlowGraph(graph))).toEqual(['admin.flow.err.voteGremiumInitial']);
  });

  it('rejects a fixed agenda gremium into a budget vote state', () => {
    const r = validateFlowGraph(
      voteGraph({ gremiumSource: 'budget' }, [{ type: 'addToNextSession', gremiumId: 'g1' }]),
    );
    expect(r.errors).toEqual([
      { key: 'admin.flow.err.sessionGremiumIntoBudgetVote', params: { from: 'draft', to: 'vote' } },
    ]);
    expect(
      validateFlowGraph(voteGraph({ gremiumId: 'g1' }, [{ type: 'addToNextSession', gremiumId: 'g1' }]))
        .valid,
    ).toBe(true);
  });

  it('allows the voteGremium recipient only into a vote state', () => {
    const notify = { type: 'notify' as const, recipients: [{ kind: 'voteGremium' as const }] };
    expect(validateFlowGraph(voteGraph({ gremiumSource: 'budget' }, [notify])).valid).toBe(true);
    const graph = voteGraph({ gremiumSource: 'budget' });
    graph.transitions[1].actions = [notify];
    expect(validateFlowGraph(graph).errors).toEqual([
      { key: 'admin.flow.err.voteGremiumRecipientNeedsVote', params: { from: 'vote', to: 'ok' } },
    ]);
  });
});
