/**
 * Pointer/zoom/pan state machine of the flow canvas. Owns the transient drag,
 * connect and pan handles; graph/selection state is reached through the host
 * context so the component keeps a single source of truth.
 */
import type { WritableSignal } from '@angular/core';
import type { FlowGraph, TransitionBranch, TransitionDef } from '../admin.models';
import { blankTransition } from '../flow-graph.util';
import {
  NODE_H,
  NODE_W,
  type Point,
  type Selection,
  type ViewRect,
} from './flow-editor.models';
import { addTransition, moveStatesBy, setStatePosition } from './flow-graph-ops.util';

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
  positions(): Record<string, Point>;
  nodes(): ReadonlyArray<{ key: string; x: number; y: number; h: number }>;
  contentBounds(): ViewRect;
  deepKeys(groupId: string): string[];
  openGroup(id: string): void;
  selection: WritableSignal<Selection>;
  multiSel: WritableSignal<ReadonlySet<string>>;
  multiSelGroups: WritableSignal<ReadonlySet<string>>;
  tempEdge: WritableSignal<TempEdge | null>;
  view: WritableSignal<ViewRect | null>;
}

export class FlowCanvasInteraction {
  private drag: { key: string; dx: number; dy: number; moved: boolean } | null = null;
  /** Group drag: moves all (deep) member positions together. */
  private groupDrag: { id: string; lastX: number; lastY: number; moved: boolean } | null = null;
  private connectFrom: string | null = null;
  /** Branch (pass/fail) when dragging from a branch dot. */
  private connectBranch: string | null = null;
  /** Guard of the source dot — inherited by the new transition. */
  private connectGuard: TransitionDef['guard'] | null = null;
  /** World point under the cursor at pan start (stays fixed "under the finger"). */
  private panGrab: Point | null = null;

  constructor(private readonly host: FlowCanvasHost) {}

  /** Grab a node → move it, or (click without movement) select it.
   *  Shift-click toggles the multi-selection for "create group". */
  nodePointerDown(event: PointerEvent, key: string): void {
    event.stopPropagation();
    if (event.shiftKey) {
      const next = new Set(this.host.multiSel());
      if (next.has(key)) next.delete(key);
      else next.add(key);
      this.host.multiSel.set(next);
      return;
    }
    const p = this.toSvg(event);
    const pos = this.host.positions()[key] ?? { x: 0, y: 0 };
    this.drag = { key, dx: p.x - pos.x, dy: p.y - pos.y, moved: false };
    (event.target as Element).setPointerCapture?.(event.pointerId);
  }

  /** Grab a group box: dragging moves all deep members, a plain click OPENS
   *  the group (drill-down), shift-click toggles the multi-selection. */
  groupPointerDown(event: PointerEvent, id: string): void {
    event.stopPropagation();
    if (event.shiftKey) {
      const next = new Set(this.host.multiSelGroups());
      if (next.has(id)) next.delete(id);
      else next.add(id);
      this.host.multiSelGroups.set(next);
      return;
    }
    const p = this.toSvg(event);
    this.groupDrag = { id, lastX: p.x, lastY: p.y, moved: false };
    (event.target as Element).setPointerCapture?.(event.pointerId);
  }

  /** Start drawing a new edge from a connector dot; a branch/guard dot
   *  transfers its branch/guard onto the new transition. */
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
    if (this.drag) {
      const p = this.toSvg(event);
      const nx = Math.max(0, Math.round(p.x - this.drag.dx));
      const ny = Math.max(0, Math.round(p.y - this.drag.dy));
      const key = this.drag.key;
      this.drag.moved = true;
      this.host.updateGraph((g) => setStatePosition(g, key, nx, ny));
      return;
    }
    if (this.groupDrag) {
      const p = this.toSvg(event);
      const dx = p.x - this.groupDrag.lastX;
      const dy = p.y - this.groupDrag.lastY;
      this.groupDrag.lastX = p.x;
      this.groupDrag.lastY = p.y;
      this.groupDrag.moved = true;
      const deepKeys = this.host.deepKeys(this.groupDrag.id);
      this.host.updateGraph((g) => moveStatesBy(g, deepKeys, dx, dy));
      return;
    }
    if (this.connectFrom) {
      const from = this.host.positions()[this.connectFrom];
      const p = this.toSvg(event);
      this.host.tempEdge.set({ x1: from.x + NODE_W, y1: from.y + NODE_H / 2, x2: p.x, y2: p.y });
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
    if (this.drag) {
      // Click without movement = select; movement only commits the position.
      if (!this.drag.moved) this.host.selection.set({ kind: 'state', key: this.drag.key });
      this.drag = null;
      return;
    }
    if (this.groupDrag) {
      if (!this.groupDrag.moved) this.host.openGroup(this.groupDrag.id);
      this.groupDrag = null;
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

  /** Pointerdown on empty canvas: clear selection + start panning. */
  canvasPointerDown(event: PointerEvent): void {
    this.clearSelection();
    this.panGrab = this.toSvg(event);
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
  }

  clearSelection(): void {
    if (!this.drag && !this.connectFrom && !this.groupDrag) {
      this.host.selection.set(null);
      if (this.host.multiSel().size) this.host.multiSel.set(new Set());
    }
  }

  /** Wheel: zoom around the cursor (the world point under it stays fixed). */
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

  /** Reset zoom/fit (whole content). */
  resetView(): void {
    this.host.view.set(null);
  }

  /** Current view, initialised to "whole content" on first zoom/pan. */
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

  /** Client coordinates → SVG user space (drag/connect/zoom math). */
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

  /** State whose node rect contains the point (connect target). Only nodes of
   *  the current level — connecting into a group happens via drill-down. */
  private nodeAt(p: Point): string | null {
    for (const n of this.host.nodes()) {
      if (p.x >= n.x && p.x <= n.x + NODE_W && p.y >= n.y && p.y <= n.y + n.h) {
        return n.key;
      }
    }
    return null;
  }
}
