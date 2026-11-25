import type { FlowGraph } from '../admin.models';
import {
  dissolveGroup,
  setActionMap,
  setOrderOffer,
  setStateGremiumSource,
  setStateKind,
  setStateOutcome,
  setStateReplacedTarget,
} from './flow-graph-ops.util';

const graph = (over: Partial<FlowGraph> = {}): FlowGraph => ({
  states: [{ key: 'a', label: { de: 'A' } }],
  transitions: [{ from: 'a', to: 'a' }],
  ...over,
});

describe('flow-graph-ops.util', () => {
  /** §F/finance/orders/002931: the status of a Bestellung that offers a transition. */
  it('sets and takes away the status of a Bestellung that offers a transition', () => {
    const base = graph({
      states: [{ key: 'a', label: { de: 'A' } }, { key: 'b', label: { de: 'B' } }],
      transitions: [{ from: 'a', to: 'b', actions: [] }],
    });
    const ordered = setOrderOffer(base, 0, 'ordered');
    expect(ordered.transitions[0].offerOnOrderStatus).toBe('ordered');
    expect(setOrderOffer(ordered, 0, 'delivered').transitions[0].offerOnOrderStatus).toBe('delivered');
    expect(setOrderOffer(ordered, 0, '').transitions[0]).not.toHaveProperty('offerOnOrderStatus');
    expect(setOrderOffer(ordered, 0, 'returned').transitions[0].offerOnOrderStatus).toBe('returned');
  });

  /** § 000571: a state is approved or denied, never both, and a vote state neither. */
  it('keeps one outcome flag per state and drops both on a vote state', () => {
    const flags = (g: FlowGraph) => [g.states[0].isApproved, g.states[0].isDenied];
    const approved = setStateOutcome(graph(), 'a', 'approved', true);
    expect(flags(approved)).toEqual([true, false]);
    const denied = setStateOutcome(approved, 'a', 'denied', true);
    expect(flags(denied)).toEqual([false, true]);
    expect(flags(setStateOutcome(denied, 'a', 'denied', false))).toEqual([false, false]);
    expect(flags(setStateOutcome(approved, 'a', 'approved', false))).toEqual([false, false]);
    expect(flags(setStateKind(approved, 'a', 'vote'))).toEqual([false, false]);
    expect(flags(setStateKind(approved, 'a', 'normal'))).toEqual([true, false]);
  });

  /** 001722: one target for replaced Anträge, terminal and denied. */
  it('keeps one target for replaced Anträge and makes it terminal and denied', () => {
    const two = graph({ states: [{ key: 'a', label: { de: 'A' } }, { key: 'b', label: { de: 'B' } }] });
    const a = setStateReplacedTarget(two, 'a', true);
    expect(a.states[0]).toMatchObject({ isReplacedTarget: true, isTerminal: true, isDenied: true, isApproved: false });
    const b = setStateReplacedTarget(a, 'b', true);
    expect(b.states.map((s) => !!s.isReplacedTarget)).toEqual([false, true]);
    expect(setStateReplacedTarget(b, 'b', false).states[1].isReplacedTarget).toBe(false);
  });

  it('sets the gremium source on a state without a config', () => {
    expect(setStateGremiumSource(graph(), 'a', 'budget').states[0].config).toEqual({
      gremiumSource: 'budget',
    });
    expect(setStateGremiumSource(graph(), 'a', 'fixed').states[0].config).toEqual({});
  });

  it('leaves a transition without actions without actions when the map is set', () => {
    expect(setActionMap(graph(), 0, 0, { x: 'y' }).transitions[0].actions).toEqual([]);
  });

  it('moves a group without child groups into a parent without child groups', () => {
    const g = graph({
      layout: {
        groups: [
          { id: 'p', name: 'P', stateKeys: [] },
          { id: 'c', name: 'C', stateKeys: ['a'] },
        ],
      },
    });
    expect(dissolveGroup(g, 'c', 'p').layout?.groups).toEqual([
      { id: 'p', name: 'P', stateKeys: ['a'], groupIds: [] },
    ]);
  });

  it('drops the groups key when the last group dissolves on a graph without a layout key', () => {
    expect(dissolveGroup(graph(), 'x', null)).toEqual(graph());
  });
});
