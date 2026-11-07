import type { FlowGraph } from '../admin.models';
import { dissolveGroup, setActionMap, setStateGremiumSource } from './flow-graph-ops.util';

const graph = (over: Partial<FlowGraph> = {}): FlowGraph => ({
  states: [{ key: 'a', label: { de: 'A' } }],
  transitions: [{ from: 'a', to: 'a' }],
  ...over,
});

describe('flow-graph-ops.util', () => {
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
