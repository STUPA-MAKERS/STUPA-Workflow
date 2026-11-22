/**
 * The layout of the graph: a small force simulation as pure functions (spec 001426).
 *
 * Every node pushes every other node away, a line pulls its two nodes to a fixed length,
 * and a weak pull holds the whole drawing around the origin. `place` puts a new node next
 * to a neighbour that already has a place, so the node appears where it belongs and the
 * nodes that already show keep their place. `step` moves every node once; `alpha` scales
 * the forces and falls from 1 to 0 while the layout settles.
 */

/** A node of the layout: its place and its speed. */
export interface Body {
  readonly id: string;
  readonly x: number;
  readonly y: number;
  readonly vx: number;
  readonly vy: number;
  /** True for a node that the person put somewhere (spec 001433): no force moves it. */
  readonly fixed?: boolean;
}

/** A line of the layout between two node ids. */
export interface Spring {
  readonly a: string;
  readonly b: string;
}

/** The length that a line pulls its nodes to, in px. */
export const LINK_LENGTH = 70;
/** The strength of the push between two nodes. */
const REPULSION = 11000;
/** The strength of a line. */
const STIFFNESS = 0.14;
/** The pull to the origin. */
const GRAVITY = 0.01;
/** The part of the speed that a node keeps per step. */
const DAMPING = 0.78;
/** The least distance of the push, so two nodes at one place do not fly apart. */
const MIN_DISTANCE = 12;
/** The most that a node moves per step, in px. */
const MAX_SPEED = 42;

/** `alpha` at the start of a run, after new nodes arrive. */
export const ALPHA_START = 1;
/** The factor of `alpha` per step. */
export const ALPHA_DECAY = 0.975;
/** Below this `alpha` the layout rests. */
export const ALPHA_MIN = 0.02;
/** The steps from {@link ALPHA_START} to rest. */
export const SETTLE_STEPS = Math.ceil(Math.log(ALPHA_MIN / ALPHA_START) / Math.log(ALPHA_DECAY));

/** A number from 0 to 1 that depends only on the text and the salt. */
export function hashUnit(text: string, salt = 0): number {
  const hash = Array.from(text).reduce((h, ch) => Math.imul(h ^ ch.charCodeAt(0), 16777619), (2166136261 + salt) | 0);
  return ((hash >>> 0) % 10000) / 10000;
}

function clamp(value: number, limit: number): number {
  return Math.max(-limit, Math.min(limit, value));
}

/** The ids that each node connects to. Build it once per change of the lines, not per step. */
export type Adjacency = ReadonlyMap<string, readonly string[]>;

export function adjacency(springs: readonly Spring[]): Adjacency {
  const pairs = springs.flatMap((s) => [[s.a, s.b] as const, [s.b, s.a] as const]);
  const ids = Array.from(new Set(pairs.map(([own]) => own)));
  return new Map(ids.map((id) => [id, pairs.filter(([own]) => own === id).map(([, other]) => other)] as const));
}

/**
 * Add the bodies of `ids` that have none yet. A new node starts beside its first neighbour
 * that has a place, else on a ring around the origin that grows with the drawing.
 */
export function place(bodies: readonly Body[], ids: readonly string[], near: Adjacency): readonly Body[] {
  return ids.reduce<readonly Body[]>((placed, id) => {
    if (placed.some((b) => b.id === id)) return placed;
    const anchor = (near.get(id) ?? []).map((n) => placed.find((b) => b.id === n)).find((b) => b !== undefined);
    const angle = hashUnit(id) * 2 * Math.PI;
    const reach = anchor ? LINK_LENGTH * (0.5 + hashUnit(id, 1) * 0.4) : LINK_LENGTH * (1 + Math.sqrt(placed.length));
    return [
      ...placed,
      {
        id,
        x: (anchor?.x ?? 0) + Math.cos(angle) * reach,
        y: (anchor?.y ?? 0) + Math.sin(angle) * reach,
        vx: 0,
        vy: 0,
      },
    ];
  }, bodies);
}

/** The pause before the next node joins, per waiting node, in ms (spec 001426). */
export const JOIN_BUDGET = 3600;
/** The shortest pause between two nodes, in ms. */
export const JOIN_MIN = 30;
/** The longest pause between two nodes, in ms. */
export const JOIN_MAX = 120;

/** The pause before the next node joins: shorter for a longer queue (spec 001426). */
export function pauseFor(waiting: number): number {
  return Math.min(JOIN_MAX, Math.max(JOIN_MIN, JOIN_BUDGET / Math.max(waiting, 1)));
}

/**
 * The node that joins the drawing next (spec 001426): the first waiting node with a
 * neighbour that shows, else the first waiting node; null when none waits.
 */
export function joinNext(queue: readonly string[], shown: ReadonlySet<string>, near: Adjacency): string | null {
  return queue.find((id) => (near.get(id) ?? []).some((n) => shown.has(n))) ?? queue[0] ?? null;
}

/** Keep only the bodies of `ids`. */
export function keep(bodies: readonly Body[], ids: ReadonlySet<string>): readonly Body[] {
  return bodies.filter((b) => ids.has(b.id));
}

interface Force {
  readonly x: number;
  readonly y: number;
}

/** The push of every other node on `own`. */
function push(own: Body, bodies: readonly Body[]): Force {
  return bodies.reduce<Force>(
    (sum, other) => {
      if (other.id === own.id) return sum;
      const dx = own.x - other.x || hashUnit(own.id + other.id) - 0.5;
      const dy = own.y - other.y || hashUnit(other.id + own.id) - 0.5;
      const distance = Math.max(MIN_DISTANCE, Math.hypot(dx, dy));
      const strength = REPULSION / (distance * distance * distance);
      return { x: sum.x + dx * strength, y: sum.y + dy * strength };
    },
    { x: 0, y: 0 },
  );
}

/** The pull of the lines of `own` to their length. */
function pull(own: Body, others: readonly Body[]): Force {
  return others.reduce<Force>(
    (sum, other) => {
      const dx = other.x - own.x;
      const dy = other.y - own.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const strength = ((distance - LINK_LENGTH) * STIFFNESS) / distance;
      return { x: sum.x + dx * strength, y: sum.y + dy * strength };
    },
    { x: 0, y: 0 },
  );
}

/** Move every node once. */
export function step(bodies: readonly Body[], near: Adjacency, alpha: number): readonly Body[] {
  const byId = new Map(bodies.map((b) => [b.id, b] as const));
  return bodies.map((own) => {
    if (own.fixed) return own;
    const linked = (near.get(own.id) ?? []).flatMap((id) => {
      const other = byId.get(id);
      return other ? [other] : [];
    });
    const away = push(own, bodies);
    const toward = pull(own, linked);
    const vx = clamp((own.vx + (away.x + toward.x - own.x * GRAVITY) * alpha) * DAMPING, MAX_SPEED);
    const vy = clamp((own.vy + (away.y + toward.y - own.y * GRAVITY) * alpha) * DAMPING, MAX_SPEED);
    return { id: own.id, x: own.x + vx, y: own.y + vy, vx, vy };
  });
}

/** Put the node `id` at a place and hold it there; the other nodes stay (spec 001433). */
export function hold(bodies: readonly Body[], id: string, x: number, y: number): readonly Body[] {
  return bodies.map((b) => (b.id === id ? { id, x, y, vx: 0, vy: 0, fixed: true } : b));
}

/** Run the layout from `alpha` to rest in one go, for a drawing that must not move (spec 001427). */
export function settle(bodies: readonly Body[], near: Adjacency, alpha: number = ALPHA_START): readonly Body[] {
  return alpha < ALPHA_MIN
    ? bodies.map((b) => ({ ...b, vx: 0, vy: 0 }))
    : settle(step(bodies, near, alpha), near, alpha * ALPHA_DECAY);
}

/** The box around the bodies, with `pad` px on each side; null without a body. */
export interface Box {
  readonly minX: number;
  readonly minY: number;
  readonly maxX: number;
  readonly maxY: number;
}

export function bounds(bodies: readonly Body[], pad = 0): Box | null {
  return bodies.length === 0
    ? null
    : {
        minX: Math.min(...bodies.map((b) => b.x)) - pad,
        minY: Math.min(...bodies.map((b) => b.y)) - pad,
        maxX: Math.max(...bodies.map((b) => b.x)) + pad,
        maxY: Math.max(...bodies.map((b) => b.y)) + pad,
      };
}

/** The pan and the zoom of the drawing. A point `p` of the layout shows at `p * zoom + pan`. */
export interface View {
  readonly x: number;
  readonly y: number;
  readonly zoom: number;
}

export const ZOOM_MIN = 0.15;
export const ZOOM_MAX = 2.5;

export function clampZoom(zoom: number): number {
  return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, zoom));
}

/** The view that shows the whole box in a frame of `width` x `height`, never larger than 1:1. */
export function fit(box: Box | null, width: number, height: number): View {
  if (!box || width <= 0 || height <= 0) return { x: width / 2, y: height / 2, zoom: 1 };
  const zoom = clampZoom(
    Math.min(1, width / Math.max(1, box.maxX - box.minX), height / Math.max(1, box.maxY - box.minY)),
  );
  return {
    x: width / 2 - ((box.minX + box.maxX) / 2) * zoom,
    y: height / 2 - ((box.minY + box.maxY) / 2) * zoom,
    zoom,
  };
}

/** Zoom by `factor` and keep the point `(px, py)` of the frame where it is. */
export function zoomAt(view: View, factor: number, px: number, py: number): View {
  const zoom = clampZoom(view.zoom * factor);
  const ratio = zoom / view.zoom;
  return { x: px - (px - view.x) * ratio, y: py - (py - view.y) * ratio, zoom };
}

export type Direction = 'up' | 'down' | 'left' | 'right';

/**
 * The nearest node from `from` in a direction, for the arrow keys (spec 001428). A node
 * counts when it lies in the quarter of the plane of that direction.
 */
export function nearestIn(bodies: readonly Body[], from: string, direction: Direction): string | null {
  const own = bodies.find((b) => b.id === from);
  if (!own) return bodies[0]?.id ?? null;
  const ahead = (dx: number, dy: number): boolean => {
    switch (direction) {
      case 'right':
        return dx > 0 && Math.abs(dy) <= dx;
      case 'left':
        return dx < 0 && Math.abs(dy) <= -dx;
      case 'down':
        return dy > 0 && Math.abs(dx) <= dy;
      case 'up':
        return dy < 0 && Math.abs(dx) <= -dy;
    }
  };
  return bodies
    .filter((b) => b.id !== from && ahead(b.x - own.x, b.y - own.y))
    .reduce<{ readonly id: string | null; readonly distance: number }>(
      (best, b) => {
        const distance = Math.hypot(b.x - own.x, b.y - own.y);
        return distance < best.distance ? { id: b.id, distance } : best;
      },
      { id: null, distance: Infinity },
    ).id;
}
