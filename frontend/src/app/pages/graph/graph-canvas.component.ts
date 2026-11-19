import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import type { GraphKind } from '@core/api/graph.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent, type IconName, reducedMotion } from '@stupa-makers/ui-kit';
import {
  ALPHA_DECAY,
  ALPHA_MIN,
  ALPHA_START,
  type Adjacency,
  type Body,
  type Direction,
  type View,
  adjacency,
  bounds,
  fit,
  keep,
  nearestIn,
  place,
  settle,
  step,
  zoomAt,
} from './graph-layout';
import type { GraphLine } from './graph.util';

/** A node as the drawing shows it. */
export interface CanvasNode {
  readonly key: string;
  readonly kind: GraphKind;
  readonly icon: IconName;
  /** The text under the node. */
  readonly title: string;
  /** The accessible name: the kind and the title. */
  readonly name: string;
  /** An element that the person does not read (spec 001422). */
  readonly muted: boolean;
}

/** A line with the places of its two ends. */
export interface DrawnLine {
  readonly key: string;
  readonly x1: number;
  readonly y1: number;
  readonly x2: number;
  readonly y2: number;
  readonly builtin: boolean;
  readonly dim: boolean;
}

interface Point {
  readonly x: number;
  readonly y: number;
}

/** The room around the drawing when the view fits it, in px of the layout. */
export const FIT_PAD = 56;
/** From this zoom the titles show under the nodes (spec 001430). */
export const LABEL_ZOOM = 0.75;
/** A pointer that travels less is a press, not a drag, in px. */
export const PRESS_TRAVEL = 4;
/** The factor of one press on "+" or "−". */
export const ZOOM_STEP = 1.3;
/** The most nodes of one page that appear one after the other (spec 001426). */
const STAGGER = 60;
/** The room that a node keeps to the edge of the frame when the keyboard moves to it. */
const REVEAL_MARGIN = 48;

const ARROWS: Readonly<Record<string, Direction>> = {
  ArrowUp: 'up',
  ArrowDown: 'down',
  ArrowLeft: 'left',
  ArrowRight: 'right',
};

/**
 * The drawing of the graph (specs 001426-001430): the nodes as buttons over the lines.
 *
 * A small force layout places the nodes (`graph-layout.ts`). New nodes start beside a
 * neighbour and scale in; the nodes that already show keep their place apart from the
 * settling. With reduced motion the layout runs to its end before the paint and nothing
 * moves. The view follows the drawing until the person moves or zooms it: a drag on the
 * empty drawing moves it, the wheel, a pinch and the buttons zoom it. A press on a node
 * chooses it, a press on the empty drawing ends the choice. The view goes to the chosen
 * node when it is outside the frame or too small to read. Tab moves to one node, the arrow
 * keys to the nearest node in that direction.
 */
@Component({
  selector: 'app-graph-canvas',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, TranslatePipe],
  templateUrl: './graph-canvas.component.html',
  styleUrl: './graph-canvas.component.scss',
})
export class GraphCanvasComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly nodes = input.required<readonly CanvasNode[]>();
  readonly lines = input.required<readonly GraphLine[]>();
  /** The key of the chosen node. */
  readonly selected = input<string | null>(null);
  /** The label of the drawing for a screen reader (spec 001428). */
  readonly label = input.required<string>();
  /**
   * Where a chosen node goes when the view moves to it, as parts of the width and the
   * height of the frame. The page moves it away from the panel that covers a part.
   */
  readonly focusAt = input<{ readonly x: number; readonly y: number }>({ x: 0.5, y: 0.5 });
  /** A press on a node (its key) or on the empty drawing (null). */
  readonly chosen = output<string | null>();

  readonly bodies = signal<readonly Body[]>([]);
  readonly view = signal<View>({ x: 0, y: 0, zoom: 1 });
  readonly size = signal<{ readonly width: number; readonly height: number }>({ width: 0, height: 0 });
  /** The node that the keyboard is on. */
  readonly focused = signal<string | null>(null);
  /** True while nothing may move (spec 001427). */
  readonly still = signal(reducedMotion());
  /** The place of each new node in its page, for the order of the scale-in. */
  readonly order = signal<ReadonlyMap<string, number>>(new Map());

  readonly near = computed<Adjacency>(() => adjacency(this.lines()));
  readonly world = computed(() => {
    const v = this.view();
    return `translate(${v.x}px, ${v.y}px) scale(${v.zoom})`;
  });
  readonly labels = computed(() => this.view().zoom >= LABEL_ZOOM);

  private readonly places = computed(() => new Map(this.bodies().map((b) => [b.id, b] as const)));

  /** The chosen node and its neighbours; null without a choice. */
  readonly lit = computed<ReadonlySet<string> | null>(() => {
    const chosen = this.selected();
    return chosen === null ? null : new Set([chosen, ...(this.near().get(chosen) ?? [])]);
  });

  readonly drawn = computed<readonly DrawnLine[]>(() => {
    const places = this.places();
    const chosen = this.selected();
    return this.lines().flatMap((l) => {
      const a = places.get(l.a);
      const b = places.get(l.b);
      return a && b
        ? [
            {
              key: l.key,
              x1: a.x,
              y1: a.y,
              x2: b.x,
              y2: b.y,
              builtin: l.source === 'builtin',
              dim: chosen !== null && l.a !== chosen && l.b !== chosen,
            },
          ]
        : [];
    });
  });

  /** The one node that Tab reaches: the focused one, else the chosen one, else the first. */
  readonly tabStop = computed<string | null>(() => {
    const keys = this.nodes().map((n) => n.key);
    return [this.focused(), this.selected()].find((k) => k !== null && keys.includes(k)) ?? keys[0] ?? null;
  });

  private alpha = 0;
  private frame: number | null = null;
  /** True after the person moved or zoomed the view; then the view stops to follow. */
  private free = false;
  private pointers: ReadonlyMap<number, Point> = new Map();
  private travel = 0;

  constructor() {
    const observer = new ResizeObserver(() => this.measure());
    observer.observe(this.host.nativeElement);
    this.measure();

    effect(() => {
      const ids = this.nodes().map((n) => n.key);
      const near = this.near();
      untracked(() => this.arrange(ids, near));
    });
    effect(() => {
      const chosen = this.selected();
      untracked(() => (chosen === null ? undefined : this.reveal(chosen)));
    });

    inject(DestroyRef).onDestroy(() => {
      observer.disconnect();
      this.stop();
    });
  }

  at(key: string): string {
    const body = this.places().get(key);
    return `translate(${body?.x ?? 0}px, ${body?.y ?? 0}px)`;
  }

  isDim(key: string): boolean {
    const lit = this.lit();
    return lit !== null && !lit.has(key);
  }

  isLit(key: string): boolean {
    return this.lit()?.has(key) ?? false;
  }

  delay(key: string): string {
    return `${Math.min(this.order().get(key) ?? 0, STAGGER) * 14}ms`;
  }

  choose(key: string): void {
    this.focused.set(key);
    this.chosen.emit(key);
  }

  onKey(event: KeyboardEvent, key: string): void {
    const direction = ARROWS[event.key];
    if (!direction) return;
    event.preventDefault();
    const next = nearestIn(this.bodies(), key, direction);
    if (next === null) return;
    this.focused.set(next);
    this.reveal(next);
    Array.from(this.host.nativeElement.querySelectorAll<HTMLElement>('.gc__node'))
      .find((el) => el.dataset['key'] === next)
      ?.focus({ preventScroll: true });
  }

  onDown(event: PointerEvent): void {
    if ((event.target as Element).closest('.gc__node, .gc__tools')) return;
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
    if (this.pointers.size === 0) this.travel = 0;
    this.pointers = new Map(this.pointers).set(event.pointerId, { x: event.clientX, y: event.clientY });
  }

  onMove(event: PointerEvent): void {
    const last = this.pointers.get(event.pointerId);
    if (!last) return;
    const point: Point = { x: event.clientX, y: event.clientY };
    const other = Array.from(this.pointers).find(([id]) => id !== event.pointerId)?.[1];
    this.pointers = new Map(this.pointers).set(event.pointerId, point);
    this.travel = this.travel + Math.hypot(point.x - last.x, point.y - last.y);
    if (other) {
      const frame = this.host.nativeElement.getBoundingClientRect();
      const before = Math.max(1, Math.hypot(last.x - other.x, last.y - other.y));
      const after = Math.hypot(point.x - other.x, point.y - other.y);
      this.free = true;
      this.view.update((v) =>
        zoomAt(v, after / before, (point.x + other.x) / 2 - frame.left, (point.y + other.y) / 2 - frame.top),
      );
    } else if (this.travel > PRESS_TRAVEL) {
      this.free = true;
      this.view.update((v) => ({ ...v, x: v.x + point.x - last.x, y: v.y + point.y - last.y }));
    }
  }

  onUp(event: PointerEvent): void {
    if (!this.pointers.has(event.pointerId)) return;
    this.pointers = new Map(Array.from(this.pointers).filter(([id]) => id !== event.pointerId));
    if (this.pointers.size === 0 && this.travel <= PRESS_TRAVEL && event.type === 'pointerup') {
      this.chosen.emit(null);
    }
  }

  onWheel(event: WheelEvent): void {
    event.preventDefault();
    const frame = this.host.nativeElement.getBoundingClientRect();
    this.free = true;
    this.view.update((v) =>
      zoomAt(v, Math.exp(-event.deltaY * 0.0015), event.clientX - frame.left, event.clientY - frame.top),
    );
  }

  /** "+" and "−": zoom around the middle of the frame. */
  zoom(factor: number): void {
    const { width, height } = this.size();
    this.free = true;
    this.view.update((v) => zoomAt(v, factor, width / 2, height / 2));
  }

  zoomIn(): void {
    this.zoom(ZOOM_STEP);
  }

  zoomOut(): void {
    this.zoom(1 / ZOOM_STEP);
  }

  /** "Alles zeigen": fit the drawing, and follow it again. */
  showAll(): void {
    this.free = false;
    this.refit();
  }

  private measure(): void {
    const el = this.host.nativeElement;
    this.size.set({ width: el.clientWidth, height: el.clientHeight });
    this.refit();
  }

  /** Take the nodes that show now: drop the bodies that left, place the new ones, and settle. */
  private arrange(ids: readonly string[], near: Adjacency): void {
    const before = keep(this.bodies(), new Set(ids));
    const known = new Set(before.map((b) => b.id));
    const fresh = ids.filter((id) => !known.has(id));
    if (before.length === 0) this.free = false;
    if (fresh.length > 0) this.order.set(new Map(fresh.map((id, i) => [id, i] as const)));
    const placed = place(before, ids, near);
    const still = reducedMotion();
    this.still.set(still);
    if (still) {
      this.stop();
      this.bodies.set(settle(placed, near));
      this.refit();
      return;
    }
    this.bodies.set(placed);
    this.refit();
    this.alpha = ALPHA_START;
    this.run();
  }

  private run(): void {
    if (this.frame !== null) return;
    this.frame = requestAnimationFrame(() => this.tick());
  }

  private tick(): void {
    this.frame = null;
    this.bodies.set(step(this.bodies(), this.near(), this.alpha));
    this.alpha = this.alpha * ALPHA_DECAY;
    this.refit();
    if (this.alpha >= ALPHA_MIN) this.run();
  }

  private stop(): void {
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = null;
    this.alpha = 0;
  }

  private refit(): void {
    if (this.free) return;
    const { width, height } = this.size();
    this.view.set(fit(bounds(this.bodies(), FIT_PAD), width, height));
  }

  /**
   * Move the view so that the node is inside the frame. From a zoom at which the titles
   * hide, the view also goes to 1:1, so the titles of the node and its neighbours have room.
   */
  private reveal(key: string): void {
    const body = this.places().get(key);
    const { width, height } = this.size();
    if (!body || width <= 0 || height <= 0) return;
    const v = this.view();
    const at = this.focusAt();
    if (v.zoom < LABEL_ZOOM) {
      this.free = true;
      this.view.set({ x: width * at.x - body.x, y: height * at.y - body.y, zoom: 1 });
      return;
    }
    const x = body.x * v.zoom + v.x;
    const y = body.y * v.zoom + v.y;
    const inside =
      x >= REVEAL_MARGIN && x <= width - REVEAL_MARGIN && y >= REVEAL_MARGIN && y <= height - REVEAL_MARGIN;
    if (inside) return;
    this.free = true;
    this.view.set({ x: width * at.x - body.x * v.zoom, y: height * at.y - body.y * v.zoom, zoom: v.zoom });
  }
}
