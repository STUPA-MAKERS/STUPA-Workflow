/**
 * Pointer, zoom and pan state machine of the flow canvas.
 *
 * The layout places every box (`flow-elk.ts`), so a box does not move under the
 * pointer: a press on a state selects it, a press on a group box opens it. This class
 * owns the transient connect and pan handles. It reaches graph and
 * selection state through the host context. The component stays the single source of
 * truth.
 */
import type { WritableSignal } from '@angular/core';
import type { FlowGraph, TransitionBranch, TransitionDef } from '../admin.models';
import { blankTransition } from '../flow-graph.util';
import type { Point, Selection, ViewRect } from './flow-editor.models';
import { addTransition } from './flow-graph-ops.util';

export interface TempEdge {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface FlowCanvasHost {
  svg(): SVGSVGElement | undefined;
  graph(): FlowGraph;
  updateGraph(fn: (g: FlowGraph) => FlowGraph): void;
  nodes(): ReadonlyArray<{ key: string; x: number; y: number; w: number; h: number }>;
  contentBounds(): ViewRect;
  openGroup(id: string): void;
  selection: WritableSignal<Selection>;
  multiSel: WritableSignal<ReadonlySet<string>>;
  multiSelGroups: WritableSignal<ReadonlySet<string>>;
  tempEdge: WritableSignal<TempEdge | null>;
  view: WritableSignal<ViewRect | null>;
}

export class FlowCanvasInteraction {
  private connectFrom: string | null = null;
  /** Branch (pass/fail) when dragging from a branch dot. */
  private connectBranch: string | null = null;
  /** Guard of the source dot. The new transition inherits it. */
  private connectGuard: TransitionDef['guard'] | null = null;
  /** World point under the cursor at pan start. It stays fixed under the finger. */
  private panGrab: Point | null = null;

  constructor(private readonly host: FlowCanvasHost) {}

  /** A press on a node selects it. Shift-click toggles the multi-selection that
   *  "create group" reads. */
  nodePointerDown(event: PointerEvent, key: string): void {
    event.stopPropagation();
    if (event.shiftKey) {
      const next = new Set(this.host.multiSel());
      if (next.has(key)) next.delete(key);
      else next.add(key);
      this.host.multiSel.set(next);
      return;
    }
    this.host.selection.set({ kind: 'state', key });
  }

  /** A press on a group box OPENS the group (drill-down). Shift-click toggles the
   *  multi-selection. */
  groupPointerDown(event: PointerEvent, id: string): void {
    event.stopPropagation();
    if (event.shiftKey) {
      const next = new Set(this.host.multiSelGroups());
      if (next.has(id)) next.delete(id);
      else next.add(id);
      this.host.multiSelGroups.set(next);
      return;
    }
    this.host.openGroup(id);
  }

  /** Start to draw a new edge from a connector dot. A branch dot or a guard dot
   *  copies its branch or guard onto the new transition. */
  connectPointerDown(
    event: PointerEvent,
    key: string,
    branch: string | null = null,
    guard: TransitionDef['guard'] | null = null,
  ): void {
    event.stopPropagation();
    this.connectFrom = key;
    this.connectBranch = branch;
    this.connectGuard = guard;
    const p = this.toSvg(event);
    this.host.tempEdge.set({ x1: p.x, y1: p.y, x2: p.x, y2: p.y });
    (event.target as Element).setPointerCapture?.(event.pointerId);
  }

  pointerMove(event: PointerEvent): void {
    const temp = this.host.tempEdge();
    if (this.connectFrom && temp) {
      // The line starts at the dot that was pressed and follows the pointer.
      const p = this.toSvg(event);
      this.host.tempEdge.set({ ...temp, x2: p.x, y2: p.y });
      return;
    }
    if (this.panGrab) {
      // Shift the view so the world point under the cursor is `panGrab` again.
      const now = this.toSvg(event);
      const v = this.ensureView();
      this.host.view.set({
        ...v,
        x: v.x + (this.panGrab.x - now.x),
        y: v.y + (this.panGrab.y - now.y),
      });
    }
  }

  pointerUp(event: PointerEvent): void {
    if (this.panGrab) {
      this.panGrab = null;
      return;
    }
    if (this.connectFrom) {
      const target = this.nodeAt(this.toSvg(event));
      if (target && target !== this.connectFrom) {
        const from = this.connectFrom;
        const branch = this.connectBranch as TransitionBranch | null;
        const guard = this.connectGuard;
        const t: TransitionDef = blankTransition(from, target);
        if (branch) t.branch = branch;
        if (guard) t.guard = guard;
        this.host.updateGraph((g) => addTransition(g, t));
        this.host.selection.set({
          kind: 'transition',
          index: (this.host.graph().transitions?.length ?? 1) - 1,
        });
      }
      this.connectFrom = null;
      this.connectBranch = null;
      this.connectGuard = null;
      this.host.tempEdge.set(null);
    }
  }

  /** Pointer down on the empty canvas. Nodes and group boxes stop propagation first. */
  canvasPointerDown(event: PointerEvent): void {
    this.clearSelection();
    this.panGrab = this.toSvg(event);
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
  }

  clearSelection(): void {
    if (!this.connectFrom) {
      this.host.selection.set(null);
      if (this.host.multiSel().size) this.host.multiSel.set(new Set());
    }
  }

  /** Zoom around the cursor. The world point under the cursor stays fixed. */
  wheel(event: WheelEvent): void {
    event.preventDefault();
    const v = this.ensureView();
    const c = this.toSvg(event);
    const factor = event.deltaY > 0 ? 1.12 : 1 / 1.12;
    this.applyZoom(v, factor, c);
  }

  zoomIn(): void {
    const v = this.ensureView();
    this.applyZoom(v, 1 / 1.2, { x: v.x + v.w / 2, y: v.y + v.h / 2 });
  }

  zoomOut(): void {
    const v = this.ensureView();
    this.applyZoom(v, 1.2, { x: v.x + v.w / 2, y: v.y + v.h / 2 });
  }

  /** Reset the zoom so the view fits the whole content again. */
  resetView(): void {
    this.host.view.set(null);
  }

  /** Current view. The first zoom or pan initializes it to the whole content. */
  private ensureView(): ViewRect {
    const v = this.host.view();
    if (v) return v;
    const init = { ...this.host.contentBounds() };
    this.host.view.set(init);
    return init;
  }

  private applyZoom(v: ViewRect, factor: number, center: Point): void {
    // Clamp zoom relative to the content width (0.2×…6×).
    const base = this.host.contentBounds().w;
    const minW = base / 6;
    const maxW = base * 5;
    const w = Math.min(maxW, Math.max(minW, v.w * factor));
    const ratio = w / v.w;
    const h = v.h * ratio;
    const x = center.x - (center.x - v.x) * ratio;
    const y = center.y - (center.y - v.y) * ratio;
    this.host.view.set({ x, y, w, h });
  }

  /** Map client coordinates to SVG user space for the drag, connect and zoom math. */
  private toSvg(event: MouseEvent): Point {
    const svg = this.host.svg();
    if (!svg) return { x: event.clientX, y: event.clientY };
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: event.clientX, y: event.clientY };
    const pt = svg.createSVGPoint();
    pt.x = event.clientX;
    pt.y = event.clientY;
    const local = pt.matrixTransform(ctm.inverse());
    return { x: local.x, y: local.y };
  }

  /** State whose node rect contains the point, that is, the connect target. Only
   *  nodes of the current level count. To connect into a group, drill down first. */
  private nodeAt(p: Point): string | null {
    for (const n of this.host.nodes()) {
      if (p.x >= n.x && p.x <= n.x + n.w && p.y >= n.y && p.y <= n.y + n.h) {
        return n.key;
      }
    }
    return null;
  }
}
