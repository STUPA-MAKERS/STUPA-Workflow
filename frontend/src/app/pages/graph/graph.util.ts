/**
 * The data of the graph page as pure functions (specs 001420-001432): the key of a node,
 * the graph that grows page by page, the neighbours of a node, and the filters in the query
 * of the URL.
 */
import type { ParamMap } from '@angular/router';
import type { FeatureKey } from '@core/features/feature.service';
import {
  GRAPH_KINDS,
  GRAPH_RELATIONS,
  type GraphEdge,
  type GraphFilters,
  type GraphKind,
  type GraphNode,
  type GraphPage,
  type GraphRef,
  type GraphRelations,
  type GraphSource,
} from '@core/api/graph.service';

/** The nodes that load by themselves; then "Mehr laden" loads the next ones (spec 001426). */
export const AUTO_NODES = 300;

/** The feature that a kind needs (spec 001432); an Antrag, a Gremium and a card need none. */
export const KIND_FEATURE: Readonly<Partial<Record<GraphKind, FeatureKey>>> = {
  meeting: 'meetings',
  agenda_item: 'meetings',
  vote: 'voting',
  appointment: 'calendar',
  invoice: 'invoices',
  expense: 'budget',
  budget: 'budget',
  ticket: 'tickets',
};

/** The key of a node: its kind and its id. */
export function nodeKey(ref: GraphRef): string {
  return `${ref.kind}:${ref.id}`;
}

/** A line of the drawing between two node keys. */
export interface GraphLine {
  readonly key: string;
  readonly a: string;
  readonly b: string;
  readonly source: GraphSource;
}

/** The graph that shows: the nodes in the order of their arrival, and the lines. */
export interface Graph {
  readonly nodes: readonly GraphNode[];
  readonly lines: readonly GraphLine[];
}

export const EMPTY_GRAPH: Graph = { nodes: [], lines: [] };

function lineOf(edge: GraphEdge): GraphLine {
  const a = nodeKey(edge.a);
  const b = nodeKey(edge.b);
  return { key: `${edge.source}|${a}|${b}`, a, b, source: edge.source };
}

/**
 * Add a page to the graph. A node that already shows keeps its object, so the drawing keeps
 * its element and its place (spec 001426). A line shows once.
 */
export function merged(graph: Graph, page: GraphPage): Graph {
  const known = new Set(graph.nodes.map(nodeKey));
  const lines = new Set(graph.lines.map((l) => l.key));
  const fresh = page.edges.map(lineOf).filter((l, i, all) => !lines.has(l.key) && all.findIndex((o) => o.key === l.key) === i);
  return {
    nodes: [...graph.nodes, ...page.nodes.filter((n) => !known.has(nodeKey(n)))],
    lines: [...graph.lines, ...fresh],
  };
}

/** The keys of the neighbours of each node, in the order of the lines and without doubles. */
export function neighbours(lines: readonly GraphLine[]): ReadonlyMap<string, readonly string[]> {
  const pairs = lines.flatMap((l) => [[l.a, l.b] as const, [l.b, l.a] as const]);
  return pairs.reduce((map, [own, other]) => {
    const list = map.get(own) ?? [];
    return list.includes(other) ? map : new Map(map).set(own, [...list, other]);
  }, new Map<string, readonly string[]>());
}

export const NO_FILTERS: GraphFilters = {
  kinds: [],
  from: '',
  to: '',
  gremiumId: '',
  relations: 'all',
  q: '',
  single: false,
  noAccess: false,
};

/** True while a filter or a switch is set. */
export function isFiltered(f: GraphFilters): boolean {
  return (
    f.kinds.length > 0 ||
    f.from !== '' ||
    f.to !== '' ||
    f.gremiumId !== '' ||
    f.relations !== 'all' ||
    f.q.trim() !== '' ||
    f.single ||
    f.noAccess
  );
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

function day(value: string | null): string {
  return value !== null && DAY.test(value) ? value : '';
}

/** The view of the page: the drawing or the list (spec 001428). */
export type GraphView = 'graph' | 'list';

/** The filters and the view from the query of the URL (spec 001425). Unknown values drop. */
export function filtersOf(query: ParamMap): GraphFilters {
  const kinds = (query.get('kinds') ?? '').split(',');
  const relations = query.get('rel') as GraphRelations | null;
  return {
    kinds: GRAPH_KINDS.filter((k) => kinds.includes(k)),
    from: day(query.get('from')),
    to: day(query.get('to')),
    gremiumId: query.get('gremium') ?? '',
    relations: relations !== null && GRAPH_RELATIONS.includes(relations) ? relations : 'all',
    q: query.get('q') ?? '',
    single: query.get('single') === '1',
    noAccess: query.get('noaccess') === '1',
  };
}

export function viewOf(query: ParamMap): GraphView {
  return query.get('view') === 'list' ? 'list' : 'graph';
}

/** The query of the URL for the filters and the view; null removes a parameter. */
export function queryOf(f: GraphFilters, view: GraphView): Readonly<Record<string, string | null>> {
  return {
    kinds: f.kinds.length ? f.kinds.join(',') : null,
    from: f.from || null,
    to: f.to || null,
    gremium: f.gremiumId || null,
    rel: f.relations === 'all' ? null : f.relations,
    q: f.q.trim() || null,
    single: f.single ? '1' : null,
    noaccess: f.noAccess ? '1' : null,
    view: view === 'list' ? 'list' : null,
  };
}

/** True when two sets of filters ask the server for the same graph. */
export function sameFilters(a: GraphFilters, b: GraphFilters): boolean {
  return JSON.stringify(queryOf(a, 'graph')) === JSON.stringify(queryOf(b, 'graph'));
}
