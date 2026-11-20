import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, input, output } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { screen, within } from '@testing-library/angular';
import { NEVER, type Observable, Subject, of, throwError } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import {
  GRAPH_KINDS,
  GraphApiService,
  type GraphEdge,
  type GraphFilters,
  type GraphNode,
  type GraphPage,
} from '@core/api/graph.service';
import { GremienApiService } from '@core/api/gremien.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { loadErrorToast, retryLoadError } from '../../../testing/load-error';
import { matchMediaQueries } from '../../../testing/meeting-fixtures';
import { type CanvasNode, GraphCanvasComponent } from './graph-canvas.component';
import { GraphComponent, SEARCH_PAUSE } from './graph.component';
import { AUTO_NODES, defaultFilters, localDay } from './graph.util';

/** The filters of a fresh page (spec 001425): the last 30 days, only the links of persons. */
const FRESH = defaultFilters(localDay(new Date()));

@Component({ standalone: true, template: '<p>Ziel</p>' })
class TargetStub {}

/** The drawing without its layout, for a test of the build-up with hundreds of nodes. */
@Component({ selector: 'app-graph-canvas', standalone: true, template: '' })
class CanvasStub {
  readonly nodes = input<readonly CanvasNode[]>([]);
  readonly lines = input<readonly unknown[]>([]);
  readonly selected = input<string | null>(null);
  readonly label = input('');
  readonly focusAt = input({ x: 0.5, y: 0.5 });
  readonly edge = input(0);
  readonly chosen = output<string | null>();
}

function node(kind: GraphNode['kind'], id: string, over: Partial<GraphNode> = {}): GraphNode {
  return {
    kind,
    id,
    accessible: true,
    title: `${kind} ${id}`,
    date: null,
    url: `/${kind}/${id}`,
    granted: false,
    detail: null,
    ...over,
  };
}
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
/** `count` cards from `from`, each linked to the card before it. */
function cards(from: number, count: number, nextCursor: string | null): GraphPage {
  const nodes = Array.from({ length: count }, (_, i) => node('todo', String(from + i), { title: `Karte ${from + i}` }));
  return page(nodes, nodes.slice(1).map((n, i) => edge(nodes[i], n)), nextCursor);
}

const MEETING = node('meeting', '1', { title: 'Sondersitzung', date: '2026-11-03', url: '/meetings/1' });
const TOP = node('agenda_item', '2', { title: 'TOP 1: Haushalt', date: '2026-11-03', url: '/meetings/1?top=2' });
const CARD = node('todo', '3', { title: 'Flyer drucken', url: '/todos/b1?card=3' });
const GRANTED = node('application', '4', { title: 'Antrag Sommerfest', url: null, granted: true });
const HIDDEN = node('invoice', '5', { accessible: false, title: null, url: null });
const LONE = node('vote', '6', { title: '', url: '/voting/6' });
const SMALL = page([MEETING, TOP], [edge(MEETING, TOP, 'builtin')]);
const FULL = page(
  [MEETING, TOP, CARD, GRANTED, HIDDEN, LONE],
  [edge(MEETING, TOP, 'builtin'), edge(CARD, MEETING), edge(MEETING, GRANTED), edge(MEETING, HIDDEN), edge(TOP, LONE, 'builtin')],
);

type Answer = () => Observable<GraphPage>;

async function start(
  url = '/graph',
  answers: Answer[] = [],
  gremien: Observable<unknown> = of([{ id: 'g1', name: 'StuPa' }]),
  stub = false,
) {
  localStorage.setItem('ap.locale', 'de');
  document.documentElement.setAttribute('data-display-motion', 'reduce');
  const calls: { readonly filters: GraphFilters; readonly cursor: string | null }[] = [];
  const api = {
    page: jest.fn((filters: GraphFilters, cursor: string | null = null) => {
      calls.push({ filters, cursor });
      const next = answers.shift();
      return next ? next() : of(SMALL);
    }),
  };
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        { path: 'graph', component: GraphComponent },
        { path: '**', component: TargetStub },
      ]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: GraphApiService, useValue: api },
      { provide: GremienApiService, useValue: { overview: jest.fn(() => gremien) } },
    ],
  });
  if (stub) {
    TestBed.overrideComponent(GraphComponent, {
      remove: { imports: [GraphCanvasComponent] },
      add: { imports: [CanvasStub] },
    });
  }
  const harness = await RouterTestingHarness.create();
  await harness.navigateByUrl(url);
  const settle = async (): Promise<void> => {
    harness.detectChanges();
    await harness.fixture.whenStable();
    harness.detectChanges();
  };
  await settle();
  const cmp = harness.routeDebugElement?.componentInstance as GraphComponent;
  const el = harness.routeNativeElement as HTMLElement;
  return { harness, api, calls, settle, cmp, el, router: TestBed.inject(Router) };
}

const last = <T>(list: readonly T[]): T => list[list.length - 1];

describe('GraphComponent', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('data-display-motion');
    localStorage.clear();
  });

  /** § F/collaboration/graph/001420 and 001428: the drawing with its nodes, lines and label. */
  it('draws the first page and names the drawing for a screen reader', async () => {
    const { calls, el, router } = await start('/graph', [() => of(FULL)]);
    expect(calls).toEqual([{ filters: FRESH, cursor: null }]);
    // § 001425: no title shows, and the filters are in the layer over the drawing.
    expect(el.querySelector('#gr-title')).toHaveTextContent('Graph');
    expect(el.querySelector('#gr-title')).toHaveClass('sr-only');
    expect(el.querySelector('.gr__float .gr__bar [role="search"]')).not.toBeNull();
    expect(el.querySelector('.gr__foot')).toBeNull();
    expect(screen.queryByRole('group', { name: 'Legende' })).toBeNull();
    expect(
      screen.getByRole('group', {
        name: 'Graph mit 6 Elementen und 5 Beziehungen.',
      }),
    ).toBeInTheDocument();
    const meeting = screen.getByRole('button', { name: 'Sitzung: Sondersitzung' });
    expect(meeting).toHaveAttribute('data-kind', 'meeting');
    // § 001428: a node names its neighbours for a screen reader.
    expect(meeting).toHaveAccessibleDescription(
      'Verbunden mit: TOP 1: Haushalt, Flyer drucken, Antrag Sommerfest, Rechnung (kein Zugriff)',
    );
    expect(screen.getByRole('button', { name: 'Abstimmung: Ohne Titel' })).toBeInTheDocument();
    // § 001422: an element without access has its kind only.
    expect(screen.getByRole('button', { name: 'Rechnung (kein Zugriff)' })).toHaveClass('gc__node--muted');
    expect(el.querySelectorAll('.gc__line')).toHaveLength(5);
    expect(el.querySelectorAll('.gc__line--builtin')).toHaveLength(2);
    expect(screen.queryByTestId('gr-more')).toBeNull();
    expect(screen.queryByTestId('gr-reset')).toBeNull();
    expect(router.url).toBe('/graph');
  });

  /** § F/collaboration/graph/001432: a kind of a feature that is off is not offered. */
  it('does not offer the kinds of a feature that is off', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['invoices']));
    const { cmp } = await start();
    expect(cmp.kinds()).toEqual(GRAPH_KINDS.filter((k) => k !== 'invoice'));
    expect(cmp.kindOptions().map((o) => o.label)).not.toContain('Rechnung');
    expect(cmp.kindOptions().map((o) => o.label)).toContain('TOP');
  });

  /** § F/collaboration/graph/001426: the build-up, page by page, until 300 nodes show. */
  it('loads the pages by itself until 300 nodes show, then "Mehr laden" loads on', async () => {
    const first = cards(0, 60, '60');
    const { calls, cmp, settle } = await start(
      '/graph',
      [
        () => of(first),
        () => of(cards(60, 60, '120')),
        () => of(cards(120, 60, '180')),
        () => of(cards(180, 60, '240')),
        () => of(cards(240, 60, '300')),
        () => of(cards(300, 10, null)),
      ],
      undefined,
      true,
    );
    expect(calls.map((c) => c.cursor)).toEqual([null, '60', '120', '180', '240']);
    expect(cmp.graph().nodes).toHaveLength(AUTO_NODES);
    // The nodes of the first page keep their identity.
    expect(cmp.graph().nodes[0]).toBe(first.nodes[0]);
    expect(cmp.graph().nodes[59]).toBe(first.nodes[59]);
    expect(cmp.canvasNodes()).toHaveLength(300);
    expect(cmp.growing()).toBe(false);

    screen.getByTestId('gr-more').click();
    await settle();
    expect(calls.map((c) => c.cursor)).toEqual([null, '60', '120', '180', '240', '300']);
    expect(cmp.limit()).toBe(2 * AUTO_NODES);
    expect(cmp.graph().nodes).toHaveLength(310);
    expect(cmp.graph().nodes[0]).toBe(first.nodes[0]);
    expect(screen.queryByTestId('gr-more')).toBeNull();
    cmp.loadMore();
    expect(calls).toHaveLength(6);
  });

  it('shows that a later page loads, and keeps the graph when that page fails', async () => {
    const second = new Subject<GraphPage>();
    const { calls, cmp, settle, el } = await start('/graph', [() => of(cards(0, 60, '60')), () => second], undefined, true);
    expect(cmp.growing()).toBe(true);
    expect(el.querySelector('.gr__growing')).toHaveTextContent('Weitere Elemente werden geladen …');
    expect(el.querySelector('.gr__growing')).toHaveAttribute('role', 'status');
    expect(screen.queryByTestId('gr-more')).toBeNull();
    cmp.loadMore();
    expect(calls).toHaveLength(2);

    second.error(new Error('offline'));
    await settle();
    expect(cmp.growing()).toBe(false);
    expect(cmp.error()).toBe(false);
    expect(cmp.graph().nodes).toHaveLength(60);
    expect(loadErrorToast()).toBeNull();
    screen.getByTestId('gr-more').click();
    await settle();
    expect(last(calls).cursor).toBe('60');
    expect(cmp.graph().nodes).toHaveLength(62);
  });

  it('shows a skeleton while the first page loads', async () => {
    const { cmp, el, calls } = await start('/graph', [() => NEVER]);
    expect(cmp.loading()).toBe(true);
    expect(el.querySelector('.gr__body')).toHaveAttribute('aria-busy', 'true');
    expect(el.querySelector('app-skeleton')).not.toBeNull();
    expect(el.querySelector('app-graph-canvas')).toBeNull();
    cmp.loadMore();
    expect(calls).toHaveLength(1);
  });

  it('shows the load error with a retry', async () => {
    const { cmp, calls, settle, el } = await start('/graph', [() => throwError(() => new Error('offline'))]);
    expect(cmp.error()).toBe(true);
    expect(loadErrorToast()).toBe('Der Graph konnte nicht geladen werden.');
    retryLoadError();
    await settle();
    expect(calls).toHaveLength(2);
    expect(cmp.error()).toBe(false);
    expect(el.querySelector('app-graph-canvas')).not.toBeNull();
  });

  it('shows an empty state, another one with filters', async () => {
    const plain = await start('/graph', [() => of(page([]))]);
    expect(screen.getByText('Noch keine Verknüpfungen')).toBeInTheDocument();
    expect(screen.getByText('Sobald Elemente miteinander verknüpft sind, erscheinen sie hier.')).toBeInTheDocument();
    expect(plain.el.querySelector('app-graph-canvas')).toBeNull();
    expect(plain.cmp.empty()).toBe(true);
    expect(plain.cmp.filtered()).toBe(false);
  });

  it('shows the empty state of the filters', async () => {
    await start('/graph?single=1', [() => of(page([]))]);
    expect(screen.getByText('Kein Element passt zu den Filtern')).toBeInTheDocument();
    expect(screen.queryByText('Noch keine Verknüpfungen')).toBeNull();
  });

  /** § F/collaboration/graph/001425: the filters are in the query of the URL, the server applies them. */
  it('reads the filters from the URL and resets them', async () => {
    const { calls, cmp, settle, router } = await start(
      '/graph?kinds=meeting,todo&from=2026-01-01&to=2026-12-31&gremium=g1&rel=links&q=Haushalt&single=1&noaccess=1',
    );
    expect(calls[0].filters).toEqual({
      kinds: ['meeting', 'todo'],
      from: '2026-01-01',
      to: '2026-12-31',
      gremiumId: 'g1',
      relations: 'links',
      q: 'Haushalt',
      single: true,
      noAccess: true,
    });
    expect(cmp.searchText()).toBe('Haushalt');
    expect(cmp.gremiumText()).toBe('Gremium: StuPa');
    expect(cmp.relationsText()).toBe('Beziehungen: Nur Verknüpfungen');
    expect(screen.getByTestId('gr-single')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('gr-no-access')).toHaveAttribute('aria-pressed', 'true');

    screen.getByTestId('gr-reset').click();
    await settle();
    expect(last(calls).filters).toEqual(FRESH);
    expect(cmp.searchText()).toBe('');
    expect(router.url).toBe('/graph');
    expect(screen.queryByTestId('gr-reset')).toBeNull();
  });

  it('writes each filter to the URL and asks the server again', async () => {
    const { calls, cmp, settle, router } = await start();
    cmp.setKinds(['todo', 'bogus', 'meeting']);
    await settle();
    expect(last(calls).filters.kinds).toEqual(['meeting', 'todo']);
    expect(router.parseUrl(router.url).queryParams).toEqual({ kinds: 'meeting,todo' });

    cmp.setPeriod({ from: '2026-01-01', to: '2026-06-30' });
    cmp.setGremium('g1');
    cmp.setRelations('builtin');
    await settle();
    expect(last(calls).filters).toEqual({
      ...FRESH,
      kinds: ['meeting', 'todo'],
      from: '2026-01-01',
      to: '2026-06-30',
      gremiumId: 'g1',
      relations: 'builtin',
    });
    expect(router.parseUrl(router.url).queryParams).toEqual({
      kinds: 'meeting,todo',
      from: '2026-01-01',
      to: '2026-06-30',
      gremium: 'g1',
      rel: 'builtin',
    });

    cmp.setRelations('unknown');
    await settle();
    expect(last(calls).filters.relations).toBe('all');
    expect(cmp.relationsText()).toBe('Beziehungen');

    screen.getByTestId('gr-single').click();
    await settle();
    expect(last(calls).filters.single).toBe(true);
    screen.getByTestId('gr-no-access').click();
    await settle();
    expect(last(calls).filters.noAccess).toBe(true);
    expect(router.parseUrl(router.url).queryParams['noaccess']).toBe('1');

    // A value that changes nothing does not load again.
    const count = calls.length;
    cmp.setGremium('g1');
    await settle();
    expect(calls).toHaveLength(count);
  });

  it('adopts the filters when the URL changes', async () => {
    const { calls, cmp, harness, settle } = await start();
    await harness.navigateByUrl('/graph?rel=links&q=Fest&view=list');
    await settle();
    expect(cmp.filters().relations).toBe('links');
    expect(cmp.searchText()).toBe('Fest');
    expect(last(calls).filters).toEqual({ ...FRESH, relations: 'links', q: 'Fest' });
  });

  it('searches after a pause, with the last text only', async () => {
    const { calls, cmp, settle } = await start();
    cmp.setSearch('Haus');
    cmp.setSearch('Haushalt');
    expect(cmp.searchText()).toBe('Haushalt');
    expect(calls).toHaveLength(1);
    await new Promise((done) => setTimeout(done, SEARCH_PAUSE + 60));
    await settle();
    expect(calls).toHaveLength(2);
    expect(last(calls).filters.q).toBe('Haushalt');

    // A reset and the end of the page drop a search that waits.
    cmp.setSearch('Fest');
    cmp.reset();
    await new Promise((done) => setTimeout(done, SEARCH_PAUSE + 60));
    await settle();
    expect(last(calls).filters).toEqual(FRESH);
    const count = calls.length;
    cmp.setSearch('Ende');
    TestBed.resetTestingModule();
    await new Promise((done) => setTimeout(done, SEARCH_PAUSE + 60));
    expect(calls).toHaveLength(count);
  });

  /** § F/collaboration/graph/001429: a press chooses a node: the panel, the dimmed nodes and "Öffnen". */
  it('shows the panel of the pressed node with "Öffnen" and dims the other nodes', async () => {
    const { settle, cmp, el } = await start('/graph', [() => of(FULL)]);
    expect(el.querySelector('.gr__panel')).toBeNull();
    screen.getByRole('button', { name: 'Sitzung: Sondersitzung' }).click();
    await settle();

    const panel = within(el.querySelector('.gr__panel') as HTMLElement);
    expect(panel.getByRole('heading', { level: 2, name: 'Sondersitzung' })).toBeInTheDocument();
    expect(panel.getByText('Sitzung')).toBeInTheDocument();
    expect(panel.getByText('03.11.2026')).toBeInTheDocument();
    expect(panel.getByRole('link', { name: 'Öffnen' })).toHaveAttribute('href', '/meetings/1');
    // The panel has no list of the neighbours: the drawing shows them.
    expect(panel.queryByRole('heading', { level: 3 })).toBeNull();
    expect(panel.getAllByRole('button')).toHaveLength(1);
    // The node that is no neighbour dims.
    expect(screen.getByRole('button', { name: 'Abstimmung: Ohne Titel' })).toHaveClass('gc__node--dim');
    expect(screen.getByRole('button', { name: 'To-Do: Flyer drucken' })).not.toHaveClass('gc__node--dim');

    // A press on a neighbour in the drawing chooses that node.
    screen.getByRole('button', { name: 'TOP: TOP 1: Haushalt' }).click();
    await settle();
    expect(cmp.selected()).toBe('agenda_item:2');
    const top = within(el.querySelector('.gr__panel') as HTMLElement);
    expect(top.getByRole('heading', { level: 2, name: 'TOP 1: Haushalt' })).toBeInTheDocument();
    expect(top.getByRole('link', { name: 'Öffnen' })).toHaveAttribute('href', '/meetings/1?top=2');

    top.getByRole('button', { name: 'Auswahl aufheben' }).click();
    await settle();
    expect(el.querySelector('.gr__panel')).toBeNull();
    expect(el.querySelector('.gc__node--dim')).toBeNull();
  });

  it('offers no "Öffnen" for an element without a page, and no panel for a node that left', async () => {
    const { settle, cmp, el } = await start('/graph', [() => of(FULL)]);
    cmp.choose('application:4');
    await settle();
    const granted = within(el.querySelector('.gr__panel') as HTMLElement);
    expect(granted.getByRole('heading', { level: 2, name: 'Antrag Sommerfest' })).toBeInTheDocument();
    expect(granted.queryByRole('link')).toBeNull();
    expect(granted.getByText('Nur über eine verknüpfte Karte lesbar')).toBeInTheDocument();

    cmp.choose('invoice:5');
    await settle();
    const hidden = within(el.querySelector('.gr__panel') as HTMLElement);
    expect(hidden.getByRole('heading', { level: 2, name: 'Rechnung (kein Zugriff)' })).toBeInTheDocument();
    expect(hidden.queryByRole('link')).toBeNull();
    expect(hidden.queryByText('Nur über eine verknüpfte Karte lesbar')).toBeNull();
    expect(el.querySelector('.gr__panel .gr__mark--muted')).not.toBeNull();

    cmp.choose('todo:99');
    await settle();
    expect(cmp.chosen()).toBeNull();
    expect(el.querySelector('.gr__panel')).toBeNull();

    // A new build-up ends the choice.
    cmp.choose('meeting:1');
    cmp.toggleSingle();
    await settle();
    expect(cmp.selected()).toBeNull();
  });

  /** § F/collaboration/graph/001429: on a phone the chosen element shows in a sheet. */
  it('shows the chosen element in a sheet on a phone', async () => {
    const restore = matchMediaQueries(MEDIA.phone);
    try {
      const { settle, cmp, el } = await start('/graph', [() => of(FULL)]);
      screen.getByRole('button', { name: 'Sitzung: Sondersitzung' }).click();
      await settle();
      expect(el.querySelector('.gr__panel')).toBeNull();
      const sheet = within(screen.getByRole('dialog', { name: 'Sondersitzung' }));
      expect(sheet.getByText('03.11.2026')).toBeInTheDocument();
      expect(sheet.getByRole('link', { name: 'Öffnen' })).toHaveAttribute('href', '/meetings/1');
      // The sheet keeps the element while it goes.
      cmp.choose(null);
      await settle();
      expect(cmp.chosen()).toBeNull();
      expect(cmp.sheetRow()?.title).toBe('Sondersitzung');
    } finally {
      restore();
    }
  });

  it('offers the Gremien of the person in the filter, and none when they do not load', async () => {
    const ok = await start();
    expect(ok.cmp.gremiumOptions()).toEqual([
      { value: '', label: 'Alle Gremien' },
      { value: 'g1', label: 'StuPa' },
    ]);
    expect(ok.cmp.gremiumText()).toBe('Gremium');
    expect(ok.cmp.relationOptions().map((o) => o.label)).toEqual([
      'Alle Beziehungen',
      'Nur Verknüpfungen',
      'Nur feste Beziehungen',
    ]);
    TestBed.resetTestingModule();
    const failed = await start('/graph', [], throwError(() => new Error('offline')));
    expect(failed.cmp.gremiumOptions()).toEqual([{ value: '', label: 'Alle Gremien' }]);
  });
});
