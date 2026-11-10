import type { TransitionDef } from '../admin.models';

/**
 * Current canvas selection: a state (by key) or a transition (by index).
 * A group is never a selection. A click on a group drills down into it.
 */
export type Selection =
  | { readonly kind: 'state'; readonly key: string }
  | { readonly kind: 'transition'; readonly index: number }
  | null;

/** One rendered group box on the current drill-down level. */
export interface GroupBox {
  readonly id: string;
  readonly name: string;
  readonly color: string | null;
  readonly multi: boolean;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
  /** Transitively contained state count (badge). */
  readonly count: number;
  /** Transitively contained state keys. A drag moves all of them. */
  readonly deepKeys: readonly string[];
  /** Outgoing boundary-edge count. */
  readonly outCount: number;
  /** Y offsets of the outgoing dots (fixed spacing, centered). */
  readonly outDotYs: readonly number[];
}

/** Visible end of an edge on the current drill-down level. */
export type EndRef =
  | { readonly type: 'state'; readonly key: string }
  | { readonly type: 'group'; readonly id: string }
  | { readonly type: 'proxy'; readonly pid: string };

export interface EdgeEnds {
  readonly src: EndRef;
  readonly dst: EndRef;
}

/** Proxy node while drilled into a group: external source (left) or target (right). */
export interface ProxyBox {
  /** Stable id: `state:<key>` | `group:<id>`. */
  readonly pid: string;
  readonly label: string;
  readonly isGroup: boolean;
  readonly x: number;
  readonly y: number;
}

/**
 * Outgoing transitions of one node that share an identical guard. There is one
 * connector dot per distinct guard. The group order is the evaluation order, also
 * called the priority order. The first guard that matches wins.
 */
export interface GuardGroup {
  /** Stable guard signature (`''` = no guard / catch-all). */
  readonly sig: string;
  readonly guard: TransitionDef['guard'] | null;
  readonly op: string;
  readonly value: string;
  /** Indices of the member transitions in the `transitions` array. */
  readonly indices: readonly number[];
}

/** Row of the incoming/outgoing transition lists for a selected state. */
export interface TransitionListRow {
  readonly index: number;
  readonly from: string;
  readonly to: string;
  readonly label: string;
  readonly guard: string;
  readonly automatic: boolean;
  readonly branch: string | null;
}

export interface TransitionLists {
  readonly incoming: readonly TransitionListRow[];
  readonly outgoing: readonly TransitionListRow[];
}

export interface Point {
  readonly x: number;
  readonly y: number;
}

export interface ViewRect {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

export const NODE_W = 150;
export const NODE_H = 52;
export const MARGIN = 40;

/** Connector dots use a fixed spacing. Nodes and groups grow in height instead. */
export const DOT_GAP = 22;
export const DOT_PAD = 16;

export const GROUP_W = 180;
export const GROUP_H = 64;

export const PROXY_W = 150;
export const PROXY_H = 44;
export const PROXY_GAP = 78;
export const PROXY_COL_GAP = 240;
