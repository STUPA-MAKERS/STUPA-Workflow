import type { FlowGraph } from './admin.models';
import {
  autoLayout,
  blankState,
  blankTransition,
  emptyFlowGraph,
  normalizeFlowGraph,
  parseFlowGraph,
  serializeFlowGraph,
  validateFlowGraph,
} from './flow-graph.util';

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
    expect(r.errors).toContain('flow graph has no states');
  });

  it('requires exactly one initial state', () => {
    const none = validateFlowGraph(
      graph({ states: [{ key: 'a', label: { de: 'A' } }] }),
    );
    expect(none.errors).toContain('flow graph has no initial state');

    const many = validateFlowGraph({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' }, isInitial: true },
      ],
      transitions: [{ from: 'a', to: 'b' }],
    });
    expect(many.errors.some((e) => e.includes('multiple initial states'))).toBe(true);
  });

  it('detects duplicate state keys', () => {
    const r = validateFlowGraph({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'a', label: { de: 'A2' } },
      ],
      transitions: [],
    });
    expect(r.errors.some((e) => e.includes('duplicate state keys: a'))).toBe(true);
  });

  it('flags invalid key syntax', () => {
    const r = validateFlowGraph({
      states: [{ key: 'Not Valid', label: { de: 'x' }, isInitial: true }],
      transitions: [],
    });
    expect(r.errors.some((e) => e.includes('invalid state key'))).toBe(true);
  });

  it('detects dangling transition refs', () => {
    const r = validateFlowGraph(
      graph({ transitions: [{ from: 'draft', to: 'ghost' }] }),
    );
    expect(r.errors.some((e) => e.includes('unknown to-state'))).toBe(true);
  });

  it('detects unreachable states', () => {
    const r = validateFlowGraph(
      graph({ transitions: [{ from: 'draft', to: 'review' }] }), // 'done' unreachable
    );
    expect(r.errors.some((e) => e.includes('unreachable states: done'))).toBe(true);
  });

  it('rejects automatic exits from vote states (#vote-bypass)', () => {
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
        // Automatischer Nicht-Branch-Ausgang: würde am Vote vorbei sofort feuern.
        { from: 'voting', to: 'passed', automatic: true },
      ],
    });
    const v = validateFlowGraph(g);
    expect(v.valid).toBe(false);
    expect(v.errors.join(' ')).toContain('must not have automatic outgoing transitions');
    // Manueller Ausgang (Wahl abbrechen) bleibt dagegen erlaubt.
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

  it('keeps a transition color through normalize (#flow)', () => {
    const g = graph({
      transitions: [{ from: 'draft', to: 'review', color: '#16a34a' }],
    });
    expect(normalizeFlowGraph(g).transitions[0]).toEqual({
      from: 'draft',
      to: 'review',
      color: '#16a34a',
    });
  });

  it('serialize → parse is idempotent (round-trip)', () => {
    const g = graph();
    const back = parseFlowGraph(serializeFlowGraph(g));
    expect(back).toEqual(normalizeFlowGraph(g));
    // double round-trip stable
    expect(parseFlowGraph(serializeFlowGraph(back))).toEqual(back);
  });

  it('persists a non-empty layout', () => {
    const g = graph({ layout: { positions: { draft: { x: 0, y: 0 } } } });
    expect(normalizeFlowGraph(g).layout).toEqual({ positions: { draft: { x: 0, y: 0 } } });
  });
});

describe('autoLayout', () => {
  it('assigns BFS-layered positions and keeps existing ones', () => {
    const g = autoLayout(graph({ layout: { positions: { draft: { x: 5, y: 5 } } } }));
    expect(g.layout!.positions!['draft']).toEqual({ x: 5, y: 5 }); // preserved
    expect(g.layout!.positions!['review'].x).toBeGreaterThan(0); // column by depth
    expect(g.layout!.positions!['done'].x).toBeGreaterThan(g.layout!.positions!['review'].x);
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
});
