/**
 * Pure flow-graph mutations. Every function returns a new graph and never mutates the
 * input. Signal consumers and the undo history therefore see distinct snapshots.
 */
import type {
  ActionDef,
  ActionType,
  CompareOp,
  FlowGraph,
  FlowGroup,
  Guard,
  GuardLeafOperator,
  NotifyRecipient,
  NotifyRecipientKind,
  StateConfig,
  StateDef,
  StateKind,
  TransitionBranch,
  TransitionDef,
} from '../admin.models';
import { autoLayout, blankState, layoutEntities } from '../flow-graph.util';
import {
  compareSpecOf,
  defaultGuard,
  groupsOf,
  guardOpOf,
  recipientsOf,
} from './flow-guard.util';
import {
  buildGroupById,
  buildParentGroupId,
  buildStateOwnerId,
  computeEdgeEnds,
  deepStateKeys,
} from './flow-level.util';
import type { EndRef, Point } from './flow-editor.models';


/** Unique state key (`state`, `state2`, …). */
export function uniqueStateKey(base: string, states: readonly StateDef[]): string {
  const used = new Set(states.map((s) => s.key));
  if (!used.has(base)) return base;
  let i = 2;
  while (used.has(`${base}${i}`)) i++;
  return `${base}${i}`;
}

/** Add a state. Inside an open group it becomes a member, else it stays invisible there. */
export function addState(g: FlowGraph, key: string, groupCtx: string | null): FlowGraph {
  const next = autoLayout({
    ...g,
    states: [...g.states, blankState(key, g.states.length === 0)],
  });
  if (!groupCtx) return next;
  return {
    ...next,
    layout: {
      ...(next.layout ?? {}),
      groups: (next.layout?.groups ?? []).map((gr) =>
        gr.id === groupCtx ? { ...gr, stateKeys: [...gr.stateKeys, key] } : gr,
      ),
    },
  };
}

/** Remove a state with its transitions, position and group membership. Empty groups go. */
export function removeState(g: FlowGraph, key: string): FlowGraph {
  const positions = { ...(g.layout?.positions ?? {}) };
  delete positions[key];
  const groups = (g.layout?.groups ?? [])
    .map((gr) => ({ ...gr, stateKeys: gr.stateKeys.filter((k) => k !== key) }))
    .filter((gr) => gr.stateKeys.length > 0 || (gr.groupIds ?? []).length > 0);
  return {
    ...g,
    states: g.states.filter((s) => s.key !== key),
    transitions: (g.transitions ?? []).filter((t) => t.from !== key && t.to !== key),
    layout: { positions, ...(groups.length ? { groups } : {}) },
  };
}

/** Exactly one initial: set the chosen state, reset all others. */
export function setInitial(g: FlowGraph, key: string): FlowGraph {
  return { ...g, states: g.states.map((s) => ({ ...s, isInitial: s.key === key })) };
}

/** Rename a state key. Transitions, positions and group memberships follow. */
export function renameState(g: FlowGraph, oldKey: string, key: string): FlowGraph {
  const positions = { ...(g.layout?.positions ?? {}) };
  if (positions[oldKey] && key) {
    positions[key] = positions[oldKey];
    if (key !== oldKey) delete positions[oldKey];
  }
  const groups = (g.layout?.groups ?? []).map((gr) => ({
    ...gr,
    stateKeys: gr.stateKeys.map((k) => (k === oldKey ? key : k)),
  }));
  return {
    ...g,
    states: g.states.map((s) => (s.key === oldKey ? { ...s, key } : s)),
    transitions: (g.transitions ?? []).map((t) => ({
      ...t,
      from: t.from === oldKey ? key : t.from,
      to: t.to === oldKey ? key : t.to,
    })),
    layout: { positions, ...(groups.length ? { groups } : {}) },
  };
}

function patchState(g: FlowGraph, key: string, patch: Partial<StateDef>): FlowGraph {
  return { ...g, states: g.states.map((s) => (s.key === key ? { ...s, ...patch } : s)) };
}

export function setStateLabel(
  g: FlowGraph,
  key: string,
  lang: 'de' | 'en',
  value: string,
): FlowGraph {
  return {
    ...g,
    states: g.states.map((s) =>
      s.key === key ? { ...s, label: { ...s.label, [lang]: value } } : s,
    ),
  };
}

export function setStateColor(g: FlowGraph, key: string, color: string): FlowGraph {
  return patchState(g, key, { color: color || null });
}

export function setStateEditAllowed(g: FlowGraph, key: string, on: boolean): FlowGraph {
  return patchState(g, key, { editAllowed: on });
}

export function setStateTerminal(g: FlowGraph, key: string, on: boolean): FlowGraph {
  return patchState(g, key, { isTerminal: on });
}

/** Change the state kind. This resets the kind-specific config but keeps the deadline policy. */
export function setStateKind(g: FlowGraph, key: string, kind: string): FlowGraph {
  const k = (kind || 'normal') as StateKind;
  const policy = g.states.find((s) => s.key === key)?.config?.deadlinePolicyKey;
  const config: StateConfig = policy ? { deadlinePolicyKey: policy } : {};
  return patchState(g, key, { kind: k === 'normal' ? null : k, config });
}

function patchConfig(g: FlowGraph, key: string, patch: Partial<StateConfig>): FlowGraph {
  return {
    ...g,
    states: g.states.map((s) =>
      s.key === key ? { ...s, config: { ...(s.config ?? {}), ...patch } } : s,
    ),
  };
}

export function setStateGremium(g: FlowGraph, key: string, gremiumId: string): FlowGraph {
  return patchConfig(g, key, { gremiumId: gremiumId || undefined });
}

export function setStateDeadlinePolicy(g: FlowGraph, key: string, policyKey: string): FlowGraph {
  return patchConfig(g, key, { deadlinePolicyKey: policyKey || undefined });
}


function patchTransition(
  g: FlowGraph,
  index: number,
  fn: (t: TransitionDef) => TransitionDef,
): FlowGraph {
  return {
    ...g,
    transitions: (g.transitions ?? []).map((t, idx) => (idx === index ? fn(t) : t)),
  };
}

export function addTransition(g: FlowGraph, t: TransitionDef): FlowGraph {
  return { ...g, transitions: [...(g.transitions ?? []), t] };
}

export function removeTransition(g: FlowGraph, index: number): FlowGraph {
  return { ...g, transitions: (g.transitions ?? []).filter((_, idx) => idx !== index) };
}

export function setTransitionEndpoint(
  g: FlowGraph,
  index: number,
  end: 'from' | 'to',
  key: string,
): FlowGraph {
  return patchTransition(g, index, (t) => ({ ...t, [end]: key }));
}

export function setTransitionLabel(
  g: FlowGraph,
  index: number,
  lang: 'de' | 'en',
  value: string,
): FlowGraph {
  return patchTransition(g, index, (t) => {
    const label = { ...(t.label ?? {}), [lang]: value };
    // Drop empty languages. No language left means no label.
    const cleaned = Object.fromEntries(Object.entries(label).filter(([, v]) => v));
    return { ...t, label: Object.keys(cleaned).length ? cleaned : null };
  });
}

export function setTransitionColor(g: FlowGraph, index: number, color: string): FlowGraph {
  return patchTransition(g, index, (t) => ({ ...t, color: color || null }));
}

export function setTransitionAutomatic(g: FlowGraph, index: number, on: boolean): FlowGraph {
  return patchTransition(g, index, (t) => ({ ...t, automatic: on }));
}

/** `requiresAction: true` is the default. The editor does not persist it. */
export function setTransitionRequiresAction(g: FlowGraph, index: number, on: boolean): FlowGraph {
  return patchTransition(g, index, (t) => {
    if (on) {
      const next = { ...t };
      delete next.requiresAction;
      return next;
    }
    return { ...t, requiresAction: false };
  });
}

export function setTransitionBranch(g: FlowGraph, index: number, branch: string): FlowGraph {
  return patchTransition(g, index, (t) => ({
    ...t,
    branch: (branch || null) as TransitionBranch | null,
  }));
}


export function setGuard(g: FlowGraph, index: number, guard: Guard | null): FlowGraph {
  return patchTransition(g, index, (t) => {
    if (!guard) {
      const next = { ...t };
      delete next.guard;
      return next;
    }
    return { ...t, guard };
  });
}

/** Choose an operator to seed the guard with a default. An empty operator drops the guard. */
export function setGuardOp(g: FlowGraph, index: number, op: string): FlowGraph {
  return patchTransition(g, index, (t) => {
    if (!op) {
      const next = { ...t };
      delete next.guard;
      return next;
    }
    return { ...t, guard: defaultGuard(op as GuardLeafOperator) };
  });
}

export function setGuardValue(g: FlowGraph, index: number, value: string): FlowGraph {
  return patchTransition(g, index, (t) => {
    const op = guardOpOf(t);
    return op ? { ...t, guard: { [op]: value } } : t;
  });
}

export function setGuardBool(g: FlowGraph, index: number, on: boolean): FlowGraph {
  return patchTransition(g, index, (t) => {
    const op = guardOpOf(t);
    return op ? { ...t, guard: { [op]: on } } : t;
  });
}

export function setCompare(
  g: FlowGraph,
  index: number,
  patch: { field?: string; op?: string; value?: string },
): FlowGraph {
  return patchTransition(g, index, (t) => {
    const cur = compareSpecOf(t);
    const op = patch.op ?? cur.op;
    let value: unknown = patch.value ?? cur.value;
    // The `in` operator expects a list. Split the comma-separated input.
    if (op === 'in' && typeof value === 'string') {
      value = value.split(',').map((s) => s.trim()).filter(Boolean);
    }
    return {
      ...t,
      guard: { compare: { field: patch.field ?? cur.field, op: op as CompareOp, value } },
    };
  });
}

/**
 * Move a guard group up or down in the priority stack. The function rewrites the
 * `order` fields so the array order equals the evaluation order. It keeps the branch
 * transitions of the node, because they are not part of the guard groups.
 */
export function reorderGuardGroup(
  g: FlowGraph,
  fromKey: string,
  sig: string,
  dir: -1 | 1,
): FlowGraph {
  const all = g.transitions ?? [];
  const groups = groupsOf(all, fromKey);
  const gi = groups.findIndex((x) => x.sig === sig);
  const ni = gi + dir;
  if (gi < 0 || ni < 0 || ni >= groups.length) return g;
  [groups[gi], groups[ni]] = [groups[ni], groups[gi]];
  const outgoing = groups.flatMap((grp) => grp.indices.map((i) => all[i]));
  const others = all.filter((t) => t.from !== fromKey || t.branch);
  const next = [...others, ...outgoing].map((t, i) => ({ ...t, order: i }));
  return { ...g, transitions: next };
}


export function addAction(g: FlowGraph, index: number, type: string): FlowGraph {
  const initial: ActionDef =
    type === 'notify'
      ? { type: 'notify', recipients: [] }
      : ({ type: type as ActionType } as ActionDef);
  return patchTransition(g, index, (t) => ({ ...t, actions: [...(t.actions ?? []), initial] }));
}

export function removeAction(g: FlowGraph, index: number, ai: number): FlowGraph {
  return patchTransition(g, index, (t) => ({
    ...t,
    actions: (t.actions ?? []).filter((_, k) => k !== ai),
  }));
}

export function setActionParam(
  g: FlowGraph,
  index: number,
  ai: number,
  key: string,
  value: string,
): FlowGraph {
  return patchTransition(g, index, (t) => ({
    ...t,
    actions: (t.actions ?? []).map((a, k) => (k === ai ? { ...a, [key]: value } : a)),
  }));
}

function patchRecipients(
  g: FlowGraph,
  index: number,
  ai: number,
  fn: (list: NotifyRecipient[]) => NotifyRecipient[],
): FlowGraph {
  return patchTransition(g, index, (t) => ({
    ...t,
    actions: (t.actions ?? []).map((a, k) =>
      k === ai ? { ...a, recipients: fn(recipientsOf(a)) } : a,
    ),
  }));
}

export function addRecipient(g: FlowGraph, index: number, ai: number): FlowGraph {
  return patchRecipients(g, index, ai, (list) => [...list, { kind: 'applicant' }]);
}

export function removeRecipient(g: FlowGraph, index: number, ai: number, ri: number): FlowGraph {
  return patchRecipients(g, index, ai, (list) => list.filter((_, i) => i !== ri));
}

export function setRecipientKind(
  g: FlowGraph,
  index: number,
  ai: number,
  ri: number,
  kind: string,
): FlowGraph {
  return patchRecipients(g, index, ai, (list) =>
    list.map((r, i) =>
      i === ri
        ? {
            kind: kind as NotifyRecipientKind,
            ref: kind === 'applicant' ? undefined : (r.ref ?? ''),
          }
        : r,
    ),
  );
}

export function setRecipientRef(
  g: FlowGraph,
  index: number,
  ai: number,
  ri: number,
  ref: string,
): FlowGraph {
  return patchRecipients(g, index, ai, (list) =>
    list.map((r, i) => (i === ri ? { ...r, ref } : r)),
  );
}


export function setStatePosition(g: FlowGraph, key: string, x: number, y: number): FlowGraph {
  return {
    ...g,
    layout: {
      ...(g.layout ?? {}),
      positions: { ...(g.layout?.positions ?? {}), [key]: { x, y } },
    },
  };
}

/** Shift several states at once for a group drag. Clamps to non-negative coordinates. */
export function moveStatesBy(g: FlowGraph, keys: string[], dx: number, dy: number): FlowGraph {
  const positions = { ...(g.layout?.positions ?? {}) };
  for (const k of keys) {
    const cur = positions[k];
    if (cur) {
      positions[k] = {
        x: Math.max(0, Math.round(cur.x + dx)),
        y: Math.max(0, Math.round(cur.y + dy)),
      };
    }
  }
  return { ...g, layout: { ...(g.layout ?? {}), positions } };
}

/**
 * Auto-arrange the given drill-down level. Each sub-group acts as one node. The
 * function shifts the members of a sub-group as a block.
 */
export function relayoutLevel(g: FlowGraph, ctx: string | null): FlowGraph {
  const allGroups = g.layout?.groups ?? [];
  const byId = buildGroupById(allGroups);
  const parents = buildParentGroupId(allGroups);
  const owner = buildStateOwnerId(allGroups);
  const visible = g.states.filter((s) => (owner.get(s.key) ?? null) === ctx);
  const childGroups = allGroups.filter((gr) => (parents.get(gr.id) ?? null) === ctx);
  const ends = computeEdgeEnds(g, ctx, owner, parents);
  const entId = (r: EndRef): string | null =>
    r.type === 'state' ? `s:${r.key}` : r.type === 'group' ? `g:${r.id}` : null;
  const initialKey = g.states.find((s) => s.isInitial)?.key;
  const entities = [
    ...visible.map((s) => ({ id: `s:${s.key}`, isInitial: !!s.isInitial })),
    ...childGroups.map((gr) => ({
      id: `g:${gr.id}`,
      isInitial: initialKey ? deepStateKeys(byId, gr.id).includes(initialKey) : false,
    })),
  ];
  const edges: Array<readonly [string, string]> = [];
  for (const e of ends) {
    if (!e) continue;
    const a = entId(e.src);
    const b = entId(e.dst);
    if (a && b && a !== b) edges.push([a, b] as const);
  }
  const target = layoutEntities(entities, edges);
  const positions: Record<string, Point> = { ...(g.layout?.positions ?? {}) };
  for (const s of visible) {
    const p = target[`s:${s.key}`];
    if (p) positions[s.key] = p;
  }
  // Group as a block: shift the member bbox top-left onto the target position.
  for (const grp of childGroups) {
    const p = target[`g:${grp.id}`];
    if (!p) continue;
    const deep = deepStateKeys(byId, grp.id);
    const pts = deep.map((k) => positions[k]).filter((q): q is Point => !!q);
    if (!pts.length) continue;
    const dx = p.x - Math.min(...pts.map((q) => q.x));
    const dy = p.y - Math.min(...pts.map((q) => q.y));
    for (const k of deep) {
      const cur = positions[k];
      if (cur) positions[k] = { x: cur.x + dx, y: cur.y + dy };
    }
  }
  return { ...g, layout: { ...(g.layout ?? {}), positions } };
}


/** First free `grpN` id. */
export function freshGroupId(groups: readonly FlowGroup[]): { id: string; n: number } {
  const used = new Set(groups.map((g) => g.id));
  let n = groups.length + 1;
  while (used.has(`grp${n}`)) n++;
  return { id: `grp${n}`, n };
}

/**
 * Create a group from the selected states and groups. The members leave their previous
 * group. Inside an open group the new group becomes a sub-group.
 */
export function createGroup(
  g: FlowGraph,
  id: string,
  name: string,
  stateKeys: string[],
  groupIds: string[],
  ctx: string | null,
): FlowGraph {
  const selStates = new Set(stateKeys);
  const selGroups = new Set(groupIds);
  let groups: FlowGroup[] = (g.layout?.groups ?? []).map((gr) => ({
    ...gr,
    stateKeys: gr.stateKeys.filter((k) => !selStates.has(k)),
    groupIds: (gr.groupIds ?? []).filter((cid) => !selGroups.has(cid)),
  }));
  const created: FlowGroup = { id, name, stateKeys };
  if (groupIds.length) created.groupIds = groupIds;
  groups.push(created);
  if (ctx) {
    groups = groups.map((gr) =>
      gr.id === ctx ? { ...gr, groupIds: [...(gr.groupIds ?? []), id] } : gr,
    );
  }
  groups = groups.filter((gr) => gr.stateKeys.length > 0 || (gr.groupIds ?? []).length > 0);
  return { ...g, layout: { ...(g.layout ?? {}), groups } };
}

function patchGroup(g: FlowGraph, id: string, fn: (gr: FlowGroup) => FlowGroup): FlowGraph {
  return {
    ...g,
    layout: {
      ...(g.layout ?? {}),
      groups: (g.layout?.groups ?? []).map((gr) => (gr.id === id ? fn(gr) : gr)),
    },
  };
}

export function renameGroup(g: FlowGraph, id: string, name: string): FlowGraph {
  return patchGroup(g, id, (gr) => ({ ...gr, name }));
}

export function setGroupColor(g: FlowGraph, id: string, color: string): FlowGraph {
  return patchGroup(g, id, (gr) => ({ ...gr, color: color || null }));
}

/** Dissolve a group: its content moves one level up (parent or top level). */
export function dissolveGroup(g: FlowGraph, id: string, parent: string | null): FlowGraph {
  const all = g.layout?.groups ?? [];
  const me = all.find((gr) => gr.id === id);
  if (!me) return g;
  let groups = all.filter((gr) => gr.id !== id);
  if (parent) {
    groups = groups.map((gr) =>
      gr.id === parent
        ? {
            ...gr,
            stateKeys: [...gr.stateKeys, ...me.stateKeys],
            groupIds: [...(gr.groupIds ?? []).filter((cid) => cid !== id), ...(me.groupIds ?? [])],
          }
        : gr,
    );
  }
  const layout = { ...(g.layout ?? {}) };
  if (groups.length) layout.groups = groups;
  else delete layout.groups;
  return { ...g, layout };
}
