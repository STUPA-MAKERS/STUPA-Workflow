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

/** The days that the period reaches back when the person chose none (spec 001425). */
export const DEFAULT_DAYS = 30;
/** The value of `period` in the query that stands for every day. */
const ALL = 'all';

/** The local day of a moment as `YYYY-MM-DD`. */
export function localDay(now: Date): string {
  const two = (n: number): string => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}`;
}

/** The day that is `days` before `day`, both as `YYYY-MM-DD`. */
export function daysBefore(day: string, days: number): string {
  return new Date(Date.parse(`${day}T00:00:00Z`) - days * 86_400_000).toISOString().slice(0, 10);
}

/** The filters of a fresh page: the last 30 days and only the links of persons (spec 001425). */
export function defaultFilters(today: string): GraphFilters {
  return { ...NO_FILTERS, from: daysBefore(today, DEFAULT_DAYS), relations: 'links' };
}

function plain(f: GraphFilters): string {
  return JSON.stringify({ ...f, kinds: GRAPH_KINDS.filter((k) => f.kinds.includes(k)), q: f.q.trim() });
}

/** True when two sets of filters ask the server for the same graph. */
export function sameFilters(a: GraphFilters, b: GraphFilters): boolean {
  return plain(a) === plain(b);
}

/** True while a filter or a switch differs from the fresh page. */
export function isFiltered(f: GraphFilters, today: string): boolean {
  return !sameFilters(f, defaultFilters(today));
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

function day(value: string | null): string {
  return value !== null && DAY.test(value) ? value : '';
}

/**
 * The filters from the query of the URL (spec 001425). Unknown values drop. A query without
 * a period or without relations means the fresh page; `all` means every day or every relation.
 */
export function filtersOf(query: ParamMap, today: string): GraphFilters {
  const fresh = defaultFilters(today);
  const kinds = (query.get('kinds') ?? '').split(',');
  const relations = query.get('rel') as GraphRelations | null;
  const from = day(query.get('from'));
  const to = day(query.get('to'));
  const own = from !== '' || to !== '' || query.get('period') === ALL;
  return {
    kinds: GRAPH_KINDS.filter((k) => kinds.includes(k)),
    from: own ? from : fresh.from,
    to,
    gremiumId: query.get('gremium') ?? '',
    relations: relations !== null && GRAPH_RELATIONS.includes(relations) ? relations : fresh.relations,
    q: query.get('q') ?? '',
    single: query.get('single') === '1',
    noAccess: query.get('noaccess') === '1',
  };
}

/** The query of the URL for the filters; null removes a parameter. The fresh page has none. */
export function queryOf(f: GraphFilters, today: string): Readonly<Record<string, string | null>> {
  const fresh = defaultFilters(today);
  const freshPeriod = f.from === fresh.from && f.to === '';
  return {
    kinds: f.kinds.length ? f.kinds.join(',') : null,
    from: freshPeriod ? null : f.from || null,
    to: f.to || null,
    period: f.from === '' && f.to === '' ? ALL : null,
    gremium: f.gremiumId || null,
    rel: f.relations === fresh.relations ? null : f.relations,
    q: f.q.trim() || null,
    single: f.single ? '1' : null,
    noaccess: f.noAccess ? '1' : null,
  };
}
