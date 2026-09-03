/**
 * Flow-graph helpers for the flow editor: client validation, graph to JSON, and
 * auto-layout.
 *
 * Validation mirrors `app/shared/config_schemas.py` (`validate_flow_graph`). It asks for at
 * least one state, exactly one initial state, no duplicate keys, and no dangling `from` or
 * `to`. All states must be reachable from the initial state. Guards and actions must come
 * from the whitelist. The server validates again on save and stays authoritative. This
 * check only gives the user instant feedback.
 */
import { type TranslationKey } from '../../core/i18n/translations';
import { type FlowGraph, type FlowGroup, type StateDef, type TransitionDef } from './admin.models';
import { type GuardError, validateAction, validateGuard } from './guard-builder.util';

/** Keys of a field or a state. Mirrors `KEY_PATTERN` in `config_schemas`. */
export const KEY_PATTERN = /^[a-z][a-z0-9_]*$/;

/**
 * One rejected thing, named by a translation key rather than by a sentence.
 *
 * An admin reads these in the flow editor, so the caller picks the language.
 */
export interface FlowValidationError {
  readonly key: TranslationKey;
  readonly params?: Record<string, string | number>;
}

export interface FlowValidationResult {
  valid: boolean;
  errors: FlowValidationError[];
}

export function validateFlowGraph(graph: FlowGraph): FlowValidationResult {
  const errors: FlowValidationError[] = [];
  const states = graph.states ?? [];

  if (states.length === 0) {
    errors.push({ key: 'admin.flow.err.noStates' });
    return { valid: false, errors };
  }

  const keys = states.map((s) => s.key);
  const duplicates = [...new Set(keys.filter((k) => keys.indexOf(k) !== keys.lastIndexOf(k)))];
  if (duplicates.length > 0) {
    errors.push({
      key: 'admin.flow.err.duplicateKeys',
      params: { keys: duplicates.sort().join(', ') },
    });
  }
  for (const s of states) {
    if (!KEY_PATTERN.test(s.key)) {
      errors.push({ key: 'admin.flow.err.invalidKey', params: { key: String(s.key) } });
    }
  }
  const keySet = new Set(keys);

  const initials = states.filter((s) => s.isInitial).map((s) => s.key);
  if (initials.length === 0) {
    errors.push({ key: 'admin.flow.err.noInitial' });
  } else if (initials.length > 1) {
    errors.push({ key: 'admin.flow.err.multipleInitial', params: { keys: initials.join(', ') } });
  }

  const transitions = graph.transitions ?? [];
  for (const t of transitions) {
    if (!keySet.has(t.from)) {
      errors.push({ key: 'admin.flow.err.unknownFrom', params: { key: String(t.from) } });
    }
    if (!keySet.has(t.to)) {
      errors.push({ key: 'admin.flow.err.unknownTo', params: { key: String(t.to) } });
    }
    try {
      // Actor gates (roleIs/isInCommittee) apply to manual transitions only.
      validateGuard(t.guard, !t.automatic);
      for (const a of t.actions ?? []) {
        validateAction(a);
        if (a.type === 'addToNextSession') {
          const target = states.find((s) => s.key === t.to);
          if ((target?.kind ?? 'normal') !== 'vote') {
            errors.push({
              key: 'admin.flow.err.sessionNeedsVote',
              params: { from: String(t.from), to: String(t.to) },
            });
          }
        }
      }
    } catch (err) {
      const gerr = err as GuardError;
      errors.push({ key: gerr.key, params: gerr.params });
    }
  }

  if (initials.length === 1 && duplicates.length === 0) {
    const unreachable = findUnreachable(initials[0], keySet, transitions);
    if (unreachable.length > 0) {
      errors.push({
        key: 'admin.flow.err.unreachable',
        params: { keys: unreachable.sort().join(', ') },
      });
    }
  }

  // State-kind rules mirror `_validate_state_kinds` in the backend. The user sees the
  // error at once, and not only on save as a 422.
  for (const s of states) {
    if (!s.kind || s.kind === 'normal') continue;
    const outBranches = transitions
      .filter((t) => t.from === s.key && t.branch)
      .map((t) => t.branch as string)
      .sort();
    if (s.kind === 'vote') {
      if (!s.config?.gremiumId) {
        errors.push({ key: 'admin.flow.err.voteNeedsGremium', params: { key: s.key } });
      }
      if (outBranches.join(',') !== 'fail,pass') {
        errors.push({ key: 'admin.flow.err.voteBranches', params: { key: s.key } });
      }
      // Only the vote or a manual abort decides a vote state. An automatic exit would
      // fire at once, before a vote happened. This mirrors the backend validator.
      if (transitions.some((t) => t.from === s.key && t.automatic && !t.branch)) {
        errors.push({ key: 'admin.flow.err.voteNoAutomatic', params: { key: s.key } });
      }
    }
  }

  return { valid: errors.length === 0, errors };
}

function findUnreachable(
  initial: string,
  keySet: Set<string>,
  transitions: TransitionDef[],
): string[] {
  const adjacency = new Map<string, string[]>();
  for (const k of keySet) adjacency.set(k, []);
  for (const t of transitions) {
    if (keySet.has(t.from) && keySet.has(t.to)) adjacency.get(t.from)!.push(t.to);
  }
  const seen = new Set<string>();
  const queue = [initial];
  while (queue.length > 0) {
    const node = queue.shift()!;
    if (seen.has(node)) continue;
    seen.add(node);
    queue.push(...(adjacency.get(node) ?? []));
  }
  return [...keySet].filter((k) => !seen.has(k));
}

/**
 * Bring the graph into canonical wire form: exactly the schema fields, with empty
 * optionals dropped. A flow version stores this form. The round-trip guarantee holds:
 * `normalize(parse(serialize(g))) === normalize(g)`.
 */
export function normalizeFlowGraph(graph: FlowGraph): FlowGraph {
  const states: StateDef[] = graph.states.map((s) => {
    const out: StateDef = { key: s.key, label: s.label };
    if (s.color) out.color = s.color;
    if (s.editAllowed === false) out.editAllowed = false;
    if (s.isInitial) out.isInitial = true;
    if (s.isTerminal) out.isTerminal = true;
    // `normal` is the default kind and stays out of the wire form.
    if (s.kind && s.kind !== 'normal') out.kind = s.kind;
    if (s.config && Object.keys(s.config).length > 0) out.config = s.config;
    return out;
  });
  const transitions: TransitionDef[] = (graph.transitions ?? []).map((t) => {
    const out: TransitionDef = { from: t.from, to: t.to };
    if (t.label) out.label = t.label;
    if (t.color) out.color = t.color;
    if (t.guard) out.guard = t.guard;
    if (t.actions && t.actions.length > 0) out.actions = t.actions;
    if (t.order != null) out.order = t.order;
    if (t.automatic) out.automatic = true;
    if (t.branch) out.branch = t.branch;
    // The default `true` stays out. Persist the explicit opt-out only.
    if (t.requiresAction === false) out.requiresAction = false;
    return out;
  });
  const out: FlowGraph = { states, transitions };
  const keySet2 = new Set(states.map((s) => s.key));
  const positions = graph.layout?.positions ?? {};
  const layout: { positions?: Record<string, { x: number; y: number }>; groups?: FlowGroup[] } = {};
  if (Object.keys(positions).length > 0) layout.positions = { ...positions };
  // Groups reference existing states and groups only. A group with no states and no
  // sub-groups disappears. Drop the legacy `collapsed` flag, because content opens
  // through drill-down today.
  const allGroupIds = new Set((graph.layout?.groups ?? []).map((g) => g.id));
  const groups = (graph.layout?.groups ?? [])
    .map((g) => ({
      ...g,
      stateKeys: g.stateKeys.filter((k) => keySet2.has(k)),
      groupIds: (g.groupIds ?? []).filter((id) => id !== g.id && allGroupIds.has(id)),
    }))
    .filter((g) => g.stateKeys.length > 0 || g.groupIds.length > 0)
    .map((g) => {
      const out2: FlowGroup = { id: g.id, name: g.name, stateKeys: g.stateKeys };
      if (g.groupIds.length) out2.groupIds = g.groupIds;
      if (g.color) out2.color = g.color;
      return out2;
    });
  if (groups.length > 0) layout.groups = groups;
  if (layout.positions || layout.groups) out.layout = layout;
  return out;
}

export function serializeFlowGraph(graph: FlowGraph): string {
  return JSON.stringify(normalizeFlowGraph(graph), null, 2);
}

export function parseFlowGraph(json: string): FlowGraph {
  const parsed = JSON.parse(json) as FlowGraph;
  return normalizeFlowGraph(parsed);
}

// Auto-layout: Sugiyama-light with layers, barycenter, and centering.

const COL_GAP = 240;
const ROW_GAP = 130;
/** Left and top padding that keeps nodes off the canvas edge. */
const PAD = 40;

/**
 * Fill in missing node positions. A position that is already set stays, because an editor
 * drag persists.
 *
 * Layout algorithm:
 *
 * 1. Layer = longest path from the initial state, and not BFS. Nodes move as far right as
 *    needed. Edges then point mostly forward, and back-edges stay the exception.
 * 2. Barycenter ordering per layer, with 3 forward and backward sweeps. Nodes line up next
 *    to their neighbors, which gives far fewer crossings.
 * 3. Vertical centering. A small layer centers against the tallest layer instead of
 *    sticking to the top.
 */
export function autoLayout(graph: FlowGraph): FlowGraph {
  const existing: Record<string, { x: number; y: number }> = {
    ...(graph.layout?.positions ?? {}),
  };
  const keys = graph.states.map((s) => s.key);
  const keySet = new Set(keys);
  const out = new Map<string, string[]>();
  const incoming = new Map<string, string[]>();
  for (const k of keySet) {
    out.set(k, []);
    incoming.set(k, []);
  }
  for (const t of graph.transitions ?? []) {
    if (t.from === t.to) continue; // a self-loop does not change the layout
    if (keySet.has(t.from) && keySet.has(t.to)) {
      out.get(t.from)!.push(t.to);
      incoming.get(t.to)!.push(t.from);
    }
  }

  // 1. Layers: longest path from the initial state. The Bellman-style relaxation stops
  //    even with cycles, because the iteration bound limits it.
  const initial = graph.states.find((s) => s.isInitial)?.key ?? keys[0];
  const depth = new Map<string, number>();
  if (initial) depth.set(initial, 0);
  for (let i = 0; i < keys.length; i += 1) {
    let changed = false;
    for (const [from, targets] of out) {
      const d = depth.get(from);
      if (d === undefined) continue;
      for (const to of targets) {
        const candidate = d + 1;
        if (candidate > (depth.get(to) ?? -1) && candidate <= keys.length) {
          depth.set(to, candidate);
          changed = true;
        }
      }
    }
    if (!changed) break;
  }
  // Place unreachable states behind the deepest layer.
  let maxDepth = 0;
  for (const d of depth.values()) maxDepth = Math.max(maxDepth, d);
  for (const k of keys) {
    if (!depth.has(k)) depth.set(k, maxDepth + 1);
  }

  // 2. Layer lists (initial order = state order) + barycenter.
  const layers = new Map<number, string[]>();
  for (const k of keys) {
    const d = depth.get(k)!;
    if (!layers.has(d)) layers.set(d, []);
    layers.get(d)!.push(k);
  }
  const layerDepths = [...layers.keys()].sort((a, b) => a - b);
  const indexIn = (layer: string[], k: string): number => layer.indexOf(k);
  const sortByBarycenter = (layer: string[], neighborsOf: (k: string) => string[]): void => {
    const neighborLayerIndex = new Map<string, number>();
    for (const k of layer) {
      const ns = neighborsOf(k)
        .map((n) => {
          const d = depth.get(n)!;
          return indexIn(layers.get(d)!, n);
        })
        .filter((i) => i >= 0);
      neighborLayerIndex.set(
        k,
        ns.length > 0 ? ns.reduce((a, b) => a + b, 0) / ns.length : indexIn(layer, k),
      );
    }
    layer.sort((a, b) => neighborLayerIndex.get(a)! - neighborLayerIndex.get(b)!);
  };
  for (let sweep = 0; sweep < 3; sweep += 1) {
    for (const d of layerDepths) {
      sortByBarycenter(layers.get(d)!, (k) => incoming.get(k) ?? []);
    }
    for (const d of [...layerDepths].reverse()) {
      sortByBarycenter(layers.get(d)!, (k) => out.get(k) ?? []);
    }
  }

  // 3. Positions: column = layer, row = order. Center each layer vertically.
  const tallest = Math.max(...layerDepths.map((d) => layers.get(d)!.length), 1);
  const computed: Record<string, { x: number; y: number }> = {};
  for (const d of layerDepths) {
    const layer = layers.get(d)!;
    const offset = ((tallest - layer.length) * ROW_GAP) / 2;
    layer.forEach((k, row) => {
      computed[k] = { x: PAD + d * COL_GAP, y: PAD + offset + row * ROW_GAP };
    });
  }
  return {
    ...graph,
    layout: { ...(graph.layout ?? {}), positions: { ...computed, ...existing } },
  };
}

/**
 * Condensed auto-layout for one drill-down level. It treats arbitrary entities, that is
 * the visible states and the group boxes, as nodes of a virtual graph. A group behaves
 * like ONE node during auto-arrange. The function returns fresh positions per entity id
 * and ignores existing positions.
 */
export function layoutEntities(
  entities: ReadonlyArray<{ id: string; isInitial?: boolean }>,
  edges: ReadonlyArray<readonly [string, string]>,
): Record<string, { x: number; y: number }> {
  const fake: FlowGraph = {
    states: entities.map((e) => ({ key: e.id, label: {}, isInitial: !!e.isInitial })),
    transitions: edges.map(([from, to]) => ({ from, to })),
    layout: null,
  };
  return autoLayout(fake).layout?.positions ?? {};
}

export function emptyFlowGraph(): FlowGraph {
  return { states: [], transitions: [] };
}

export function blankState(key = '', isInitial = false): StateDef {
  return { key, label: { de: '', en: '' }, isInitial, editAllowed: true };
}

export function blankTransition(from = '', to = ''): TransitionDef {
  return { from, to, actions: [] };
}
