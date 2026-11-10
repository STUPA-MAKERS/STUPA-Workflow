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
  type EndRef,
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
  readonly id: string;
  readonly branch: string | null;
  readonly guard: TransitionDef['guard'] | null;
  readonly cy: number;
  readonly label: string;
}

export interface CanvasNode {
  readonly key: string;
  readonly label: string;
  readonly kind: string;
  readonly color: string | null;
  readonly isInitial: boolean;
  /** A terminal state: the node carries the tag "Endzustand" under its label. */
  readonly isTerminal: boolean;
  /** A vote state that takes its gremium from the cost center: the node carries the
   *  tag "Gremium: aus Kostenstelle" under its label. */
  readonly gremiumFromBudget: boolean;
  readonly selected: boolean;
  readonly multi: boolean;
  /** Not related to the focused state or transition: drawn faint. */
  readonly dim: boolean;
  readonly x: number;
  readonly y: number;
  /** The width fits the label. */
  readonly w: number;
  readonly h: number;
  readonly dots: readonly CanvasNodeDot[];
}

export interface CanvasEdge {
  readonly index: number;
  readonly d: string;
  /** Centre of the label. */
  readonly mx: number;
  readonly my: number;
  /** The label text; empty for a line without a label (a later member of a bundle). */
  readonly label: string;
  /** The line carries a label (a name or the bolt of an automatic transition). */
  readonly labeled: boolean;
  readonly automatic: boolean;
  readonly color: string | null;
  readonly selected: boolean;
  /** Not related to the focused state or transition: drawn faint. */
  readonly dim: boolean;
}

export interface FlowCanvasViewDeps {
  readonly graph: Signal<FlowGraph>;
  readonly currentGroupId: Signal<string | null>;
  readonly selection: Signal<Selection>;
  readonly multiSel: Signal<ReadonlySet<string>>;
  readonly multiSelGroups: Signal<ReadonlySet<string>>;
  /** The state under the pointer: it has the focus while no transition is selected. */
  readonly hover: Signal<string | null>;
  /**
   * The automatic layout of the level, once it answers. While a newer `layoutInput`
   * waits for its layout, the places of the last one stay and the lines are left out
   * (`routes` is empty): the transition indices of the old routes may be stale.
   */
  readonly layout: Signal<LevelLayout | null>;
  readonly stateLabel: (s: StateDef) => string;
  readonly guardDotLabel: (g: GuardGroup) => string;
}

/** One visible transition between two boxes of the level. */
interface LevelLink {
  readonly index: number;
  readonly t: TransitionDef;
  readonly src: string;
  readonly port: string;
  /** Start of the line relative to the source box. */
  readonly sx: number;
  readonly sy: number;
  readonly dst: string;
}

export interface FlowCanvasView {
  readonly positions: Signal<Record<string, Point>>;
  readonly groups: Signal<readonly FlowGroup[]>;
  readonly groupById: Signal<ReadonlyMap<string, FlowGroup>>;
  readonly parentGroupId: Signal<ReadonlyMap<string, string>>;
  readonly stateOwnerId: Signal<ReadonlyMap<string, string>>;
  readonly currentGroup: Signal<FlowGroup | undefined>;
  readonly breadcrumbs: Signal<readonly FlowGroup[]>;
  readonly visibleStates: Signal<readonly StateDef[]>;
  readonly childGroups: Signal<readonly FlowGroup[]>;
  readonly edgeEnds: Signal<readonly (EdgeEnds | null)[]>;
  readonly groupBoxes: Signal<readonly GroupBox[]>;
  readonly proxies: Signal<{
    readonly left: readonly ProxyBox[];
    readonly right: readonly ProxyBox[];
  }>;
  readonly nodes: Signal<readonly CanvasNode[]>;
  readonly edges: Signal<readonly CanvasEdge[]>;
  /** What the automatic layout needs to place the level. */
  readonly layoutInput: Signal<LayoutInput>;
  readonly contentBounds: Signal<ViewRect>;
  readonly deepKeys: (groupId: string) => readonly string[];
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

  const breadcrumbs = computed<readonly FlowGroup[]>(() =>
    breadcrumbPath(groupById(), parentGroupId(), deps.currentGroupId()),
  );

  const deepKeys = (groupId: string): readonly string[] => deepStateKeys(groupById(), groupId);

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
  const proxyIds = computed(
    (): { readonly left: readonly string[]; readonly right: readonly string[] } => {
      if (deps.currentGroupId() === null) return { left: [], right: [] };
      const ends = edgeEnds().filter((e): e is EdgeEnds => !!e);
      const proxyPid = (end: EndRef): readonly string[] => (end.type === 'proxy' ? [end.pid] : []);
      return {
        left: [...new Set(ends.flatMap((e) => proxyPid(e.src)))],
        right: [...new Set(ends.flatMap((e) => proxyPid(e.dst)))],
      };
    },
  );

  /**
   * Every visible transition with its source box, its dot and its target box. A state
   * starts the line at its branch dot (pass/fail) or at the dot of its guard group; a
   * group box has one dot per outgoing line, in the order of the transitions.
   */
  const links = computed<readonly LevelLink[]>(() => {
    const transitions = deps.graph().transitions ?? [];
    const ends = edgeEnds();
    const kindOf = new Map(deps.graph().states.map((s) => [s.key, s.kind] as const));
    const shapes = new Map(nodeShapes().map((n) => [n.s.key, n]));
    const groupsBy = new Map(groupShapes().map((b) => [b.g.id, b]));
    /** The rank of a line among the earlier lines out of the same group box. */
    const groupOutRank = (index: number, id: string): number =>
      ends.slice(0, index).filter((e) => e?.src.type === 'group' && e.src.id === id).length;
    const source = (
      t: TransitionDef,
      end: EndRef,
      index: number,
    ): Pick<LevelLink, 'src' | 'port' | 'sx' | 'sy'> | null => {
      switch (end.type) {
        case 'state': {
          const n = shapes.get(t.from);
          if (!n) return null;
          const sy = outDotYFor(t.from, kindOf.get(t.from), t, transitions, positions(), n.h);
          const id = t.branch ?? ((t.guard ? JSON.stringify(t.guard) : '') || 'out');
          const dot = n.dots.find((d) => d.id === id) ?? n.dots.find((d) => d.cy === sy);
          return { src: stateBox(t.from), port: dot?.id ?? 'out', sx: n.w, sy };
        }
        case 'group': {
          const b = groupsBy.get(end.id);
          if (!b) return null;
          const j = groupOutRank(index, end.id);
          return {
            src: groupBox(end.id),
            port: `o${j}`,
            sx: GROUP_W,
            sy: dotY(j, b.outCount, b.h),
          };
        }
        case 'proxy':
          return { src: proxyBox('l', end.pid), port: 'out', sx: PROXY_W, sy: PROXY_H / 2 };
      }
    };
    const target = (t: TransitionDef, end: EndRef): string | null => {
      switch (end.type) {
        case 'state':
          return shapes.has(t.to) ? stateBox(t.to) : null;
        case 'group':
          return groupsBy.has(end.id) ? groupBox(end.id) : null;
        case 'proxy':
          return proxyBox('r', end.pid);
      }
    };
    return transitions.flatMap((t, index): readonly LevelLink[] => {
      const e = ends[index];
      const from = e ? source(t, e.src, index) : null;
      const dst = e && from ? target(t, e.dst) : null;
      return from && dst !== null ? [{ index, t, ...from, dst }] : [];
    });
  });

  const layoutInput = computed<LayoutInput>(() => {
    const { left, right } = proxyIds();
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
  const focus = computed<{
    readonly boxes: ReadonlySet<string>;
    readonly edge: number | null;
    readonly state: string | null;
  } | null>(() => {
    const sel = deps.selection();
    if (sel?.kind === 'transition') {
      const l = links().find((x) => x.index === sel.index);
      return l ? { boxes: new Set([l.src, l.dst]), edge: sel.index, state: null } : null;
    }
    const key = deps.hover() ?? (sel?.kind === 'state' ? sel.key : null);
    if (!key) return null;
    const box = stateBox(key);
    const linked = links().flatMap((l) => [
      ...(l.src === box ? [l.dst] : []),
      ...(l.dst === box ? [l.src] : []),
    ]);
    return { boxes: new Set([box, ...linked]), edge: null, state: box };
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
    const shapes = [...nodes(), ...groupBoxes()];
    const xs = shapes.flatMap((n) => [n.x, n.x + n.w]);
    const ys = shapes.map((n) => n.y);
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
    const make = (ids: readonly string[], side: 'l' | 'r', x: number): ProxyBox[] =>
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
    const boxes = new Map<string, { readonly x: number; readonly y: number; readonly h: number }>([
      ...nodes().map((n) => [stateBox(n.key), n] as const),
      ...groupBoxes().map((b) => [groupBox(b.id), b] as const),
      ...proxies().left.map((p) => [proxyBox('l', p.pid), { ...p, h: PROXY_H }] as const),
      ...proxies().right.map((p) => [proxyBox('r', p.pid), { ...p, h: PROXY_H }] as const),
    ]);
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
    const dotText = (n: CanvasNode): number =>
      Math.max(0, ...n.dots.map((d) => (d.label ? textWidth(d.label, DOT_FONT) + 14 : 0)));
    const { left, right } = proxies();
    const rects = [
      ...nodes().map((n) => ({ x: n.x, y: n.y, w: n.w + dotText(n), h: n.h })),
      ...groupBoxes(),
      ...[...left, ...right].map((p) => ({ x: p.x, y: p.y, w: PROXY_W, h: PROXY_H })),
    ];
    const xs = rects.flatMap((b) => [b.x, b.x + b.w]);
    const ys = rects.flatMap((b) => [b.y, b.y + b.h]);
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
