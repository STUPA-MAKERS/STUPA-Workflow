/**
 * Drill-down helpers for the group hierarchy of a flow graph. A group is a pure layout
 * concept in `layout.groups`. The flow engine never sees a group.
 */
import type { FlowGraph, FlowGroup } from '../admin.models';
import type { EdgeEnds, EndRef } from './flow-editor.models';

/** Resolution of a state on a level: directly visible, inside a sub-group box, or external. */
export type LevelRef = { readonly kind: 'state' } | { readonly kind: 'group'; readonly id: string } | null;

export function buildGroupById(groups: readonly FlowGroup[]): ReadonlyMap<string, FlowGroup> {
  return new Map(groups.map((g) => [g.id, g]));
}

/** Parent relation of groups (child id → parent id) derived from `groupIds`. */
export function buildParentGroupId(groups: readonly FlowGroup[]): ReadonlyMap<string, string> {
  return new Map(groups.flatMap((g) => (g.groupIds ?? []).map((child) => [child, g.id] as const)));
}

/** Direct owner of a state (group id). An absent entry means the top level. */
export function buildStateOwnerId(groups: readonly FlowGroup[]): ReadonlyMap<string, string> {
  return new Map(groups.flatMap((g) => g.stateKeys.map((k) => [k, g.id] as const)));
}

/** Transitively contained state keys of a group (including sub-groups). */
export function deepStateKeys(groupById: ReadonlyMap<string, FlowGroup>, groupId: string): readonly string[] {
  const walk = (id: string, seen: ReadonlySet<string>): KeyWalk => {
    if (seen.has(id)) return { keys: [], seen };
    const marked = new Set([...seen, id]);
    const g = groupById.get(id);
    if (!g) return { keys: [], seen: marked };
    return (g.groupIds ?? []).reduce<KeyWalk>((acc, child) => {
      const sub = walk(child, acc.seen);
      return { keys: [...acc.keys, ...sub.keys], seen: sub.seen };
    }, { keys: g.stateKeys, seen: marked });
  };
  return walk(groupId, new Set()).keys;
}

/** The state keys found so far and the groups already walked. */
interface KeyWalk {
  readonly keys: readonly string[];
  readonly seen: ReadonlySet<string>;
}

/**
 * Resolve a state on a level: directly visible ('state'), shown as a
 * sub-group box ('group'), or outside the level (null → proxy).
 */
function resolveAt(
  stateOwnerId: ReadonlyMap<string, string>,
  parentGroupId: ReadonlyMap<string, string>,
  stateKey: string,
  ctx: string | null,
): LevelRef {
  const owner = stateOwnerId.get(stateKey) ?? null;
  const climb = (g: string | null, guard: ReadonlySet<string>): LevelRef => {
    if (g === null || guard.has(g)) return null;
    const parent = parentGroupId.get(g) ?? null;
    return parent === ctx ? { kind: 'group', id: g } : climb(parent, new Set([...guard, g]));
  };
  return owner === ctx ? { kind: 'state' } : climb(owner, new Set());
}

/**
 * Representative of an external state for the proxy columns. It is what the user sees
 * of that state on the closest enclosing level: the state itself or its group.
 */
function proxyRefFor(
  stateOwnerId: ReadonlyMap<string, string>,
  parentGroupId: ReadonlyMap<string, string>,
  stateKey: string,
  currentGroupId: string | null,
): { readonly pid: string; readonly isGroup: boolean; readonly entityId: string } {
  let ctx = currentGroupId;
  while (ctx !== null) {
    ctx = parentGroupId.get(ctx) ?? null;
    const r = resolveAt(stateOwnerId, parentGroupId, stateKey, ctx);
    if (r) {
      return r.kind === 'state'
        ? { pid: `state:${stateKey}`, isGroup: false, entityId: stateKey }
        : { pid: `group:${r.id}`, isGroup: true, entityId: r.id };
    }
  }
  return { pid: `state:${stateKey}`, isGroup: false, entityId: stateKey };
}

/**
 * Visible edge ends per transition on a level (null = invisible on this level:
 * fully internal to one sub-group or fully external).
 */
export function computeEdgeEnds(
  graph: FlowGraph,
  ctx: string | null,
  stateOwnerId: ReadonlyMap<string, string>,
  parentGroupId: ReadonlyMap<string, string>,
): readonly (EdgeEnds | null)[] {
  return (graph.transitions ?? []).map((t) => {
    const src = resolveAt(stateOwnerId, parentGroupId, t.from, ctx);
    const dst = resolveAt(stateOwnerId, parentGroupId, t.to, ctx);
    if (!src && !dst) return null;
    if (src && dst) {
      if (src.kind === 'group' && dst.kind === 'group' && src.id === dst.id) return null;
      if (src.kind === 'state' && dst.kind === 'state' && t.from === t.to) return null;
    }
    const toRef = (r: LevelRef, key: string): EndRef =>
      r === null
        ? { type: 'proxy', pid: proxyRefFor(stateOwnerId, parentGroupId, key, ctx).pid }
        : r.kind === 'state'
          ? { type: 'state', key }
          : { type: 'group', id: r.id };
    return { src: toRef(src, t.from), dst: toRef(dst, t.to) };
  });
}

/** Breadcrumb path: top level … current group. */
export function breadcrumbPath(
  groupById: ReadonlyMap<string, FlowGroup>,
  parentGroupId: ReadonlyMap<string, string>,
  currentGroupId: string | null,
): readonly FlowGroup[] {
  const path: FlowGroup[] = [];
  let id = currentGroupId;
  while (id) {
    const g = groupById.get(id);
    if (!g) break;
    path.unshift(g);
    id = parentGroupId.get(id) ?? null;
  }
  return path;
}
