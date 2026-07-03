/**
 * Derived canvas view-model of the flow editor: all read-only geometry
 * (nodes, edges, group boxes, proxies, bounds) computed from the graph plus
 * the drill-down/selection state. Pure with respect to its inputs — labels
 * come in via callbacks so i18n/catalogue lookups stay in the component.
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
  selected: boolean;
  multi: boolean;
  x: number;
  y: number;
  h: number;
  dots: CanvasNodeDot[];
}

export interface CanvasEdge {
  index: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  d: string;
  mx: number;
  my: number;
  label: string;
  automatic: boolean;
  color: string | null;
  selected: boolean;
}

export interface FlowCanvasViewDeps {
  graph: Signal<FlowGraph>;
  currentGroupId: Signal<string | null>;
  selection: Signal<Selection>;
  multiSel: Signal<ReadonlySet<string>>;
  multiSelGroups: Signal<ReadonlySet<string>>;
  stateLabel: (s: StateDef) => string;
  guardDotLabel: (g: GuardGroup) => string;
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
  contentBounds: Signal<ViewRect>;
  deepKeys: (groupId: string) => string[];
}

/** Node height grows once the dots no longer fit the base height at fixed spacing. */
function nodeHeight(dotCount: number): number {
  return Math.max(NODE_H, 2 * DOT_PAD + Math.max(0, dotCount - 1) * DOT_GAP);
}

/** Y of a connector dot: fixed spacing, vertically centered. */
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
 * Y offset of the source dot of a transition: its branch dot (vote) or the
 * dot of its guard group — consistent with the combined dot list in `nodes`.
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

  /** One box per sub-group: centered on the (hidden) member bbox, height grows with out-dots. */
  const groupBoxes = computed<GroupBox[]>(() => {
    const pos = positions();
    const ends = edgeEnds();
    const multi = deps.multiSelGroups();
    return childGroups()
      .map((g) => {
        const dk = deepKeys(g.id);
        const pts = dk.map((k) => pos[k]).filter((p): p is Point => !!p);
        if (pts.length === 0) return null;
        const minX = Math.min(...pts.map((p) => p.x));
        const minY = Math.min(...pts.map((p) => p.y));
        const maxX = Math.max(...pts.map((p) => p.x)) + NODE_W;
        const maxY = Math.max(...pts.map((p) => p.y)) + NODE_H;
        const outCount = ends.filter((e) => e?.src.type === 'group' && e.src.id === g.id).length;
        const h = Math.max(GROUP_H, 2 * DOT_PAD + Math.max(0, outCount - 1) * DOT_GAP);
        const cx = (minX + maxX) / 2;
        const cy = (minY + maxY) / 2;
        return {
          id: g.id,
          name: g.name,
          color: g.color ?? null,
          multi: multi.has(g.id),
          x: cx - GROUP_W / 2,
          y: cy - h / 2,
          w: GROUP_W,
          h,
          count: dk.length,
          deepKeys: dk,
          outCount,
          outDotYs: Array.from({ length: outCount }, (_, i) => dotY(i, outCount, h)),
        };
      })
      .filter((b): b is GroupBox => b !== null);
  });

  const nodes = computed<CanvasNode[]>(() => {
    const pos = positions();
    const sel = deps.selection();
    const multi = deps.multiSel();
    const transitions = deps.graph().transitions ?? [];
    return visibleStates().map((s) => {
      // vote: one labeled dot per branch (pass/fail) PLUS the guard dots for
      // manual exits. normal: one dot per distinct guard (+ a default dot for
      // drawing new guard-less edges).
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
          // Dragging from a guard dot: the new transition inherits its guard.
          guard: gp.guard ?? null,
          cy: dotY(branches.length + i, total, h),
          label: gp.sig ? deps.guardDotLabel(gp) : '',
        })),
      ];
      return {
        key: s.key,
        label: deps.stateLabel(s),
        kind: s.kind ?? 'normal',
        color: s.color ?? null,
        isInitial: !!s.isInitial,
        selected: sel?.kind === 'state' && sel.key === s.key,
        multi: multi.has(s.key),
        x: pos[s.key]?.x ?? 0,
        y: pos[s.key]?.y ?? 0,
        h,
        dots,
      };
    });
  });

  /** Proxy columns while drilled in: external sources left, external targets right. */
  const proxies = computed<{ left: ProxyBox[]; right: ProxyBox[] }>(() => {
    if (deps.currentGroupId() === null) return { left: [], right: [] };
    const ends = edgeEnds();
    const leftIds: string[] = [];
    const rightIds: string[] = [];
    for (const e of ends) {
      if (!e) continue;
      if (e.src.type === 'proxy' && !leftIds.includes(e.src.pid)) leftIds.push(e.src.pid);
      if (e.dst.type === 'proxy' && !rightIds.includes(e.dst.pid)) rightIds.push(e.dst.pid);
    }
    // Columns left/right of the content bbox (nodes + group boxes).
    const xs: number[] = [];
    const ys: number[] = [];
    for (const n of nodes()) {
      xs.push(n.x, n.x + NODE_W);
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
    const make = (ids: string[], x: number): ProxyBox[] =>
      ids.map((pid, i) => ({ pid, ...label(pid), x, y: minY + i * PROXY_GAP }));
    return {
      left: make(leftIds, minX - PROXY_COL_GAP),
      right: make(rightIds, maxX + PROXY_COL_GAP),
    };
  });

  const edges = computed<CanvasEdge[]>(() => {
    const pos = positions();
    const sel = deps.selection();
    const transitions = deps.graph().transitions ?? [];
    const kindOf = new Map(deps.graph().states.map((s) => [s.key, s.kind] as const));
    const ends = edgeEnds();
    const nodeH = new Map(nodes().map((n) => [n.key, n.h]));
    const boxes = new Map(groupBoxes().map((b) => [b.id, b]));
    const { left, right } = proxies();
    const leftBy = new Map(left.map((p) => [p.pid, p]));
    const rightBy = new Map(right.map((p) => [p.pid, p]));
    // Out-dot index per group edge: order of appearance.
    const groupOutSeen = new Map<string, number>();
    return transitions
      .map((t, index) => ({ t, index, e: ends[index] }))
      .filter((x): x is { t: TransitionDef; index: number; e: EdgeEnds } => !!x.e)
      .filter(
        ({ t, e }) =>
          (e.src.type !== 'state' || !!pos[t.from]) && (e.dst.type !== 'state' || !!pos[t.to]),
      )
      .map(({ t, index, e }) => {
        let x1: number;
        let y1: number;
        if (e.src.type === 'state') {
          const a = pos[t.from];
          x1 = a.x + NODE_W;
          // Start at the source dot: branch (pass/fail) or the guard dot.
          y1 =
            a.y +
            outDotYFor(t.from, kindOf.get(t.from), t, transitions, pos, nodeH.get(t.from) ?? NODE_H);
        } else if (e.src.type === 'group') {
          const b = boxes.get(e.src.id);
          const j = groupOutSeen.get(e.src.id) ?? 0;
          groupOutSeen.set(e.src.id, j + 1);
          x1 = (b?.x ?? 0) + (b?.w ?? GROUP_W);
          y1 = (b?.y ?? 0) + dotY(j, b?.outCount ?? 1, b?.h ?? GROUP_H);
        } else {
          const p = leftBy.get(e.src.pid);
          x1 = (p?.x ?? 0) + PROXY_W;
          y1 = (p?.y ?? 0) + PROXY_H / 2;
        }
        let x2: number;
        let y2: number;
        if (e.dst.type === 'state') {
          const b = pos[t.to];
          x2 = b.x;
          y2 = b.y + (nodeH.get(t.to) ?? NODE_H) / 2;
        } else if (e.dst.type === 'group') {
          const b = boxes.get(e.dst.id);
          x2 = b?.x ?? 0;
          y2 = (b?.y ?? 0) + (b?.h ?? GROUP_H) / 2;
        } else {
          const p = rightBy.get(e.dst.pid);
          x2 = p?.x ?? 0;
          y2 = (p?.y ?? 0) + PROXY_H / 2;
        }
        return {
          index,
          x1,
          y1,
          x2,
          y2,
          d: edgePath(x1, y1, x2, y2),
          mx: (x1 + x2) / 2,
          my: (y1 + y2) / 2,
          label: t.label?.['de'] ?? '',
          automatic: !!t.automatic,
          color: t.color ?? null,
          selected: sel?.kind === 'transition' && sel.index === index,
        };
      });
  });

  /**
   * Content bbox of the current level (nodes + group boxes + proxies) —
   * proxies can sit left of x=0, hence real bounds instead of 0/0. The SVG
   * renders 1:1 (viewBox == size) so 1 user unit == 1 px for exact dragging.
   */
  const contentBounds = computed<ViewRect>(() => {
    const xs: number[] = [];
    const ys: number[] = [];
    for (const n of nodes()) {
      xs.push(n.x, n.x + NODE_W);
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
    contentBounds,
    deepKeys,
  };
}
