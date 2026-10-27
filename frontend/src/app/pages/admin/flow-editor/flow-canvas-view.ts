/**
 * Derived canvas view model of the flow editor.
 *
 * It computes all read-only geometry from the graph and from the drill-down and
 * selection state: nodes, edges, group boxes, proxies and bounds. The module stays pure
 * with respect to its inputs. Labels arrive through callbacks, so the i18n and catalog
 * lookups stay in the component.
 *
 * The places come from the automatic layout of the level (`layoutInput` in,
 * `deps.layout` back, see `flow-elk.ts`). Without a layout (no layouter, or it failed),
 * the boxes stand at the stored positions and the lines are plain curves. While a newer
 * input waits for its layout, a line without a route is left out, so no curve flashes up.
 */
import { type Signal, computed } from '@angular/core';
import type { FlowGraph, FlowGroup, StateDef, TransitionDef } from '../admin.models';
import {
  DOT_GAP,
  DOT_PAD,
  GROUP_H,
  GROUP_W,
  MARGIN,
  NODE_H,
  NODE_W,
  PROXY_COL_GAP,
  PROXY_GAP,
  PROXY_H,
  PROXY_W,
  type EdgeEnds,
  type GroupBox,
  type GuardGroup,
  type Point,
  type ProxyBox,
  type Selection,
  type ViewRect,
} from './flow-editor.models';
import { DOT_FONT, type LayoutInput, type LevelLayout, NODE_FONT, textWidth } from './flow-elk';
import { outDots, sortedBranchDots } from './flow-guard.util';
import {
  breadcrumbPath,
  buildGroupById,
  buildParentGroupId,
  buildStateOwnerId,
  computeEdgeEnds,
  deepStateKeys,
} from './flow-level.util';

export interface CanvasNodeDot {
  id: string;
  branch: string | null;
  guard: TransitionDef['guard'] | null;
  cy: number;
  label: string;
}

export interface CanvasNode {
  key: string;
  label: string;
  kind: string;
  color: string | null;
  isInitial: boolean;
  /** A terminal state: the node carries the tag "Endzustand" under its label. */
  isTerminal: boolean;
  /** A vote state that takes its gremium from the cost center: the node carries the
   *  tag "Gremium: aus Kostenstelle" under its label. */
  gremiumFromBudget: boolean;
  selected: boolean;
  multi: boolean;
  /** Not related to the focused state or transition: drawn faint. */
  dim: boolean;
  x: number;
  y: number;
  /** The width fits the label. */
  w: number;
  h: number;
  dots: CanvasNodeDot[];
}

export interface CanvasEdge {
  index: number;
  d: string;
  /** Centre of the label. */
  mx: number;
  my: number;
  /** The label text; empty for a line without a label (a later member of a bundle). */
  label: string;
  /** The line carries a label (a name or the bolt of an automatic transition). */
  labeled: boolean;
  automatic: boolean;
  color: string | null;
  selected: boolean;
  /** Not related to the focused state or transition: drawn faint. */
  dim: boolean;
}

export interface FlowCanvasViewDeps {
  graph: Signal<FlowGraph>;
  currentGroupId: Signal<string | null>;
  selection: Signal<Selection>;
  multiSel: Signal<ReadonlySet<string>>;
  multiSelGroups: Signal<ReadonlySet<string>>;
  /** The state under the pointer: it has the focus while no transition is selected. */
  hover: Signal<string | null>;
  /**
   * The automatic layout of the level, once it answers. While a newer `layoutInput`
   * waits for its layout, the places of the last one stay and the lines are left out
   * (`routes` is empty): the transition indices of the old routes may be stale.
   */
  layout: Signal<LevelLayout | null>;
  stateLabel: (s: StateDef) => string;
  guardDotLabel: (g: GuardGroup) => string;
}

/** One visible transition between two boxes of the level. */
interface LevelLink {
  index: number;
  t: TransitionDef;
  src: string;
  port: string;
  /** Start of the line relative to the source box. */
  sx: number;
  sy: number;
  dst: string;
}

export interface FlowCanvasView {
  positions: Signal<Record<string, Point>>;
  groups: Signal<FlowGroup[]>;
  groupById: Signal<Map<string, FlowGroup>>;
  parentGroupId: Signal<Map<string, string>>;
  stateOwnerId: Signal<Map<string, string>>;
  currentGroup: Signal<FlowGroup | undefined>;
  breadcrumbs: Signal<FlowGroup[]>;
  visibleStates: Signal<StateDef[]>;
  childGroups: Signal<FlowGroup[]>;
  edgeEnds: Signal<(EdgeEnds | null)[]>;
  groupBoxes: Signal<GroupBox[]>;
  proxies: Signal<{ left: ProxyBox[]; right: ProxyBox[] }>;
  nodes: Signal<CanvasNode[]>;
  edges: Signal<CanvasEdge[]>;
  /** What the automatic layout needs to place the level. */
  layoutInput: Signal<LayoutInput>;
  contentBounds: Signal<ViewRect>;
  deepKeys: (groupId: string) => string[];
}

/** Node height grows once the dots no longer fit the base height at fixed spacing. */
function nodeHeight(dotCount: number): number {
  return Math.max(NODE_H, 2 * DOT_PAD + Math.max(0, dotCount - 1) * DOT_GAP);
}

/** Box id of a state, a group box and a proxy in the layout. */
const stateBox = (key: string): string => `state:${key}`;
const groupBox = (id: string): string => `group:${id}`;
const proxyBox = (side: 'l' | 'r', pid: string): string => `proxy-${side}:${pid}`;

/** A node is as wide as its label needs, at least `NODE_W`. */
function nodeWidth(label: string): number {
  return Math.max(NODE_W, textWidth(label, NODE_FONT) + 40);
}

/** Y of a connector dot. The spacing is fixed and the column is centered vertically. */
function dotY(i: number, n: number, h: number): number {
  if (n <= 1) return h / 2;
  return h / 2 - ((n - 1) * DOT_GAP) / 2 + i * DOT_GAP;
}

/** Smooth (cubic Bézier) horizontal edge between two points. */
function edgePath(x1: number, y1: number, x2: number, y2: number): string {
  const dx = Math.max(Math.abs(x2 - x1) * 0.5, 30);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

/**
 * Y offset of the source dot of a transition.
 *
 * The dot is the branch dot of a vote state or the dot of the guard group. The order
 * matches the combined dot list that `nodes` builds.
 */
function outDotYFor(
  fromKey: string,
  kind: string | null | undefined,
  t: TransitionDef,
  transitions: readonly TransitionDef[],
  pos: Record<string, Point>,
  h: number,
): number {
  const branches = sortedBranchDots(fromKey, kind, transitions, pos);
  const groups = outDots(fromKey, transitions);
  const total = branches.length + groups.length;
  if (t.branch) {
    const i = branches.indexOf(t.branch);
    return i >= 0 ? dotY(i, total, h) : h / 2;
  }
  const sig = t.guard ? JSON.stringify(t.guard) : '';
  const i = groups.findIndex((g) => g.sig === sig);
  return dotY(branches.length + (i < 0 ? groups.length - 1 : i), total, h);
}

/**
 * A vote state gets one labeled dot per branch (pass/fail) plus the guard dots of the manual exits.
 * A normal state gets one dot per distinct guard and a default dot to draw a new edge without a
 * guard. The lines of the focus paint last, so they lie on top of the faint ones.
 */
export function createFlowCanvasView(deps: FlowCanvasViewDeps): FlowCanvasView {
  const positions = computed(() => deps.graph().layout?.positions ?? {});
  const groups = computed(() => deps.graph().layout?.groups ?? []);
  const groupById = computed(() => buildGroupById(groups()));
  const parentGroupId = computed(() => buildParentGroupId(groups()));
  const stateOwnerId = computed(() => buildStateOwnerId(groups()));

  const currentGroup = computed<FlowGroup | undefined>(() => {
    const id = deps.currentGroupId();
    return id ? groupById().get(id) : undefined;
  });

  const breadcrumbs = computed<FlowGroup[]>(() =>
    breadcrumbPath(groupById(), parentGroupId(), deps.currentGroupId()),
  );

  const deepKeys = (groupId: string): string[] => deepStateKeys(groupById(), groupId);

  const visibleStates = computed(() => {
    const ctx = deps.currentGroupId();
    const owner = stateOwnerId();
    return deps.graph().states.filter((s) => (owner.get(s.key) ?? null) === ctx);
  });

  const childGroups = computed(() => {
    const ctx = deps.currentGroupId();
    const parents = parentGroupId();
    return groups().filter((g) => (parents.get(g.id) ?? null) === ctx);
  });

  const edgeEnds = computed(() =>
    computeEdgeEnds(deps.graph(), deps.currentGroupId(), stateOwnerId(), parentGroupId()),
  );

  /** The size and the dots of each group box, before it has a place. */
  const groupShapes = computed(() => {
    const pos = positions();
    const ends = edgeEnds();
    return childGroups()
      .map((g) => {
        const dk = deepKeys(g.id);
        const pts = dk.map((k) => pos[k]).filter((p): p is Point => !!p);
        if (pts.length === 0) return null;
        const outCount = ends.filter((e) => e?.src.type === 'group' && e.src.id === g.id).length;
        const h = Math.max(GROUP_H, 2 * DOT_PAD + Math.max(0, outCount - 1) * DOT_GAP);
        const cx = (Math.min(...pts.map((p) => p.x)) + Math.max(...pts.map((p) => p.x)) + NODE_W) / 2;
        const cy = (Math.min(...pts.map((p) => p.y)) + Math.max(...pts.map((p) => p.y)) + NODE_H) / 2;
        return { g, dk, outCount, h, fx: cx - GROUP_W / 2, fy: cy - h / 2 };
      })
      .filter((b) => b !== null);
  });

  /** The label, the size and the dots of each visible state, before it has a place. */
  const nodeShapes = computed(() => {
    const pos = positions();
    const transitions = deps.graph().transitions ?? [];
    return visibleStates().map((s) => {
      const branches = sortedBranchDots(s.key, s.kind, transitions, pos);
      const guardGroups = outDots(s.key, transitions);
      const total = branches.length + guardGroups.length;
      const h = nodeHeight(total);
      const dots: CanvasNodeDot[] = [
        ...branches.map((b, i) => ({
          id: b,
          branch: b as string | null,
          guard: null as TransitionDef['guard'] | null,
          cy: dotY(i, total, h),
          label: b,
        })),
        ...guardGroups.map((gp, i) => ({
          id: gp.sig || 'out',
          branch: null as string | null,
          guard: gp.guard ?? null,
          cy: dotY(branches.length + i, total, h),
          label: gp.sig ? deps.guardDotLabel(gp) : '',
        })),
      ];
      const label = deps.stateLabel(s);
      return { s, label, w: nodeWidth(label), h, dots };
    });
  });

  /** The outside ends while drilled in: sources (left column) and targets (right). */
  const proxyIds = computed(() => {
    const left: string[] = [];
    const right: string[] = [];
    if (deps.currentGroupId() === null) return { left, right };
    for (const e of edgeEnds()) {
      if (!e) continue;
      if (e.src.type === 'proxy' && !left.includes(e.src.pid)) left.push(e.src.pid);
      if (e.dst.type === 'proxy' && !right.includes(e.dst.pid)) right.push(e.dst.pid);
    }
    return { left, right };
  });

  /**
   * Every visible transition with its source box, its dot and its target box. A state
   * starts the line at its branch dot (pass/fail) or at the dot of its guard group; a
   * group box has one dot per outgoing line, in the order of the transitions.
   */
  const links = computed<LevelLink[]>(() => {
    const transitions = deps.graph().transitions ?? [];
    const ends = edgeEnds();
    const kindOf = new Map(deps.graph().states.map((s) => [s.key, s.kind] as const));
    const shapes = new Map(nodeShapes().map((n) => [n.s.key, n]));
    const groupsBy = new Map(groupShapes().map((b) => [b.g.id, b]));
    const groupOutSeen = new Map<string, number>();
    const out: LevelLink[] = [];
    transitions.forEach((t, index) => {
      const e = ends[index];
      if (!e) return;
      let src: string;
      let port: string;
      let sx: number;
      let sy: number;
      if (e.src.type === 'state') {
        const n = shapes.get(t.from);
        if (!n) return;
        sy = outDotYFor(t.from, kindOf.get(t.from), t, transitions, positions(), n.h);
        const id = t.branch ?? ((t.guard ? JSON.stringify(t.guard) : '') || 'out');
        const dot = n.dots.find((d) => d.id === id) ?? n.dots.find((d) => d.cy === sy);
        src = stateBox(t.from);
        port = dot?.id ?? 'out';
        sx = n.w;
      } else if (e.src.type === 'group') {
        const b = groupsBy.get(e.src.id);
        if (!b) return;
        const j = groupOutSeen.get(e.src.id) ?? 0;
        groupOutSeen.set(e.src.id, j + 1);
        src = groupBox(e.src.id);
        port = `o${j}`;
        sx = GROUP_W;
        sy = dotY(j, b.outCount, b.h);
      } else {
        src = proxyBox('l', e.src.pid);
        port = 'out';
        sx = PROXY_W;
        sy = PROXY_H / 2;
      }
      let dst: string;
      if (e.dst.type === 'state') {
        if (!shapes.has(t.to)) return;
        dst = stateBox(t.to);
      } else if (e.dst.type === 'group') {
        if (!groupsBy.has(e.dst.id)) return;
        dst = groupBox(e.dst.id);
      } else {
        dst = proxyBox('r', e.dst.pid);
      }
      out.push({ index, t, src, port, sx, sy, dst });
    });
    return out;
  });

  const layoutInput = computed<LayoutInput>(() => {
    const { left, right } = proxyIds();
    const groupOut = new Map<string, number>();
    for (const l of links()) {
      if (l.src.startsWith('group:')) groupOut.set(l.src, (groupOut.get(l.src) ?? 0) + 1);
    }
    return {
      boxes: [
        ...left.map((pid) => ({
          id: proxyBox('l', pid),
          w: PROXY_W,
          h: PROXY_H,
          ports: [{ id: 'out', y: PROXY_H / 2, label: '' }],
          layer: 'first' as const,
        })),
        ...nodeShapes().map((n) => ({
          id: stateBox(n.s.key),
          w: n.w,
          h: n.h,
          ports: n.dots.map((d) => ({ id: d.id, y: d.cy, label: d.label })),
        })),
        ...groupShapes().map((b) => ({
          id: groupBox(b.g.id),
          w: GROUP_W,
          h: b.h,
          ports: Array.from({ length: b.outCount }, (_, j) => ({
            id: `o${j}`,
            y: dotY(j, b.outCount, b.h),
            label: '',
          })),
        })),
        ...right.map((pid) => ({ id: proxyBox('r', pid), w: PROXY_W, h: PROXY_H, ports: [], layer: 'last' as const })),
      ],
      links: links().map((l) => ({
        index: l.index,
        src: l.src,
        port: l.port,
        dst: l.dst,
        label: l.t.label?.['de'] ?? '',
        automatic: !!l.t.automatic,
      })),
    };
  });

  /**
   * The focus: the selected transition, else the state under the pointer, else the
   * selected state. Lines and boxes outside it are drawn faint.
   */
  const focus = computed<{ boxes: Set<string>; edge: number | null; state: string | null } | null>(() => {
    const sel = deps.selection();
    if (sel?.kind === 'transition') {
      const l = links().find((x) => x.index === sel.index);
      return l ? { boxes: new Set([l.src, l.dst]), edge: sel.index, state: null } : null;
    }
    const key = deps.hover() ?? (sel?.kind === 'state' ? sel.key : null);
    if (!key) return null;
    const box = stateBox(key);
    const boxes = new Set([box]);
    for (const l of links()) {
      if (l.src === box) boxes.add(l.dst);
      if (l.dst === box) boxes.add(l.src);
    }
    return { boxes, edge: null, state: box };
  });

  const placed = (id: string, fx: number, fy: number): Point => {
    const p = deps.layout()?.pos.get(id);
    return p ?? { x: fx, y: fy };
  };

  /** One box per sub-group. Without a layout it centres on its members. */
  const groupBoxes = computed<GroupBox[]>(() => {
    const multi = deps.multiSelGroups();
    return groupShapes().map((b) => {
      const p = placed(groupBox(b.g.id), b.fx, b.fy);
      return {
        id: b.g.id,
        name: b.g.name,
        color: b.g.color ?? null,
        multi: multi.has(b.g.id),
        x: p.x,
        y: p.y,
        w: GROUP_W,
        h: b.h,
        count: b.dk.length,
        deepKeys: b.dk,
        outCount: b.outCount,
        outDotYs: Array.from({ length: b.outCount }, (_, i) => dotY(i, b.outCount, b.h)),
      };
    });
  });

  const nodes = computed<CanvasNode[]>(() => {
    const pos = positions();
    const sel = deps.selection();
    const multi = deps.multiSel();
    const f = focus();
    return nodeShapes().map(({ s, label, w, h, dots }) => {
      const p = placed(stateBox(s.key), pos[s.key]?.x ?? 0, pos[s.key]?.y ?? 0);
      return {
        key: s.key,
        label,
        kind: s.kind ?? 'normal',
        color: s.color ?? null,
        isInitial: !!s.isInitial,
        isTerminal: !!s.isTerminal,
        gremiumFromBudget: s.kind === 'vote' && s.config?.gremiumSource === 'budget',
        selected: sel?.kind === 'state' && sel.key === s.key,
        multi: multi.has(s.key),
        dim: !!f && !f.boxes.has(stateBox(s.key)),
        x: p.x,
        y: p.y,
        w,
        h,
        dots,
      };
    });
  });

  /** Proxy columns while drilled in. External sources go left, external targets right. */
  const proxies = computed<{ left: ProxyBox[]; right: ProxyBox[] }>(() => {
    const { left: leftIds, right: rightIds } = proxyIds();
    if (!leftIds.length && !rightIds.length) return { left: [], right: [] };
    const xs: number[] = [];
    const ys: number[] = [];
    for (const n of nodes()) {
      xs.push(n.x, n.x + n.w);
      ys.push(n.y);
    }
    for (const b of groupBoxes()) {
      xs.push(b.x, b.x + b.w);
      ys.push(b.y);
    }
    const minX = xs.length ? Math.min(...xs) : MARGIN;
    const maxX = xs.length ? Math.max(...xs) : MARGIN + NODE_W;
    const minY = ys.length ? Math.min(...ys) : MARGIN;
    const label = (pid: string): { label: string; isGroup: boolean } => {
      if (pid.startsWith('group:')) {
        const g = groupById().get(pid.slice('group:'.length));
        return { label: g?.name ?? pid, isGroup: true };
      }
      const key = pid.slice('state:'.length);
      const s = deps.graph().states.find((x) => x.key === key);
      return { label: s ? deps.stateLabel(s) : key, isGroup: false };
    };
    const make = (ids: string[], side: 'l' | 'r', x: number): ProxyBox[] =>
      ids.map((pid, i) => ({ pid, ...label(pid), ...placed(proxyBox(side, pid), x, minY + i * PROXY_GAP) }));
    return {
      left: make(leftIds, 'l', minX - PROXY_COL_GAP),
      right: make(rightIds, 'r', maxX + PROXY_COL_GAP),
    };
  });

  const edges = computed<CanvasEdge[]>(() => {
    const sel = deps.selection();
    const layout = deps.layout();
    const routes = layout?.routes;
    const f = focus();
    const boxes = new Map<string, { x: number; y: number; h: number }>();
    for (const n of nodes()) boxes.set(stateBox(n.key), n);
    for (const b of groupBoxes()) boxes.set(groupBox(b.id), b);
    for (const p of proxies().left) boxes.set(proxyBox('l', p.pid), { ...p, h: PROXY_H });
    for (const p of proxies().right) boxes.set(proxyBox('r', p.pid), { ...p, h: PROXY_H });
    const laidOut = links().filter(({ index }) => !layout || routes!.has(index));
    const out = laidOut.map(({ index, t, src, sx, sy, dst }) => {
      const route = routes?.get(index);
      const bundle = route?.bundle ?? [index];
      const related = !f || (f.edge !== null ? bundle.includes(f.edge) : src === f.state || dst === f.state);
      const base = {
        index,
        automatic: !!t.automatic,
        color: t.color ?? null,
        selected: sel?.kind === 'transition' && bundle.includes(sel.index),
        dim: !related,
      };
      if (route) {
        const text = route.label?.text ?? '';
        return {
          ...base,
          d: route.d,
          mx: route.label?.x ?? 0,
          my: route.label?.y ?? 0,
          label: text,
          labeled: !!route.label,
          automatic: bundle.length > 1 ? bundle.every((i) => !!deps.graph().transitions[i]?.automatic) : base.automatic,
          color: bundle.length > 1 ? null : base.color,
        };
      }
      const a = boxes.get(src);
      const b = boxes.get(dst);
      const x1 = (a?.x ?? 0) + sx;
      const y1 = (a?.y ?? 0) + sy;
      const x2 = b?.x ?? 0;
      const y2 = (b?.y ?? 0) + (b?.h ?? NODE_H) / 2;
      const label = t.label?.['de'] ?? '';
      return {
        ...base,
        d: edgePath(x1, y1, x2, y2),
        mx: (x1 + x2) / 2,
        my: (y1 + y2) / 2 - 10,
        label,
        labeled: !!label || base.automatic,
      };
    });
    return [...out.filter((e) => e.dim), ...out.filter((e) => !e.dim)];
  });

  /**
   * Content bbox of the current level: nodes with the labels of their dots, group
   * boxes and proxies.
   *
   * A proxy can sit left of x=0, so this returns the real bounds and not 0/0. The SVG
   * renders 1:1, that is, the viewBox equals the size. One user unit is one pixel.
   */
  const contentBounds = computed<ViewRect>(() => {
    const xs: number[] = [];
    const ys: number[] = [];
    for (const n of nodes()) {
      const dotText = Math.max(0, ...n.dots.map((d) => (d.label ? textWidth(d.label, DOT_FONT) + 14 : 0)));
      xs.push(n.x, n.x + n.w + dotText);
      ys.push(n.y, n.y + n.h);
    }
    for (const b of groupBoxes()) {
      xs.push(b.x, b.x + b.w);
      ys.push(b.y, b.y + b.h);
    }
    const { left, right } = proxies();
    for (const p of [...left, ...right]) {
      xs.push(p.x, p.x + PROXY_W);
      ys.push(p.y, p.y + PROXY_H);
    }
    if (!xs.length) return { x: 0, y: 0, w: 480, h: 320 };
    const minX = Math.min(...xs) - MARGIN;
    const minY = Math.min(...ys) - MARGIN;
    return {
      x: minX,
      y: minY,
      w: Math.max(Math.max(...xs) + MARGIN - minX, 480),
      h: Math.max(Math.max(...ys) + MARGIN - minY, 320),
    };
  });

  return {
    positions,
    groups,
    groupById,
    parentGroupId,
    stateOwnerId,
    currentGroup,
    breadcrumbs,
    visibleStates,
    childGroups,
    edgeEnds,
    groupBoxes,
    proxies,
    nodes,
    edges,
    layoutInput,
    contentBounds,
    deepKeys,
  };
}
