/**
 * Drill-down helpers for the group hierarchy of a flow graph. Groups are a
 * pure layout concept (`layout.groups`) — the flow engine never sees them.
 */
import type { FlowGraph, FlowGroup } from '../admin.models';
import type { EdgeEnds, EndRef } from './flow-editor.models';

/** Resolution of a state on a level: directly visible, inside a sub-group box, or external. */
export type LevelRef = { kind: 'state' } | { kind: 'group'; id: string } | null;

export function buildGroupById(groups: readonly FlowGroup[]): Map<string, FlowGroup> {
  return new Map(groups.map((g) => [g.id, g]));
}

/** Parent relation of groups (child id → parent id) derived from `groupIds`. */
export function buildParentGroupId(groups: readonly FlowGroup[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const g of groups) {
    for (const child of g.groupIds ?? []) map.set(child, g.id);
  }
  return map;
}

/** Direct owner of a state (group id) — absent ⇒ top level. */
export function buildStateOwnerId(groups: readonly FlowGroup[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const g of groups) {
    for (const k of g.stateKeys) map.set(k, g.id);
  }
  return map;
}

/** Transitively contained state keys of a group (including sub-groups). */
export function deepStateKeys(groupById: Map<string, FlowGroup>, groupId: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const walk = (id: string): void => {
    if (seen.has(id)) return; // cycle guard — normalized graphs never cycle
    seen.add(id);
    const g = groupById.get(id);
    if (!g) return;
    out.push(...g.stateKeys);
    for (const child of g.groupIds ?? []) walk(child);
  };
  walk(groupId);
  return out;
}

/**
 * Resolve a state on a level: directly visible ('state'), shown as a
 * sub-group box ('group'), or outside the level (null → proxy).
 */
export function resolveAt(
  stateOwnerId: Map<string, string>,
  parentGroupId: Map<string, string>,
  stateKey: string,
  ctx: string | null,
): LevelRef {
  const owner = stateOwnerId.get(stateKey) ?? null;
  if (owner === ctx) return { kind: 'state' };
  let g: string | null = owner;
  const guard = new Set<string>();
  while (g !== null && !guard.has(g)) {
    guard.add(g);
    const parent: string | null = parentGroupId.get(g) ?? null;
    if (parent === ctx) return { kind: 'group', id: g };
    g = parent;
  }
  return null;
}

/**
 * Representative of an EXTERNAL state for the proxy columns: what one would
 * see of it on the closest enclosing level (the state itself or its group).
 */
export function proxyRefFor(
  stateOwnerId: Map<string, string>,
  parentGroupId: Map<string, string>,
  stateKey: string,
  currentGroupId: string | null,
): { pid: string; isGroup: boolean; entityId: string } {
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
  stateOwnerId: Map<string, string>,
  parentGroupId: Map<string, string>,
): (EdgeEnds | null)[] {
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
  groupById: Map<string, FlowGroup>,
  parentGroupId: Map<string, string>,
  currentGroupId: string | null,
): FlowGroup[] {
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
