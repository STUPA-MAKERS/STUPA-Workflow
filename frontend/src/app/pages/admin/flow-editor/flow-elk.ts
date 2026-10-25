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
 * - Transitions with the same source and target join into one line after their dots
 *   (`mergeEdges`), and the bundle carries one label: the name of a single transition, both names for two,
 *   else the count.
 * - Edge labels get their own place in the layer between source and target, so a label
 *   never covers a box or another label.
 * - Proxies (the ends outside an open group) sit in the first layer (sources) or in the
 *   last layer (targets).
 *
 * The module is pure except for `layoutLevel`, which loads elkjs on first use, so the
 * library is in its own chunk and only the flow editor loads it.
 */
import { InjectionToken } from '@angular/core';
import type { ElkExtendedEdge, ElkNode, ElkPoint } from 'elkjs/lib/elk-api';
import type { Point } from './flow-editor.models';

/** A port on the east side of a box: one connector dot. */
export interface LayoutPort {
  id: string;
  /** Y of the dot, from the top of the box. */
  y: number;
  /** The text beside the dot (a guard or a branch); empty for none. */
  label: string;
}

/** One box of the level: a state, a group box or a proxy. */
export interface LayoutBox {
  id: string;
  w: number;
  h: number;
  ports: LayoutPort[];
  /** A proxy of an outside source goes first, of an outside target last. */
  layer?: 'first' | 'last';
}

/** One visible transition: from a port of a box to the west side of a box. */
export interface LayoutLink {
  index: number;
  src: string;
  port: string;
  dst: string;
  label: string;
  automatic: boolean;
}

/** The input of one level. Two equal inputs give the same layout. */
export interface LayoutInput {
  boxes: LayoutBox[];
  links: LayoutLink[];
}

/** The line of one transition. A bundle has the label on its first member only. */
export interface LayoutRoute {
  d: string;
  /** Centre of the label box, or null when the line has no label. */
  label: { x: number; y: number; text: string } | null;
  /** The transitions of the bundle this line draws (the same for every member). */
  bundle: number[];
}

export interface LevelLayout {
  /** Top-left corner per box id. */
  pos: Map<string, Point>;
  /** Line per transition index. */
  routes: Map<number, LayoutRoute>;
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
export function bundles(links: readonly LayoutLink[]): LayoutLink[][] {
  const by = new Map<string, LayoutLink[]>();
  for (const l of links) {
    const k = bundleKey(l);
    const list = by.get(k);
    if (list) list.push(l);
    else by.set(k, [l]);
  }
  return [...by.values()];
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
  let d = `M ${p[0].x} ${p[0].y}`;
  for (let i = 1; i < p.length - 1; i++) {
    const a = p[i - 1];
    const b = p[i];
    const c = p[i + 1];
    const l1 = Math.hypot(b.x - a.x, b.y - a.y);
    const l2 = Math.hypot(c.x - b.x, c.y - b.y);
    const rr = Math.min(r, l1 / 2, l2 / 2);
    const sx = b.x - ((b.x - a.x) / l1) * rr;
    const sy = b.y - ((b.y - a.y) / l1) * rr;
    const ex = b.x + ((c.x - b.x) / l2) * rr;
    const ey = b.y + ((c.y - b.y) / l2) * rr;
    d += ` L ${sx} ${sy} Q ${b.x} ${b.y}, ${ex} ${ey}`;
  }
  const last = p[p.length - 1];
  return p.length > 1 ? `${d} L ${last.x} ${last.y}` : d;
}

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
  // The order of the states and transitions in the flow is the tie breaker, so an edit
  // that does not change the structure does not move the boxes.
  'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
  'elk.layered.cycleBreaking.strategy': 'MODEL_ORDER',
  'elk.edgeLabels.inline': 'false',
  // Room above a box for the kind of a vote state ("Abstimmung").
  'elk.padding': '[top=50,left=40,bottom=40,right=40]',
};

/** The ELK graph of a level. Exported for the tests. */
export function elkGraph(input: LayoutInput, many: (n: number) => string): ElkNode {
  const children: ElkNode[] = input.boxes.map((b) => ({
    id: b.id,
    width: b.w,
    height: b.h,
    layoutOptions: {
      'elk.portConstraints': 'FIXED_POS',
      'elk.portLabels.placement': 'OUTSIDE',
      'elk.nodeSize.constraints': 'PORT_LABELS',
      ...(b.layer ? { 'elk.layered.layering.layerConstraint': b.layer === 'first' ? 'FIRST' : 'LAST' } : {}),
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
  const pos = new Map<string, Point>();
  for (const c of out.children ?? []) pos.set(c.id, { x: Math.round(c.x ?? 0), y: Math.round(c.y ?? 0) });
  const byId = new Map((out.edges ?? []).map((e) => [e.id, e]));
  const routes = new Map<number, LayoutRoute>();
  for (const b of bundles(input.links)) {
    const members = b.map((l) => l.index);
    b.forEach((l, j) => {
      const e = byId.get(`t${l.index}`);
      const s = e?.sections?.[0];
      if (!s) return;
      const pts: ElkPoint[] = [s.startPoint, ...(s.bendPoints ?? []), s.endPoint];
      const lab = j === 0 ? e.labels?.[0] : undefined;
      routes.set(l.index, {
        d: roundedPath(pts),
        label:
          lab && lab.x !== undefined && lab.y !== undefined
            ? { x: lab.x + (lab.width ?? 0) / 2, y: lab.y + (lab.height ?? 0) / 2, text: bundleLabel(b, many) }
            : null,
        bundle: members,
      });
    });
  }
  return { pos, routes };
}

type ElkLayouter = { layout(graph: ElkNode): Promise<ElkNode> };
let elk: Promise<ElkLayouter> | null = null;

/** Lay out one level. Loads elkjs on the first call. */
export async function layoutLevel(input: LayoutInput, many: (n: number) => string): Promise<LevelLayout> {
  elk ??= import('elkjs/lib/elk.bundled.js').then((m) => new m.default());
  const out = await (await elk).layout(elkGraph(input, many));
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
