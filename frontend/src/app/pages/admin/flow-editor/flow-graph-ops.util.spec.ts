import type { FlowGraph } from '../admin.models';
import {
  dissolveGroup,
  setActionMap,
  setStateGremiumSource,
  setStateKind,
  setStateOutcome,
} from './flow-graph-ops.util';

const graph = (over: Partial<FlowGraph> = {}): FlowGraph => ({
  states: [{ key: 'a', label: { de: 'A' } }],
  transitions: [{ from: 'a', to: 'a' }],
  ...over,
});

describe('flow-graph-ops.util', () => {
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
