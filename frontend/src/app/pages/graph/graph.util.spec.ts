import { convertToParamMap } from '@angular/router';
import type { GraphEdge, GraphNode, GraphPage } from '@core/api/graph.service';
import {
  AUTO_NODES,
  EMPTY_GRAPH,
  KIND_FEATURE,
  NO_FILTERS,
  filtersOf,
  isFiltered,
  merged,
  neighbours,
  nodeKey,
  queryOf,
  sameFilters,
} from './graph.util';

const node = (kind: GraphNode['kind'], id: string): GraphNode => ({
  kind,
  id,
  accessible: true,
  title: `${kind} ${id}`,
  date: null,
  url: `/${kind}/${id}`,
  granted: false,
  detail: null,
});
const edge = (a: GraphNode, b: GraphNode, source: GraphEdge['source'] = 'link'): GraphEdge => ({
  a: { kind: a.kind, id: a.id },
  b: { kind: b.kind, id: b.id },
  source,
});
const page = (nodes: readonly GraphNode[], edges: readonly GraphEdge[] = [], nextCursor: string | null = null): GraphPage => ({
  nodes,
  edges,
  nextCursor,
});

describe('graph util', () => {
  const m = node('meeting', '1');
  const t = node('agenda_item', '2');
  const c = node('todo', '3');

  it('keys a node by its kind and its id', () => {
    expect(nodeKey(m)).toBe('meeting:1');
    expect(AUTO_NODES).toBe(300);
  });

  /** § F/collaboration/graph/001426: the nodes that already show keep their identity. */
  it('adds a page and keeps the nodes and the lines that already show', () => {
    const first = merged(EMPTY_GRAPH, page([m, t], [edge(m, t, 'builtin'), edge(m, t, 'builtin')]));
    expect(first.nodes).toEqual([m, t]);
    expect(first.lines).toEqual([{ key: 'builtin|meeting:1|agenda_item:2', a: 'meeting:1', b: 'agenda_item:2', source: 'builtin' }]);

    const again = { ...m, title: 'changed' };
    const second = merged(first, page([again, c], [edge(m, t, 'builtin'), edge(c, m)]));
    expect(second.nodes).toHaveLength(3);
    expect(second.nodes[0]).toBe(m);
    expect(second.nodes[2]).toBe(c);
    expect(second.lines.map((l) => l.key)).toEqual(['builtin|meeting:1|agenda_item:2', 'link|todo:3|meeting:1']);
    expect(second.lines[0]).toBe(first.lines[0]);
  });

  it('lists the neighbours of each node once', () => {
    const graph = merged(EMPTY_GRAPH, page([m, t, c], [edge(m, t, 'builtin'), edge(m, t), edge(c, m)]));
    const near = neighbours(graph.lines);
    expect(near.get('meeting:1')).toEqual(['agenda_item:2', 'todo:3']);
    expect(near.get('agenda_item:2')).toEqual(['meeting:1']);
    expect(near.get('todo:9')).toBeUndefined();
  });

  it('knows when a filter or a switch is set', () => {
    expect(isFiltered(NO_FILTERS)).toBe(false);
    expect(isFiltered({ ...NO_FILTERS, q: '  ' })).toBe(false);
    for (const change of [
      { kinds: ['todo'] as const },
      { from: '2026-01-01' },
      { to: '2026-12-31' },
      { gremiumId: 'g1' },
      { relations: 'links' as const },
      { q: 'x' },
      { single: true },
      { noAccess: true },
    ]) {
      expect(isFiltered({ ...NO_FILTERS, ...change })).toBe(true);
    }
  });

  /** § F/collaboration/graph/001425: the filters are in the query of the URL. */
  it('reads the filters from the query', () => {
    expect(filtersOf(convertToParamMap({}))).toEqual(NO_FILTERS);
    const query = convertToParamMap({
      kinds: 'todo,bogus,meeting',
      from: '2026-01-01',
      to: '2026-12-31',
      gremium: 'g1',
      rel: 'builtin',
      q: 'Haushalt',
      single: '1',
      noaccess: '1',
    });
    expect(filtersOf(query)).toEqual({
      kinds: ['meeting', 'todo'],
      from: '2026-01-01',
      to: '2026-12-31',
      gremiumId: 'g1',
      relations: 'builtin',
      q: 'Haushalt',
      single: true,
      noAccess: true,
    });
  });

  it('drops unknown values of the query', () => {
    const filters = filtersOf(convertToParamMap({ from: 'gestern', to: '2026-1-1', rel: 'none', single: 'true' }));
    expect(filters).toEqual(NO_FILTERS);
  });

  it('writes the filters to the query and back', () => {
    expect(queryOf(NO_FILTERS)).toEqual({
      kinds: null,
      from: null,
      to: null,
      gremium: null,
      rel: null,
      q: null,
      single: null,
      noaccess: null,
    });
    const filters = {
      kinds: ['meeting', 'todo'] as const,
      from: '2026-01-01',
      to: '2026-12-31',
      gremiumId: 'g1',
      relations: 'links' as const,
      q: ' Haushalt ',
      single: true,
      noAccess: true,
    };
    const query = queryOf(filters);
    expect(query).toEqual({
      kinds: 'meeting,todo',
      from: '2026-01-01',
      to: '2026-12-31',
      gremium: 'g1',
      rel: 'links',
      q: 'Haushalt',
      single: '1',
      noaccess: '1',
    });
    expect(filtersOf(convertToParamMap(query))).toEqual({ ...filters, q: 'Haushalt' });
  });

  it('compares two sets of filters by what the server gets', () => {
    expect(sameFilters(NO_FILTERS, { ...NO_FILTERS, q: ' ' })).toBe(true);
    expect(sameFilters(NO_FILTERS, { ...NO_FILTERS, single: true })).toBe(false);
  });

  /** § F/collaboration/graph/001432: the kinds of a feature. */
  it('names the feature of each kind that has one', () => {
    expect(KIND_FEATURE.invoice).toBe('invoices');
    expect(KIND_FEATURE.agenda_item).toBe('meetings');
    expect(KIND_FEATURE.application).toBeUndefined();
    expect(KIND_FEATURE.gremium).toBeUndefined();
    expect(KIND_FEATURE.todo).toBeUndefined();
  });
});
