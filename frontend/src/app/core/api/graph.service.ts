/**
 * API of the graph page (`/api/graph`, specs 001420-001432): the elements that the person
 * reads as nodes and the relations between them as edges.
 *
 * The server applies the read rule of each kind and every filter, so the client only draws
 * the answer. A page holds at most 60 nodes, the newest first, and each edge between a node
 * of the page and a node of this page or of an earlier page. The next page starts at
 * `nextCursor`.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';
import type { TodoLinkDetail, TodoLinkKind } from '@core/api/todos.service';
import { skipLoading } from '@stupa-makers/ui-kit';
import { httpParams } from './http-params';

/** The kinds of node: the kinds that link (spec 001400), in the order of the filter. */
export type GraphKind = TodoLinkKind;
export const GRAPH_KINDS: readonly GraphKind[] = [
  'application',
  'meeting',
  'agenda_item',
  'vote',
  'appointment',
  'gremium',
  'invoice',
  'expense',
  'order',
  'budget',
  'ticket',
  'todo',
  'paperless',
];

/** `link` is a link that a person made, `builtin` a relation of the data (spec 001424). */
export type GraphSource = 'link' | 'builtin';
/** The choices of the filter "Beziehungen". */
export type GraphRelations = 'all' | 'links' | 'builtin';
export const GRAPH_RELATIONS: readonly GraphRelations[] = ['all', 'links', 'builtin'];

export interface GraphRef {
  readonly kind: GraphKind;
  readonly id: Uuid;
}

/** One element. Without `accessible` it has its kind and its id only (spec 001422). */
export interface GraphNode extends GraphRef {
  readonly accessible: boolean;
  readonly title: string | null;
  /** The day of the element, `YYYY-MM-DD`; a Gremium and a cost centre have none. */
  readonly date: string | null;
  /** The detail page; a granted node has none. */
  readonly url: string | null;
  /** Readable only through a card (spec 000487). */
  readonly granted: boolean;
  readonly detail: TodoLinkDetail | null;
}

export interface GraphEdge {
  readonly a: GraphRef;
  readonly b: GraphRef;
  readonly source: GraphSource;
}

export interface GraphPage {
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
  readonly nextCursor: string | null;
}

/** The steps from a hit to the farthest neighbour that shows (spec 001434). */
export const GRAPH_DEPTH_DEFAULT = 2;
export const GRAPH_DEPTH_MAX = 5;

/** The filters of the page (spec 001425), the steps (spec 001434) and its two switches. */
export interface GraphFilters {
  readonly kinds: readonly GraphKind[];
  readonly from: string;
  readonly to: string;
  readonly relations: GraphRelations;
  readonly q: string;
  /** The steps from a hit to the farthest neighbour that shows, 0 to 5. */
  readonly depth: number;
  readonly single: boolean;
  readonly noAccess: boolean;
}

@Injectable({ providedIn: 'root' })
export class GraphApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  /** One page of the graph with these filters. */
  page(filters: GraphFilters, cursor: string | null = null): Observable<GraphPage> {
    const params = httpParams({
      kinds: filters.kinds.length ? filters.kinds : undefined,
      from: filters.from || undefined,
      to: filters.to || undefined,
      relations: filters.relations === 'all' ? undefined : filters.relations,
      q: filters.q.trim() || undefined,
      depth: filters.depth === GRAPH_DEPTH_DEFAULT ? undefined : filters.depth,
      single: filters.single ? true : undefined,
      noAccess: filters.noAccess ? true : undefined,
      cursor: cursor ?? undefined,
    });
    return this.http.get<GraphPage>(`${this.base}/graph`, { params, context: skipLoading() });
  }
}
