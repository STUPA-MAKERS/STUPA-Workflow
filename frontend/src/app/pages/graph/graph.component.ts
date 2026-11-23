import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Renderer2,
  computed,
  effect,
  inject,
  linkedSignal,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import type { Subscription } from 'rxjs';
import {
  GRAPH_DEPTH_MAX,
  GRAPH_KINDS,
  GRAPH_RELATIONS,
  GraphApiService,
  type GraphFilters,
  type GraphKind,
  type GraphNode,
  type GraphRelations,
} from '@core/api/graph.service';
import { FeatureService } from '@core/features/feature.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import { dayMonthYear } from '@shared/date-format';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import {
  ButtonComponent,
  ButtonGroupComponent,
  ButtonLinkComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  IconComponent,
  type IconName,
  MEDIA,
  RangeChipComponent,
  type RangeValue,
  SearchPillComponent,
  SideSheetComponent,
  mediaQuery,
  SheetBodyDirective,
} from '@stupa-makers/ui-kit';
import { LINK_ICON, LINK_KIND_LABEL, linkSub, splitUrl } from '../../features/todos/todos.util';
import { type CanvasNode, GraphCanvasComponent } from './graph-canvas.component';
import {
  AUTO_NODES,
  EMPTY_GRAPH,
  type Graph,
  KIND_FEATURE,
  defaultFilters,
  depthOf,
  filtersOf,
  isFiltered,
  localDay,
  merged,
  neighbours,
  nodeKey,
  queryOf,
  sameFilters,
} from './graph.util';

/** The pause after the last key before the search asks the server, in ms. */
export const SEARCH_PAUSE = 250;

/** A node as the drawing and the panel show it. */
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

/**
 * The page "Graph" (`/graph`, specs 001420-001432): the elements that the person reads as
 * nodes and the relations between them as lines.
 *
 * The server applies the read rules and every filter. The page loads 60 nodes per step and
 * adds each step to the drawing, by itself until 300 nodes show; then "Mehr laden" loads
 * the next 300. The filters are in the query of the URL. The drawing fills the page, and the
 * filters float over it. The field "Schritte" at the start corner of the foot, opposite the
 * zoom buttons, sets how far the neighbours of the hits show (spec 001434). A press on a node chooses it: the panel shows its facts and
 * "Öffnen", on a phone in a sheet. For a screen reader each node names its neighbours.
 */
@Component({
  selector: 'app-graph',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SheetBodyDirective,
    ButtonComponent,
    ButtonGroupComponent,
    ButtonLinkComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    GraphCanvasComponent,
    IconComponent,
    LoadErrorComponent,
    NgTemplateOutlet,
    RangeChipComponent,
    RouterLink,
    SearchPillComponent,
      SideSheetComponent,
    TranslatePipe,
  ],
  templateUrl: './graph.component.html',
  styleUrl: './graph.component.scss',
})
export class GraphComponent {
  /** The nodes of the skeleton: a centre and its neighbours, in px from the middle. */
  protected readonly skelNodes = [
    { x: 0, y: 0, w: 4 },
    { x: -70, y: -50, w: 6 },
    { x: 60, y: -65, w: 5 },
    { x: 85, y: 30, w: 6.5 },
    { x: -15, y: 80, w: 5.5 },
    { x: -90, y: 40, w: 4.5 },
  ] as const;

  /** The most steps of the field "Schritte" (spec 001434). */
  protected readonly maxDepth = GRAPH_DEPTH_MAX;

  private readonly api = inject(GraphApiService);
  private readonly renderer = inject(Renderer2);
  private readonly i18n = inject(I18nService);
  private readonly features = inject(FeatureService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly t: Translate = (key, params) => this.i18n.translate(key, params);

  /** The day of the fresh filters (spec 001425): the day on which the page opened. */
  private readonly today = localDay(new Date());
  readonly filters = signal<GraphFilters>(filtersOf(this.route.snapshot.queryParamMap, this.today));
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
  readonly relationOptions = computed(() =>
    GRAPH_RELATIONS.map((r) => ({ value: r, label: this.i18n.translate(`graph.relations.${r}` as TranslationKey) })),
  );
  /** The chip text (spec 000663): the name, then name and value. */
  readonly relationsText = computed(() => {
    const name = this.i18n.translate('graph.filter.relations');
    const relations = this.filters().relations;
    // The default of a fresh page (spec 001425) is no choice: the chip shows only its name.
    if (relations === 'links') return name;
    return `${name}: ${this.i18n.translate(`graph.relations.${relations}` as TranslationKey)}`;
  });

  readonly phone = mediaQuery(MEDIA.phone);
  /** Where the drawing shows a chosen node: beside the panel, on a phone above the sheet. */
  readonly focusAt = computed(() => (this.phone() ? { x: 0.5, y: 0.3 } : { x: 0.6, y: 0.5 }));

  readonly filtered = computed(() => isFiltered(this.filters(), this.today));
  readonly empty = computed(() => this.graph().nodes.length === 0);
  /** True while the drawing shows. */
  readonly drawing = computed(() => !this.loading() && !this.error() && !this.empty());

  readonly rows = computed<ReadonlyMap<string, GraphRow>>(() => {
    const locale = this.i18n.locale();
    return new Map(this.graph().nodes.map((n) => [nodeKey(n), this.row(n, locale)] as const));
  });

  private readonly near = computed(() => neighbours(this.graph().lines));

  readonly canvasNodes = computed<readonly CanvasNode[]>(() => {
    const rows = this.rows();
    const near = this.near();
    return Array.from(rows.values()).map((r) => ({
      key: r.key,
      kind: r.node.kind,
      icon: r.icon,
      title: r.title,
      name: r.node.accessible ? `${r.kind}: ${r.title}` : r.title,
      muted: !r.node.accessible,
      near: this.nearText(near.get(r.key), rows),
    }));
  });

  /** The chosen node; null without a choice. */
  readonly chosen = computed<GraphRow | null>(() => {
    const key = this.selected();
    return (key === null ? undefined : this.rows().get(key)) ?? null;
  });
  /** The node of the sheet: it stays while the sheet goes after the end of the choice. */
  readonly sheetRow = linkedSignal<GraphRow | null, GraphRow | null>({
    source: this.chosen,
    computation: (row, before) => row ?? before?.value ?? null,
  });

  /** The label of the drawing for a screen reader (spec 001428). */
  readonly canvasLabel = computed(() =>
    this.i18n.translate('graph.canvas.label', {
      nodes: this.graph().nodes.length,
      lines: this.graph().lines.length,
    }),
  );

  constructor() {
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((query) => {
      const filters = filtersOf(query, this.today);
      if (!sameFilters(filters, this.filters())) {
        this.filters.set(filters);
        this.searchText.set(filters.q);
      }
    });

    effect(() => {
      const filters = this.filters();
      untracked(() => this.load(filters));
    });

    effect(() => {
      const queryParams = queryOf(this.filters(), this.today);
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

  setKinds(values: readonly string[]): void {
    this.patch({ kinds: GRAPH_KINDS.filter((k) => values.includes(k)) });
  }

  setPeriod(range: RangeValue): void {
    this.patch({ from: range.from, to: range.to });
  }

  setRelations(value: string): void {
    this.patch({ relations: (GRAPH_RELATIONS as readonly string[]).includes(value) ? (value as GraphRelations) : 'all' });
  }

  /** Set the steps from a hit to the farthest neighbour that shows (spec 001434). */
  setDepth(value: number): void {
    this.patch({ depth: depthOf(value) });
  }

  /** The field "Schritte" changed: take the count and write the count that holds back. */
  onDepth(event: Event): void {
    const field = event.target as HTMLInputElement;
    this.setDepth(field.value.trim() === '' ? Number.NaN : Number(field.value));
    this.renderer.setProperty(field, 'value', String(this.filters().depth));
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
    this.filters.set(defaultFilters(this.today));
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

  /** The neighbours of a node as one line of text (spec 001428); empty without one. */
  private nearText(keys: readonly string[] | undefined, rows: ReadonlyMap<string, GraphRow>): string {
    const names = (keys ?? []).flatMap((key) => {
      const row = rows.get(key);
      return row ? [row.title] : [];
    });
    return names.length ? this.i18n.translate('graph.node.near', { names: names.join(', ') }) : '';
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
