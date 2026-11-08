/**
 * Pure flow-graph mutations. Every function returns a new graph and never mutates the
 * input. Signal consumers and the undo history therefore see distinct snapshots.
 */
import type { I18nMap } from '@core/api/models';
import { withoutKey } from '@shared/util/immutable';
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
import { autoLayout, blankState } from '../flow-graph.util';
import {
  compareSpecOf,
  defaultGuard,
  groupsOf,
  guardOpOf,
  recipientNeedsRef,
  recipientsOf,
} from './flow-guard.util';


/** Unique state key (`state`, `state2`, …). */
export function uniqueStateKey(base: string, states: readonly StateDef[]): string {
  const used = new Set(states.map((s) => s.key));
  const free = (i: number): string => (used.has(`${base}${i}`) ? free(i + 1) : `${base}${i}`);
  return used.has(base) ? free(2) : base;
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
  const positions = withoutKey(g.layout?.positions ?? {}, key);
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
  const old = g.layout?.positions ?? {};
  const positions =
    old[oldKey] && key && key !== oldKey
      ? { ...withoutKey(old, oldKey), [key]: old[oldKey] }
      : { ...old };
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

export function setStateLabel(g: FlowGraph, key: string, label: I18nMap): FlowGraph {
  return patchState(g, key, { label });
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

/** Change the state kind. This resets the kind-specific config. */
export function setStateKind(g: FlowGraph, key: string, kind: string): FlowGraph {
  const k = (kind || 'normal') as StateKind;
  return patchState(g, key, { kind: k === 'normal' ? null : k, config: {} });
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

/**
 * Switch the gremium source of a vote state. `budget` takes the deciding gremium of the
 * cost center on entry and drops a fixed `gremiumId`; `fixed` drops the source. The
 * backend accepts exactly one of the two keys.
 */
export function setStateGremiumSource(
  g: FlowGraph,
  key: string,
  source: 'fixed' | 'budget',
): FlowGraph {
  return {
    ...g,
    states: g.states.map((s) => {
      if (s.key !== key) return s;
      const gremiumId = s.config?.gremiumId;
      const rest: StateConfig = withoutKey(
        withoutKey(s.config ?? {}, 'gremiumId'),
        'gremiumSource',
      );
      const config: StateConfig =
        source === 'budget'
          ? { ...rest, gremiumSource: 'budget' }
          : { ...rest, ...(gremiumId ? { gremiumId } : {}) };
      return { ...s, config };
    }),
  };
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

export function addTransition(
  g: FlowGraph,
  t: TransitionDef,
): FlowGraph & { transitions: TransitionDef[] } {
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

/** An empty text removes its language, and a label without text is `null`. */
export function setTransitionLabel(g: FlowGraph, index: number, label: I18nMap): FlowGraph {
  return patchTransition(g, index, (t) => {
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
  return patchTransition(g, index, (t) =>
    on ? withoutKey(t, 'requiresAction') : { ...t, requiresAction: false },
  );
}

export function setTransitionBranch(g: FlowGraph, index: number, branch: string): FlowGraph {
  return patchTransition(g, index, (t) => ({
    ...t,
    branch: (branch || null) as TransitionBranch | null,
  }));
}


export function setGuard(g: FlowGraph, index: number, guard: Guard | null): FlowGraph {
  return patchTransition(g, index, (t) => (guard ? { ...t, guard } : withoutKey(t, 'guard')));
}

/** Choose an operator to seed the guard with a default. An empty operator drops the guard. */
export function setGuardOp(g: FlowGraph, index: number, op: string): FlowGraph {
  return patchTransition(g, index, (t) =>
    op ? { ...t, guard: defaultGuard(op as GuardLeafOperator) } : withoutKey(t, 'guard'),
  );
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
  patch: { readonly field?: string; readonly op?: string; readonly value?: string },
): FlowGraph {
  return patchTransition(g, index, (t) => {
    const cur = compareSpecOf(t);
    const op = patch.op ?? cur.op;
    const raw: unknown = patch.value ?? cur.value;
    const value =
      op === 'in' && typeof raw === 'string'
        ? raw.split(',').map((s) => s.trim()).filter(Boolean)
        : raw;
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
  const swapped = groups.map((grp, i) => (i === gi ? groups[ni] : i === ni ? groups[gi] : grp));
  const outgoing = swapped.flatMap((grp) => grp.indices.map((i) => all[i]));
  const others = all.filter((t) => t.from !== fromKey || t.branch);
  const next = [...others, ...outgoing].map((t, i) => ({ ...t, order: i }));
  return { ...g, transitions: next };
}


export function addAction(g: FlowGraph, index: number, type: string): FlowGraph {
  const initial: ActionDef =
    type === 'notify'
      ? { type: 'notify', recipients: [] }
      : type === 'assignBudgetFromMap'
        ? { type: 'assignBudgetFromMap', field: '', map: {} }
        : ({ type: type as ActionType } as ActionDef);
  return patchTransition(g, index, (t) => ({ ...t, actions: [...(t.actions ?? []), initial] }));
}

export function removeAction(g: FlowGraph, index: number, ai: number): FlowGraph {
  return patchTransition(g, index, (t) => ({
    ...t,
    actions: (t.actions ?? []).filter((_, k) => k !== ai),
  }));
}

/**
 * An empty value drops the key, so an optional parameter (`gremiumId` of addToNextSession,
 * `parentId`) is absent, as the backend expects.
 */
export function setActionParam(
  g: FlowGraph,
  index: number,
  ai: number,
  key: string,
  value: string,
): FlowGraph {
  return patchTransition(g, index, (t) => ({
    ...t,
    actions: (t.actions ?? []).map((a, k) => {
      if (k !== ai) return a;
      return value
        ? { ...a, [key]: value }
        : (Object.fromEntries(Object.entries(a).filter(([k2]) => k2 !== key)) as ActionDef);
    }),
  }));
}

/** Replace the value → cost center map of an `assignBudgetFromMap` action. */
export function setActionMap(
  g: FlowGraph,
  index: number,
  ai: number,
  map: Record<string, string>,
): FlowGraph {
  return patchTransition(g, index, (t) => ({
    ...t,
    actions: (t.actions ?? []).map((a, k) => (k === ai ? { ...a, map: { ...map } } : a)),
  }));
}

function patchRecipients(
  g: FlowGraph,
  index: number,
  ai: number,
  fn: (list: readonly NotifyRecipient[]) => readonly NotifyRecipient[],
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
            ref: recipientNeedsRef(kind) ? (r.ref ?? '') : undefined,
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

/** First free `grpN` id. */
export function freshGroupId(groups: readonly FlowGroup[]): {
  readonly id: string;
  readonly n: number;
} {
  const used = new Set(groups.map((g) => g.id));
  const firstFree = (n: number): number => (used.has(`grp${n}`) ? firstFree(n + 1) : n);
  const n = firstFree(groups.length + 1);
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
  stateKeys: readonly string[],
  groupIds: readonly string[],
  ctx: string | null,
): FlowGraph {
  const selStates = new Set(stateKeys);
  const selGroups = new Set(groupIds);
  const left: readonly FlowGroup[] = (g.layout?.groups ?? []).map((gr) => ({
    ...gr,
    stateKeys: gr.stateKeys.filter((k) => !selStates.has(k)),
    groupIds: (gr.groupIds ?? []).filter((cid) => !selGroups.has(cid)),
  }));
  const created: FlowGroup = { id, name, stateKeys, ...(groupIds.length ? { groupIds } : {}) };
  const placed = [...left, created].map((gr) =>
    ctx && gr.id === ctx ? { ...gr, groupIds: [...(gr.groupIds ?? []), id] } : gr,
  );
  const groups = placed.filter((gr) => gr.stateKeys.length > 0 || (gr.groupIds ?? []).length > 0);
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
  const rest = all.filter((gr) => gr.id !== id);
  const groups = parent
    ? rest.map((gr) =>
        gr.id === parent
          ? {
              ...gr,
              stateKeys: [...gr.stateKeys, ...me.stateKeys],
              groupIds: [
                ...(gr.groupIds ?? []).filter((cid) => cid !== id),
                ...(me.groupIds ?? []),
              ],
            }
          : gr,
      )
    : rest;
  const layout = groups.length
    ? { ...(g.layout ?? {}), groups }
    : withoutKey(g.layout ?? {}, 'groups');
  return { ...g, layout };
}
