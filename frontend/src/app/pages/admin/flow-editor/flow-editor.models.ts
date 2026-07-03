import type { TransitionDef } from '../admin.models';

/**
 * Current canvas selection: a state (by key) or a transition (by index).
 * Groups are never selected — clicking one drills down into it.
 */
export type Selection =
  | { kind: 'state'; key: string }
  | { kind: 'transition'; index: number }
  | null;

/** One rendered group box on the current drill-down level. */
export interface GroupBox {
  id: string;
  name: string;
  color: string | null;
  multi: boolean;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Transitively contained state count (badge). */
  count: number;
  /** Transitively contained state keys (dragging moves them all). */
  deepKeys: string[];
  /** Outgoing boundary-edge count. */
  outCount: number;
  /** Y offsets of the outgoing dots (fixed spacing, centered). */
  outDotYs: number[];
}

/** Visible end of an edge on the current drill-down level. */
export type EndRef =
  | { type: 'state'; key: string }
  | { type: 'group'; id: string }
  | { type: 'proxy'; pid: string };

export interface EdgeEnds {
  src: EndRef;
  dst: EndRef;
}

/** Proxy node while drilled into a group: external source (left) or target (right). */
export interface ProxyBox {
  /** Stable id: `state:<key>` | `group:<id>`. */
  pid: string;
  label: string;
  isGroup: boolean;
  x: number;
  y: number;
}

/**
 * Outgoing transitions of one node sharing an identical guard. One connector
 * dot per distinct guard; group order is the evaluation/priority order
 * (first matching guard wins).
 */
export interface GuardGroup {
  /** Stable guard signature (`''` = no guard / catch-all). */
  sig: string;
  guard: TransitionDef['guard'] | null;
  op: string;
  value: string;
  /** Indices of the member transitions in the `transitions` array. */
  indices: number[];
}

/** Row of the incoming/outgoing transition lists for a selected state. */
export interface TransitionListRow {
  index: number;
  from: string;
  to: string;
  label: string;
  guard: string;
  automatic: boolean;
  branch: string | null;
}

export interface TransitionLists {
  incoming: TransitionListRow[];
  outgoing: TransitionListRow[];
}

export interface Point {
  x: number;
  y: number;
}

export interface ViewRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const NODE_W = 150;
export const NODE_H = 52;
export const MARGIN = 40;

/** Connector dots use a FIXED spacing — nodes/groups grow in height instead. */
export const DOT_GAP = 22;
export const DOT_PAD = 16;

export const GROUP_W = 180;
export const GROUP_H = 64;

export const PROXY_W = 150;
export const PROXY_H = 44;
export const PROXY_GAP = 78;
export const PROXY_COL_GAP = 240;
