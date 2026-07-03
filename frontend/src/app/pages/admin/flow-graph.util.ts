/**
 * Flow-graph helpers (flow editor). Client validation + graph↔JSON + auto-layout.
 * Validation mirrors `app/shared/config_schemas.py` (`validate_flow_graph`): ≥1 state,
 * exactly one initial, no duplicate keys, no dangling `from`/`to`, all states reachable
 * from the initial, guards/actions only from the whitelist. The server re-validates
 * authoritatively on save — this is purely instant feedback in the UI.
 */
import {
  type FlowGraph,
  type FlowGroup,
  type StateDef,
  type TransitionDef,
} from './admin.models';
import { validateAction, validateGuard } from './guard-builder.util';

/** Field/state keys: `^[a-z][a-z0-9_]*$` (config_schemas KEY_PATTERN). */
export const KEY_PATTERN = /^[a-z][a-z0-9_]*$/;

export interface FlowValidationResult {
  valid: boolean;
  errors: string[];
}

export function validateFlowGraph(graph: FlowGraph): FlowValidationResult {
  const errors: string[] = [];
  const states = graph.states ?? [];

  if (states.length === 0) {
    errors.push('flow graph has no states');
    return { valid: false, errors };
  }

  const keys = states.map((s) => s.key);
  const duplicates = [...new Set(keys.filter((k) => keys.indexOf(k) !== keys.lastIndexOf(k)))];
  if (duplicates.length > 0) {
    errors.push(`duplicate state keys: ${duplicates.sort().join(', ')}`);
  }
  for (const s of states) {
    if (!KEY_PATTERN.test(s.key)) {
      errors.push(`invalid state key: ${JSON.stringify(s.key)}`);
    }
  }
  const keySet = new Set(keys);

  const initials = states.filter((s) => s.isInitial).map((s) => s.key);
  if (initials.length === 0) {
    errors.push('flow graph has no initial state');
  } else if (initials.length > 1) {
    errors.push(`flow graph has multiple initial states: ${initials.join(', ')}`);
  }

  const transitions = graph.transitions ?? [];
  for (const t of transitions) {
    if (!keySet.has(t.from)) {
      errors.push(`transition references unknown from-state: ${JSON.stringify(t.from)}`);
    }
    if (!keySet.has(t.to)) {
      errors.push(`transition references unknown to-state: ${JSON.stringify(t.to)}`);
    }
    try {
      // Actor gates (roleIs/isInCommittee) only on manual transitions.
      validateGuard(t.guard, !t.automatic);
      for (const a of t.actions ?? []) {
        validateAction(a);
        // `addToNextSession` may only lead into a vote state.
        if (a.type === 'addToNextSession') {
          const target = states.find((s) => s.key === t.to);
          if ((target?.kind ?? 'normal') !== 'vote') {
            errors.push(
              `addToNextSession action on "${t.from}→${t.to}" must lead into a vote state`,
            );
          }
        }
      }
    } catch (err) {
      errors.push((err as Error).message);
    }
  }

  if (initials.length === 1 && duplicates.length === 0) {
    const unreachable = findUnreachable(initials[0], keySet, transitions);
    if (unreachable.length > 0) {
      errors.push(`unreachable states: ${unreachable.sort().join(', ')}`);
    }
  }

  // State-kind rules — mirror `_validate_state_kinds` (BE), so the user sees the error
  // immediately (instead of only on save as a 422).
  for (const s of states) {
    if (!s.kind || s.kind === 'normal') continue;
    const outBranches = transitions
      .filter((t) => t.from === s.key && t.branch)
      .map((t) => t.branch as string)
      .sort();
    if (s.kind === 'vote') {
      if (!s.config?.gremiumId) errors.push(`vote state "${s.key}" needs a committee (config.gremiumId)`);
      if (outBranches.join(',') !== 'fail,pass') {
        errors.push(`vote state "${s.key}" needs exactly two outgoing transitions: branch "pass" and "fail"`);
      }
      // A vote state is decided only by the vote (or a manual abort): an automatic
      // exit would fire immediately, before any vote happened — mirrors the BE validator.
      if (transitions.some((t) => t.from === s.key && t.automatic && !t.branch)) {
        errors.push(
          `vote state "${s.key}" must not have automatic outgoing transitions — only the vote outcome (pass/fail) or a manual exit may leave it`,
        );
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

// --- Graph ↔ JSON (Round-Trip) ----------------------------------------------

/**
 * Bring the graph into canonical wire form (exactly the schema fields, empty optionals
 * omitted) — what gets stored as a flow version. Stable:
 * `normalize(parse(serialize(g))) === normalize(g)` (round-trip guarantee).
 */
export function normalizeFlowGraph(graph: FlowGraph): FlowGraph {
  const states: StateDef[] = graph.states.map((s) => {
    const out: StateDef = { key: s.key, label: s.label };
    if (s.color) out.color = s.color;
    if (s.editAllowed === false) out.editAllowed = false;
    if (s.isInitial) out.isInitial = true;
    if (s.isTerminal) out.isTerminal = true;
    // State kind + config — `normal` is the default and is omitted.
    if (s.kind && s.kind !== 'normal') out.kind = s.kind;
    if (s.config && Object.keys(s.config).length > 0) out.config = s.config;
    return out;
  });
  const transitions: TransitionDef[] = (graph.transitions ?? []).map((t) => {
    const out: TransitionDef = { from: t.from, to: t.to };
    if (t.label) out.label = t.label;
    if (t.color) out.color = t.color; // keep the arrow/button color
    if (t.guard) out.guard = t.guard;
    if (t.actions && t.actions.length > 0) out.actions = t.actions;
    if (t.order != null) out.order = t.order;
    if (t.automatic) out.automatic = true;
    if (t.branch) out.branch = t.branch; // result branch
    // Default `true` is omitted — persist only the explicit opt-out.
    if (t.requiresAction === false) out.requiresAction = false;
    return out;
  });
  const out: FlowGraph = { states, transitions };
  const keySet2 = new Set(states.map((s) => s.key));
  const positions = graph.layout?.positions ?? {};
  const layout: { positions?: Record<string, { x: number; y: number }>; groups?: FlowGroup[] } = {};
  if (Object.keys(positions).length > 0) layout.positions = { ...positions };
  // Groups: reference only existing states/groups; a group with no states AND no
  // sub-groups disappears. Legacy `collapsed` is normalized away (content opens via
  // drill-down today).
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

// --- Auto-layout (Sugiyama-light: layers + barycenter + centering) ----------

const COL_GAP = 240;
const ROW_GAP = 130;
/** Left/top padding so nodes don't stick to the canvas edge. */
const PAD = 40;

/**
 * Fill in missing node positions (already-set ones are kept — editor drag persists).
 * Layout algorithm:
 *
 * 1. Layer = longest path from the initial state (not BFS): nodes shift as far right as
 *    needed — edges point mostly forward, back-edges stay the exception rather than
 *    layout chaos.
 * 2. Barycenter ordering per layer (3 forward/backward sweeps): nodes line up next to
 *    their neighbors → far fewer crossings.
 * 3. Vertical centering: small layers centered against the tallest layer instead of all
 *    stuck to the top.
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
    if (t.from === t.to) continue; // self-loops are layout-neutral
    if (keySet.has(t.from) && keySet.has(t.to)) {
      out.get(t.from)!.push(t.to);
      incoming.get(t.to)!.push(t.from);
    }
  }

  // 1. Layers: longest path from the initial (Bellman-style relaxation, terminating
  //    even with cycles thanks to the iteration bound).
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

  // 3. Positions: column = layer, row = order; layer vertically centered.
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
 * Condensed auto-layout: arrange arbitrary entities (visible states + group boxes of one
 * drill-down level) as nodes of a virtual graph — a group behaves like ONE node during
 * auto-arrange. Returns fresh positions per entity id (existing ones are ignored).
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

// --- Factories --------------------------------------------------------------

export function emptyFlowGraph(): FlowGraph {
  return { states: [], transitions: [] };
}

export function blankState(key = '', isInitial = false): StateDef {
  return { key, label: { de: '', en: '' }, isInitial, editAllowed: true };
}

export function blankTransition(from = '', to = ''): TransitionDef {
  return { from, to, actions: [] };
}
