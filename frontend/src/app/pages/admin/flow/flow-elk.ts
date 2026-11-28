/**
 * Automatic layout of one drill-down level of the flow canvas with ELK (elkjs).
 *
 * The editor does not keep hand-made positions: every level is laid out from its
 * structure each time it changes. ELK "layered" orders the boxes left to right along
 * the transitions and routes each line in right angles through channels between the
 * layers, so lines do not cross boxes and parallel lines keep a fixed distance.
 *
 * - Every connector dot is a port at its fixed place on the east side of its box. Lines
 *   start at their dot and end in the middle of the west side of the target box.
 * - Transitions with the same source and target join into one line after their dots (`mergeEdges`),
 *   and the bundle carries one label: the name of a single transition, both names for two, else the
 *   count.
 * - Edge labels get their own place in the layer between source and target, so a label
 *   never covers a box or another label.
 * - Proxies (the ends outside an open group) sit in the first layer (sources) or in the
 *   last layer (targets).
 * - The flow runs from the initial state to the terminal states (spec 003134): the boxes go to
 *   ELK in the order of their distance from the initial state along the transitions
 *   (`flowOrder`), the initial state is in the first layer, and a terminal state without an
 *   outgoing line is in the last layer. The keys of the states do not change the layout.
 *
 * The module is pure except for `warmLayouter` and `layoutLevel`. They start a web worker that
 * runs elkjs (`flow-elk.worker.ts`), so a layout never blocks the page and the library is in
 * its own chunk that only the flow editor loads.
 */
import { InjectionToken } from '@angular/core';
import type { ElkExtendedEdge, ElkNode, ElkPoint } from 'elkjs/lib/elk-api';
import type { Point } from './flow-editor.models';

/** A port on the east side of a box: one connector dot. */
export interface LayoutPort {
  readonly id: string;
  /** Y of the dot, from the top of the box. */
  readonly y: number;
  /** The text beside the dot (a guard or a branch); empty for none. */
  readonly label: string;
}

/** One box of the level: a state, a group box or a proxy. */
export interface LayoutBox {
  readonly id: string;
  readonly w: number;
  readonly h: number;
  readonly ports: readonly LayoutPort[];
  /** A proxy of an outside source goes first, of an outside target last. */
  readonly layer?: 'first' | 'last';
  /** The initial state starts the flow, a terminal state ends it (spec 003134). */
  readonly role?: 'start' | 'end';
}

/** One visible transition: from a port of a box to the west side of a box. */
export interface LayoutLink {
  readonly index: number;
  readonly src: string;
  readonly port: string;
  readonly dst: string;
  readonly label: string;
  readonly automatic: boolean;
}

/** The input of one level. Two equal inputs give the same layout. */
export interface LayoutInput {
  readonly boxes: readonly LayoutBox[];
  readonly links: readonly LayoutLink[];
}

/** The line of one transition. A bundle has the label on its first member only. */
export interface LayoutRoute {
  readonly d: string;
  /** Centre of the label box, or null when the line has no label. */
  readonly label: { readonly x: number; readonly y: number; readonly text: string } | null;
  /** The transitions of the bundle this line draws (the same for every member). */
  readonly bundle: readonly number[];
}

export interface LevelLayout {
  /** Top-left corner per box id. */
  readonly pos: ReadonlyMap<string, Point>;
  /** Line per transition index. */
  readonly routes: ReadonlyMap<number, LayoutRoute>;
}

/** Fonts of the canvas texts (flow-editor.component.scss), for the text widths. */
export const NODE_FONT = '600 13.5px "IBM Plex Sans", sans-serif';
const EDGE_FONT = '500 11.5px "IBM Plex Sans", sans-serif';
export const DOT_FONT = '400 10.5px "IBM Plex Sans", sans-serif';
/** Average glyph width per px of font size, where no canvas can measure (jsdom). */
const AVG_GLYPH = 0.56;
/** The bolt in front of the label of an automatic transition. */
const BOLT_W = 14;

let measure: OffscreenCanvasRenderingContext2D | null | undefined;

/** Width of a text in px. Without an offscreen canvas (jsdom) it is an estimate. */
export function textWidth(text: string, font: string): number {
  if (!text) return 0;
  measure ??= typeof OffscreenCanvas === 'undefined' ? null : new OffscreenCanvas(1, 1).getContext('2d');
  if (measure) {
    measure.font = font;
    return Math.ceil(measure.measureText(text).width);
  }
  const size = Number(/([\d.]+)px/.exec(font)?.[1] ?? 12);
  return Math.ceil(text.length * size * AVG_GLYPH);
}

/** Key of a bundle: same source box and same target, whatever the dot. */
function bundleKey(l: LayoutLink): string {
  return `${l.src}\u0000${l.dst}`;
}

/** The transitions of each bundle, in the order of their first member. */
export function bundles(links: readonly LayoutLink[]): readonly (readonly LayoutLink[])[] {
  const keys = [...new Set(links.map(bundleKey))];
  return keys.map((k) => links.filter((l) => bundleKey(l) === k));
}

/**
 * The label of a bundle: the name of a single transition, both names of two named
 * ones, else the count (`many`).
 */
export function bundleLabel(b: readonly LayoutLink[], many: (n: number) => string): string {
  if (b.length === 1) return b[0].label;
  if (b.length === 2 && b[0].label && b[1].label) return `${b[0].label} · ${b[1].label}`;
  return many(b.length);
}

/** Orthogonal path through the points, with rounded corners of radius `r`. */
export function roundedPath(points: readonly Point[], r = 10): string {
  const p = points.filter((q, i) => i === 0 || q.x !== points[i - 1].x || q.y !== points[i - 1].y);
  if (p.length === 0) return '';
  const corner = (a: Point, b: Point, c: Point): string => {
    const l1 = Math.hypot(b.x - a.x, b.y - a.y);
    const l2 = Math.hypot(c.x - b.x, c.y - b.y);
    const rr = Math.min(r, l1 / 2, l2 / 2);
    const sx = b.x - ((b.x - a.x) / l1) * rr;
    const sy = b.y - ((b.y - a.y) / l1) * rr;
    const ex = b.x + ((c.x - b.x) / l2) * rr;
    const ey = b.y + ((c.y - b.y) / l2) * rr;
    return ` L ${sx} ${sy} Q ${b.x} ${b.y}, ${ex} ${ey}`;
  };
  const corners = p.slice(1, -1).map((b, j) => corner(p[j], b, p[j + 2]));
  const d = `M ${p[0].x} ${p[0].y}${corners.join('')}`;
  const last = p[p.length - 1];
  return p.length > 1 ? `${d} L ${last.x} ${last.y}` : d;
}

/**
 * The ELK options of the whole graph. The order of the states and transitions in the flow
 * is the tie breaker, so an edit that does not change the structure does not move the
 * boxes. The top padding leaves room above a box for the kind of a vote state
 * ("Abstimmung").
 */
const ROOT_OPTIONS: Record<string, string> = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.edgeRouting': 'ORTHOGONAL',
  'elk.layered.spacing.nodeNodeBetweenLayers': '32',
  'elk.layered.spacing.edgeNodeBetweenLayers': '16',
  'elk.spacing.nodeNode': '40',
  'elk.spacing.edgeEdge': '12',
  'elk.layered.spacing.edgeEdgeBetweenLayers': '10',
  'elk.spacing.edgeLabel': '4',
  'elk.layered.mergeEdges': 'true',
  'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
  'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
  'elk.layered.cycleBreaking.strategy': 'MODEL_ORDER',
  'elk.edgeLabels.inline': 'false',
  'elk.padding': '[top=50,left=40,bottom=40,right=40]',
};

/**
 * The boxes and links in the order of the flow: a breadth-first walk from the starts (the
 * proxies of outside sources and the initial state) along the links, then the boxes that the
 * walk does not reach in their own order, and the ends last. The links follow the order of their
 * source and then of their target. ELK breaks cycles and ties by this order.
 */
export function flowOrder(input: LayoutInput): LayoutInput {
  const ends = new Set(input.boxes.filter((b) => b.role === 'end' || b.layer === 'last').map((b) => b.id));
  const starts = input.boxes.filter((b) => b.layer === 'first' || b.role === 'start').map((b) => b.id);
  const next = new Map<string, readonly string[]>(
    input.boxes.map((b) => [b.id, input.links.filter((l) => l.src === b.id).map((l) => l.dst)]),
  );
  const walk = (queue: readonly string[], seen: ReadonlySet<string>): readonly string[] => {
    if (queue.length === 0) return [];
    const [head, ...rest] = queue;
    const fresh = (next.get(head) ?? []).filter((d) => !seen.has(d) && !rest.includes(d));
    return [head, ...walk([...rest, ...fresh], new Set([...seen, ...fresh]))];
  };
  const reached = walk(starts, new Set(starts));
  const seq = [...reached, ...input.boxes.map((b) => b.id).filter((id) => !reached.includes(id))];
  const ordered = [...seq.filter((id) => !ends.has(id)), ...seq.filter((id) => ends.has(id))];
  const rank = new Map(ordered.map((id, i) => [id, i]));
  const at = (id: string): number => rank.get(id) ?? Number.MAX_SAFE_INTEGER;
  return {
    boxes: [...input.boxes].sort((a, b) => at(a.id) - at(b.id)),
    links: [...input.links].sort((a, b) => at(a.src) - at(b.src) || at(a.dst) - at(b.dst) || a.index - b.index),
  };
}

/** The layer of a box: proxies by their side, the initial state first, a terminal state last. */
function layerOf(b: LayoutBox, links: readonly LayoutLink[]): 'FIRST' | 'LAST' | null {
  if (b.layer) return b.layer === 'first' ? 'FIRST' : 'LAST';
  if (b.role === 'start') return 'FIRST';
  if (b.role === 'end' && !links.some((l) => l.src === b.id)) return 'LAST';
  return null;
}

/** The ELK graph of a level. Exported for the tests. */
export function elkGraph(raw: LayoutInput, many: (n: number) => string): ElkNode {
  const input = flowOrder(raw);
  const layered = (b: LayoutBox): Record<string, string> => {
    const layer = layerOf(b, input.links);
    return layer ? { 'elk.layered.layering.layerConstraint': layer } : {};
  };
  const children: ElkNode[] = input.boxes.map((b) => ({
    id: b.id,
    width: b.w,
    height: b.h,
    layoutOptions: {
      'elk.portConstraints': 'FIXED_POS',
      'elk.portLabels.placement': 'OUTSIDE',
      'elk.nodeSize.constraints': 'PORT_LABELS',
      ...layered(b),
    },
    ports: [
      { id: `${b.id}::in`, x: -1, y: b.h / 2 - 1, width: 2, height: 2, layoutOptions: { 'elk.port.side': 'WEST' } },
      ...b.ports.map((p) => ({
        id: `${b.id}::${p.id}`,
        x: b.w - 1,
        y: p.y - 1,
        width: 2,
        height: 2,
        layoutOptions: { 'elk.port.side': 'EAST' },
        labels: p.label ? [{ text: p.label, width: textWidth(p.label, DOT_FONT) + 14, height: 14 }] : [],
      })),
    ],
  }));
  const ports = new Set(children.flatMap((c) => (c.ports ?? []).map((p) => p.id)));
  const source = (l: LayoutLink): string => (ports.has(`${l.src}::${l.port}`) ? `${l.src}::${l.port}` : l.src);
  const edges: ElkExtendedEdge[] = bundles(input.links).flatMap((b) => {
    const text = bundleLabel(b, many);
    const width = textWidth(text, EDGE_FONT) + (b.some((l) => l.automatic) ? BOLT_W : 0) + 10;
    return b.map((l, j) => ({
      id: `t${l.index}`,
      sources: [source(l)],
      targets: [`${l.dst}::in`],
      labels:
        j === 0 && (text || l.automatic)
          ? [{ text, width, height: 16, layoutOptions: { 'elk.edgeLabels.placement': 'CENTER' } }]
          : [],
    }));
  });
  return { id: 'root', layoutOptions: ROOT_OPTIONS, children, edges };
}

/** Read the positions and lines out of a laid-out ELK graph. Exported for the tests. */
export function readLayout(input: LayoutInput, out: ElkNode, many: (n: number) => string): LevelLayout {
  const pos = new Map(
    (out.children ?? []).map((c) => [c.id, { x: Math.round(c.x ?? 0), y: Math.round(c.y ?? 0) }]),
  );
  const byId = new Map((out.edges ?? []).map((e) => [e.id, e]));
  const routeOf = (
    b: readonly LayoutLink[],
    members: readonly number[],
    l: LayoutLink,
    j: number,
  ): readonly (readonly [number, LayoutRoute])[] => {
    const e = byId.get(`t${l.index}`);
    const s = e?.sections?.[0];
    if (!s) return [];
    const pts: readonly ElkPoint[] = [s.startPoint, ...(s.bendPoints ?? []), s.endPoint];
    const lab = j === 0 ? e.labels?.[0] : undefined;
    const label =
      lab && lab.x !== undefined && lab.y !== undefined
        ? {
            x: lab.x + (lab.width ?? 0) / 2,
            y: lab.y + (lab.height ?? 0) / 2,
            text: bundleLabel(b, many),
          }
        : null;
    return [[l.index, { d: roundedPath(pts), label, bundle: members }]];
  };
  const routes = new Map(
    bundles(input.links).flatMap((b) => {
      const members = b.map((l) => l.index);
      return b.flatMap((l, j) => routeOf(b, members, l, j));
    }),
  );
  return { pos, routes };
}

/** Lays out one ELK graph. */
type ElkEngine = (graph: ElkNode) => Promise<ElkNode>;

let engine: Promise<ElkEngine> | null = null;

/** The engine on a web worker: `elk-api` talks to the ELK worker script (`flow-elk.worker.ts`). */
async function workerEngine(): Promise<ElkEngine> {
  const [api, host] = await Promise.all([import('elkjs/lib/elk-api.js'), import('./flow-elk-worker')]);
  const elk = new api.default({ workerFactory: () => host.spawnElkWorker() });
  return (graph) => elk.layout(graph);
}

/** The engine on the main thread, where no web worker exists (jsdom). */
async function threadEngine(): Promise<ElkEngine> {
  const m = await import('elkjs/lib/elk.bundled.js');
  const elk = new m.default();
  return (graph) => elk.layout(graph);
}

/**
 * Start the layout engine: the web worker of `flow-elk.worker.ts` (spec 003135), or ELK on the
 * main thread where no worker exists. The flow editor calls it before it reads the flow, so the
 * two loads run at the same time (spec 003136). A second call does nothing.
 */
export function warmLayouter(): void {
  engine ??=
    typeof Worker === 'undefined'
      ? threadEngine()
      : workerEngine();
}

/** Lay out one level. Starts the engine on the first call. */
export async function layoutLevel(input: LayoutInput, many: (n: number) => string): Promise<LevelLayout> {
  warmLayouter();
  const run = await (engine as Promise<ElkEngine>);
  const out = await run(elkGraph(input, many));
  return readLayout(input, out, many);
}

/** Lays out one level; `layoutLevel` by default. */
export type LevelLayouter = (input: LayoutInput, many: (n: number) => string) => Promise<LevelLayout>;

/**
 * The layouter of the flow editor. A test can provide null: the boxes then stay at the
 * stored positions and the lines stay plain curves.
 */
export const FLOW_LAYOUTER = new InjectionToken<LevelLayouter | null>('FLOW_LAYOUTER', {
  providedIn: 'root',
  factory: () => layoutLevel,
});
