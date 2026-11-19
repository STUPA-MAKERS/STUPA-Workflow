import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import type { Subscription } from 'rxjs';
import {
  GRAPH_KINDS,
  GRAPH_RELATIONS,
  GraphApiService,
  type GraphFilters,
  type GraphKind,
  type GraphNode,
  type GraphRelations,
} from '@core/api/graph.service';
import { GremienApiService, type GremiumOverview } from '@core/api/gremien.service';
import { FeatureService } from '@core/features/feature.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import { dayMonthYear } from '@shared/date-format';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import {
  ButtonComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  IconComponent,
  type IconName,
  MEDIA,
  RangeChipComponent,
  type RangeValue,
  SearchPillComponent,
  SegmentedComponent,
  SkeletonComponent,
  mediaQuery,
} from '@stupa-makers/ui-kit';
import { LINK_ICON, LINK_KIND_LABEL, linkSub, splitUrl } from '../../features/todos/todos.util';
import { type CanvasNode, GraphCanvasComponent } from './graph-canvas.component';
import {
  AUTO_NODES,
  EMPTY_GRAPH,
  type Graph,
  type GraphView,
  KIND_FEATURE,
  NO_FILTERS,
  filtersOf,
  isFiltered,
  merged,
  neighbours,
  nodeKey,
  queryOf,
  sameFilters,
  viewOf,
} from './graph.util';

/** The pause after the last key before the search asks the server, in ms. */
export const SEARCH_PAUSE = 250;

/** A node as the panel and the list show it. */
export interface GraphRow {
  readonly key: string;
  readonly node: GraphNode;
  readonly icon: IconName;
  readonly kind: string;
  readonly title: string;
  readonly date: string | null;
  /** The target of "Öffnen"; null for an element without a page for this person. */
  readonly route: ReturnType<typeof splitUrl> | null;
}

/** A row of the list with its neighbours. */
export interface GraphListRow extends GraphRow {
  readonly near: readonly GraphRow[];
}

/**
 * The page "Graph" (`/graph`, specs 001420-001432): the elements that the person reads as
 * nodes and the relations between them as lines.
 *
 * The server applies the read rules and every filter. The page loads 60 nodes per step and
 * adds each step to the drawing, by itself until 300 nodes show; then "Mehr laden" loads
 * the next 300. The filters and the view are in the query of the URL. A press on a node
 * chooses it: the panel shows its facts, its neighbours and "Öffnen". The view "Liste"
 * shows the same nodes as rows, for a screen reader and for a person who prefers text.
 */
@Component({
  selector: 'app-graph',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    GraphCanvasComponent,
    IconComponent,
    LoadErrorComponent,
      RangeChipComponent,
    RouterLink,
    SearchPillComponent,
    SegmentedComponent,
    SkeletonComponent,
      TranslatePipe,
  ],
  templateUrl: './graph.component.html',
  styleUrl: './graph.component.scss',
})
export class GraphComponent {
  private readonly api = inject(GraphApiService);
  private readonly gremienApi = inject(GremienApiService);
  private readonly i18n = inject(I18nService);
  private readonly features = inject(FeatureService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly t: Translate = (key, params) => this.i18n.translate(key, params);

  readonly filters = signal<GraphFilters>(filtersOf(this.route.snapshot.queryParamMap));
  readonly view = signal<GraphView>(viewOf(this.route.snapshot.queryParamMap));
  /** The text of the search field; it reaches the filters after a pause. */
  readonly searchText = signal(this.filters().q);

  readonly graph = signal<Graph>(EMPTY_GRAPH);
  readonly cursor = signal<string | null>(null);
  /** True until the first step of a build-up arrives. */
  readonly loading = signal(true);
  /** True while a later step loads. */
  readonly growing = signal(false);
  readonly error = signal(false);
  /** The nodes up to which the page loads by itself (spec 001426). */
  readonly limit = signal(AUTO_NODES);
  readonly selected = signal<string | null>(null);
  readonly gremien = signal<readonly GremiumOverview[]>([]);

  private request: Subscription | null = null;
  private searchTimer: ReturnType<typeof setTimeout> | null = null;

  /** The kinds that this platform has (spec 001432). */
  readonly kinds = computed<readonly GraphKind[]>(() =>
    GRAPH_KINDS.filter((k) => {
      const feature = KIND_FEATURE[k];
      return feature === undefined || this.features.isOn(feature);
    }),
  );

  readonly kindOptions = computed(() => this.kinds().map((k) => ({ value: k, label: this.kindLabel(k) })));
  readonly legend = computed(() =>
    this.kinds().map((k) => ({ kind: k, icon: LINK_ICON[k], label: this.kindLabel(k), on: this.filters().kinds.includes(k) })),
  );
  readonly gremiumOptions = computed(() => [
    { value: '', label: this.i18n.translate('graph.filter.allGremien') },
    ...this.gremien().map((g) => ({ value: g.id, label: g.name })),
  ]);
  readonly gremiumText = computed(
    () => this.gremien().find((g) => g.id === this.filters().gremiumId)?.name ?? this.i18n.translate('graph.filter.gremium'),
  );
  readonly relationOptions = computed(() =>
    GRAPH_RELATIONS.map((r) => ({ value: r, label: this.i18n.translate(`graph.relations.${r}` as TranslationKey) })),
  );
  readonly relationsText = computed(() =>
    this.i18n.translate(`graph.relations.${this.filters().relations}` as TranslationKey),
  );
  readonly viewOptions = computed(() => [
    { value: 'graph', label: this.i18n.translate('graph.view.graph') },
    { value: 'list', label: this.i18n.translate('graph.view.list') },
  ]);

  readonly phone = mediaQuery(MEDIA.phone);
  /** Where the drawing shows a chosen node: beside the panel, on a phone above it. */
  readonly focusAt = computed(() => (this.phone() ? { x: 0.5, y: 0.3 } : { x: 0.6, y: 0.5 }));

  readonly filtered = computed(() => isFiltered(this.filters()));
  readonly empty = computed(() => this.graph().nodes.length === 0);
  /** True while the drawing shows: then the panel and the legend float over it. */
  readonly drawing = computed(() => this.view() === 'graph' && !this.loading() && !this.error() && !this.empty());

  readonly rows = computed<ReadonlyMap<string, GraphRow>>(() => {
    const locale = this.i18n.locale();
    return new Map(this.graph().nodes.map((n) => [nodeKey(n), this.row(n, locale)] as const));
  });

  private readonly near = computed(() => neighbours(this.graph().lines));

  readonly canvasNodes = computed<readonly CanvasNode[]>(() =>
    Array.from(this.rows().values()).map((r) => ({
      key: r.key,
      kind: r.node.kind,
      icon: r.icon,
      title: r.title,
      name: r.node.accessible ? `${r.kind}: ${r.title}` : r.title,
      muted: !r.node.accessible,
    })),
  );

  readonly listRows = computed<readonly GraphListRow[]>(() => {
    const rows = this.rows();
    const near = this.near();
    return Array.from(rows.values()).map((r) => ({ ...r, near: this.rowsOf(near.get(r.key), rows) }));
  });

  /** The chosen node with its neighbours; null without a choice. */
  readonly chosen = computed<GraphListRow | null>(() => {
    const key = this.selected();
    const row = key === null ? undefined : this.rows().get(key);
    return row ? { ...row, near: this.rowsOf(this.near().get(row.key), this.rows()) } : null;
  });

  /** The label of the drawing for a screen reader (spec 001428). */
  readonly canvasLabel = computed(() =>
    this.i18n.translate('graph.canvas.label', {
      nodes: this.graph().nodes.length,
      lines: this.graph().lines.length,
    }),
  );

  constructor() {
    this.gremienApi
      .overview()
      .pipe(takeUntilDestroyed())
      .subscribe({ next: (list) => this.gremien.set(list), error: () => undefined });

    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((query) => {
      const filters = filtersOf(query);
      if (!sameFilters(filters, this.filters())) {
        this.filters.set(filters);
        this.searchText.set(filters.q);
      }
      this.view.set(viewOf(query));
    });

    effect(() => {
      const filters = this.filters();
      untracked(() => this.load(filters));
    });

    effect(() => {
      const queryParams = queryOf(this.filters(), this.view());
      untracked(
        () =>
          void this.router.navigate([], {
            relativeTo: this.route,
            queryParams,
            queryParamsHandling: 'merge',
            replaceUrl: true,
          }),
      );
    });

    inject(DestroyRef).onDestroy(() => {
      this.request?.unsubscribe();
      if (this.searchTimer !== null) clearTimeout(this.searchTimer);
    });
  }

  setView(value: string | null): void {
    this.view.set(value === 'list' ? 'list' : 'graph');
  }

  setKinds(values: readonly string[]): void {
    this.patch({ kinds: GRAPH_KINDS.filter((k) => values.includes(k)) });
  }

  /** A press on a kind of the legend switches it in the filter "Art" (spec 001430). */
  toggleKind(kind: GraphKind): void {
    const kinds = this.filters().kinds;
    this.patch({ kinds: GRAPH_KINDS.filter((k) => (k === kind ? !kinds.includes(k) : kinds.includes(k))) });
  }

  setPeriod(range: RangeValue): void {
    this.patch({ from: range.from, to: range.to });
  }

  setGremium(value: string): void {
    this.patch({ gremiumId: value });
  }

  setRelations(value: string): void {
    this.patch({ relations: (GRAPH_RELATIONS as readonly string[]).includes(value) ? (value as GraphRelations) : 'all' });
  }

  toggleSingle(): void {
    this.patch({ single: !this.filters().single });
  }

  toggleNoAccess(): void {
    this.patch({ noAccess: !this.filters().noAccess });
  }

  setSearch(text: string): void {
    this.searchText.set(text);
    if (this.searchTimer !== null) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => {
      this.searchTimer = null;
      this.patch({ q: text });
    }, SEARCH_PAUSE);
  }

  reset(): void {
    if (this.searchTimer !== null) clearTimeout(this.searchTimer);
    this.searchTimer = null;
    this.searchText.set('');
    this.filters.set(NO_FILTERS);
  }

  retry(): void {
    this.load(this.filters());
  }

  /** "Mehr laden": the next 300 nodes (spec 001426). */
  loadMore(): void {
    const cursor = this.cursor();
    if (cursor === null || this.growing() || this.loading()) return;
    this.limit.update((n) => n + AUTO_NODES);
    this.fetch(this.filters(), cursor);
  }

  choose(key: string | null): void {
    this.selected.set(key);
  }

  private kindLabel(kind: GraphKind): string {
    return this.i18n.translate(LINK_KIND_LABEL[kind]);
  }

  private patch(change: Partial<GraphFilters>): void {
    const next = { ...this.filters(), ...change };
    if (!sameFilters(next, this.filters())) this.filters.set(next);
  }

  private rowsOf(keys: readonly string[] | undefined, rows: ReadonlyMap<string, GraphRow>): readonly GraphRow[] {
    return (keys ?? []).flatMap((key) => {
      const row = rows.get(key);
      return row ? [row] : [];
    });
  }

  private row(node: GraphNode, locale: string): GraphRow {
    const kind = this.kindLabel(node.kind);
    return {
      key: nodeKey(node),
      node,
      icon: LINK_ICON[node.kind],
      kind,
      title: node.accessible
        ? node.title || this.i18n.translate('graph.untitled')
        : this.i18n.translate('todos.link.noAccess', { kind }),
      date: node.date ? dayMonthYear(node.date, locale) : null,
      route: node.url ? splitUrl(node.url) : null,
    };
  }

  /** The line of facts of the chosen element: its kind and its state. */
  facts(row: GraphRow): string {
    return linkSub(row.node, this.i18n.locale(), this.i18n.uiLocale(), this.t);
  }

  /** The date of the chosen element, unless the line of facts already has it. */
  dateLine(row: GraphRow): string | null {
    return row.date !== null && !this.facts(row).includes(row.date) ? row.date : null;
  }

  /** Start the build-up again (spec 001426). */
  private load(filters: GraphFilters): void {
    this.request?.unsubscribe();
    this.graph.set(EMPTY_GRAPH);
    this.cursor.set(null);
    this.selected.set(null);
    this.limit.set(AUTO_NODES);
    this.loading.set(true);
    this.growing.set(false);
    this.error.set(false);
    this.fetch(filters, null);
  }

  private fetch(filters: GraphFilters, cursor: string | null): void {
    this.request?.unsubscribe();
    this.growing.set(cursor !== null);
    this.request = this.api.page(filters, cursor).subscribe({
      next: (page) => {
        this.graph.update((g) => merged(g, page));
        this.cursor.set(page.nextCursor);
        this.loading.set(false);
        if (page.nextCursor !== null && this.graph().nodes.length < this.limit()) {
          this.fetch(filters, page.nextCursor);
        } else {
          this.growing.set(false);
        }
      },
      error: () => {
        this.error.set(cursor === null);
        this.loading.set(false);
        this.growing.set(false);
      },
    });
  }
}
