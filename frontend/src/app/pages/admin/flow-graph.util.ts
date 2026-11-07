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
import {
  ASSIGN_BUDGET_ACTIONS,
  type ActionDef,
  type FlowGraph,
  type FlowGroup,
  type FlowLayout,
  type StateConfig,
  type StateDef,
  type TransitionDef,
} from './admin.models';
import { withEntry } from '@shared/util/immutable';
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
  readonly valid: boolean;
  readonly errors: readonly FlowValidationError[];
}

/**
 * A vote state with `gremiumSource: 'budget'` takes its gremium on entry, before the action runs,
 * so a cost-center action on the way in comes too late, and a fixed agenda gremium could name
 * another one. State-kind rules mirror `_validate_state_kinds` and `_validate_vote_gremium` in the
 * backend, so the user sees the error at once and not only as a 422 on save. Only the vote or a
 * manual abort decides a vote state, because an automatic exit would fire at once, before a vote
 * happened. This mirrors the backend validator.
 */
export function validateFlowGraph(graph: FlowGraph): FlowValidationResult {
  const states = graph.states ?? [];
  if (states.length === 0) return { valid: false, errors: [{ key: 'admin.flow.err.noStates' }] };
  const transitions = graph.transitions ?? [];
  const keys = states.map((s) => s.key);
  const keySet = new Set(keys);
  const duplicates = [...new Set(keys.filter((k) => keys.indexOf(k) !== keys.lastIndexOf(k)))];
  const initials = states.filter((s) => s.isInitial).map((s) => s.key);
  const errors: readonly FlowValidationError[] = [
    ...(duplicates.length > 0
      ? [{ key: 'admin.flow.err.duplicateKeys' as const, params: { keys: sortedList(duplicates) } }]
      : []),
    ...states
      .filter((s) => !KEY_PATTERN.test(s.key))
      .map((s) => ({ key: 'admin.flow.err.invalidKey' as const, params: { key: String(s.key) } })),
    ...initialErrors(initials),
    ...transitions.flatMap((t) => transitionErrors(t, states, keySet)),
    ...(initials.length === 1 && duplicates.length === 0
      ? unreachableErrors(findUnreachable(initials[0], keySet, transitions))
      : []),
    ...states.flatMap((s) => voteStateErrors(s, transitions)),
  ];
  return { valid: errors.length === 0, errors };
}

/** The keys sorted and joined for an error parameter. */
function sortedList(keys: readonly string[]): string {
  return [...keys].sort().join(', ');
}

/** The error of a flow without an initial state or with more than one. */
function initialErrors(initials: readonly string[]): readonly FlowValidationError[] {
  if (initials.length === 0) return [{ key: 'admin.flow.err.noInitial' }];
  return initials.length > 1
    ? [{ key: 'admin.flow.err.multipleInitial', params: { keys: initials.join(', ') } }]
    : [];
}

/** The error that names the unreachable states, if there are any. */
function unreachableErrors(unreachable: readonly string[]): readonly FlowValidationError[] {
  return unreachable.length > 0
    ? [{ key: 'admin.flow.err.unreachable', params: { keys: sortedList(unreachable) } }]
    : [];
}

/** The error that `check` throws, or null when it passes. */
function thrownError(check: () => void): FlowValidationError | null {
  try {
    check();
    return null;
  } catch (err) {
    const gerr = err as GuardError;
    return { key: gerr.key, params: gerr.params };
  }
}

/**
 * The errors of one transition: unknown ends, then the guard, then the actions. A bad guard
 * hides the action checks, like the first failing check of the backend.
 */
function transitionErrors(
  t: TransitionDef,
  states: readonly StateDef[],
  keySet: ReadonlySet<string>,
): readonly FlowValidationError[] {
  const ends: readonly FlowValidationError[] = [
    ...(keySet.has(t.from)
      ? []
      : [{ key: 'admin.flow.err.unknownFrom' as const, params: { key: String(t.from) } }]),
    ...(keySet.has(t.to)
      ? []
      : [{ key: 'admin.flow.err.unknownTo' as const, params: { key: String(t.to) } }]),
  ];
  const guardError = thrownError(() => validateGuard(t.guard, !t.automatic));
  const target = states.find((s) => s.key === t.to);
  return [
    ...ends,
    ...(guardError ? [guardError] : actionListErrors(t.actions ?? [], t, target)),
  ];
}

/**
 * The errors of the actions in order. The first action that fails the whitelist ends the
 * list, because the check throws there.
 */
function actionListErrors(
  actions: readonly ActionDef[],
  t: TransitionDef,
  target: StateDef | undefined,
): readonly FlowValidationError[] {
  if (actions.length === 0) return [];
  const [first, ...rest] = actions;
  const failure = thrownError(() => validateAction(first));
  return failure
    ? [failure]
    : [...actionErrors(first, t, target), ...actionListErrors(rest, t, target)];
}

/** The errors of one valid action against the state that the transition enters. */
function actionErrors(
  a: ActionDef,
  t: TransitionDef,
  target: StateDef | undefined,
): readonly FlowValidationError[] {
  const intoVote = (target?.kind ?? 'normal') === 'vote';
  const budgetVote = target?.kind === 'vote' && target.config?.gremiumSource === 'budget';
  const recipients = Array.isArray(a['recipients'])
    ? (a['recipients'] as readonly { readonly kind?: unknown }[])
    : [];
  const checks: readonly (readonly [boolean, TranslationKey])[] = [
    [a.type === 'addToNextSession' && !intoVote, 'admin.flow.err.sessionNeedsVote'],
    [
      a.type === 'addToNextSession' && budgetVote && 'gremiumId' in a,
      'admin.flow.err.sessionGremiumIntoBudgetVote',
    ],
    [
      a.type === 'notify' && !intoVote && recipients.some((r) => r?.kind === 'voteGremium'),
      'admin.flow.err.voteGremiumRecipientNeedsVote',
    ],
    [ASSIGN_BUDGET_ACTIONS.includes(a.type) && budgetVote, 'admin.flow.err.assignIntoBudgetVote'],
  ];
  return checks
    .filter(([hit]) => hit)
    .map(([, key]) => ({ key, params: { from: String(t.from), to: String(t.to) } }));
}

/** The errors of a vote state: its gremium, its pass/fail branches, no automatic exit. */
function voteStateErrors(
  s: StateDef,
  transitions: readonly TransitionDef[],
): readonly FlowValidationError[] {
  if (s.kind !== 'vote') return [];
  const outBranches = transitions
    .filter((t) => t.from === s.key && t.branch)
    .map((t) => t.branch as string);
  const gremiumError = voteGremiumError(s, s.config ?? {});
  const checks: readonly (readonly [boolean, TranslationKey])[] = [
    [[...outBranches].sort().join(',') !== 'fail,pass', 'admin.flow.err.voteBranches'],
    [
      transitions.some((t) => t.from === s.key && t.automatic && !t.branch),
      'admin.flow.err.voteNoAutomatic',
    ],
  ];
  return [
    ...(gremiumError ? [gremiumError] : []),
    ...checks.filter(([hit]) => hit).map(([, key]) => key),
  ].map((key) => ({ key, params: { key: s.key } }));
}

/** The error of the gremium source of a vote state, or null when it is sound. */
function voteGremiumError(s: StateDef, config: StateConfig): TranslationKey | null {
  const hasId = 'gremiumId' in config;
  const hasSource = 'gremiumSource' in config;
  if (hasId && hasSource) return 'admin.flow.err.voteGremiumBoth';
  if (hasSource) {
    return config['gremiumSource'] !== 'budget'
      ? 'admin.flow.err.voteGremiumSource'
      : s.isInitial
        ? 'admin.flow.err.voteGremiumInitial'
        : null;
  }
  return typeof config['gremiumId'] !== 'string' || config['gremiumId'] === ''
    ? 'admin.flow.err.voteNeedsGremium'
    : null;
}

function findUnreachable(
  initial: string,
  keySet: ReadonlySet<string>,
  transitions: readonly TransitionDef[],
): readonly string[] {
  const adjacency = new Map(
    [...keySet].map((k) => [
      k,
      transitions.filter((t) => t.from === k && keySet.has(t.to)).map((t) => t.to),
    ]),
  );
  const reach = (frontier: readonly string[], seen: ReadonlySet<string>): ReadonlySet<string> => {
    const next = [...new Set(frontier.flatMap((n) => adjacency.get(n) ?? []))].filter(
      (n) => !seen.has(n),
    );
    return next.length === 0 ? seen : reach(next, new Set([...seen, ...next]));
  };
  const seen = reach([initial], new Set([initial]));
  return [...keySet].filter((k) => !seen.has(k));
}

/** A state in canonical wire form: the schema fields, without empty optionals. */
function normalizeState(s: StateDef): StateDef {
  return {
    key: s.key,
    label: s.label,
    ...(s.color ? { color: s.color } : {}),
    ...(s.editAllowed === false ? { editAllowed: false } : {}),
    ...(s.isInitial ? { isInitial: true } : {}),
    ...(s.isTerminal ? { isTerminal: true } : {}),
    ...(s.kind && s.kind !== 'normal' ? { kind: s.kind } : {}),
    ...(s.config && Object.keys(s.config).length > 0 ? { config: s.config } : {}),
  };
}

/** A transition in canonical wire form: the schema fields, without empty optionals. */
function normalizeTransition(t: TransitionDef): TransitionDef {
  return {
    from: t.from,
    to: t.to,
    ...(t.label ? { label: t.label } : {}),
    ...(t.color ? { color: t.color } : {}),
    ...(t.guard ? { guard: t.guard } : {}),
    ...(t.actions && t.actions.length > 0 ? { actions: t.actions } : {}),
    ...(t.order != null ? { order: t.order } : {}),
    ...(t.automatic ? { automatic: true } : {}),
    ...(t.branch ? { branch: t.branch } : {}),
    ...(t.requiresAction === false ? { requiresAction: false } : {}),
  };
}

/**
 * The groups that still hold a known state or group, in canonical wire form. A group drops
 * itself and unknown ids from `groupIds`.
 */
function normalizeGroups(
  groups: readonly FlowGroup[],
  stateKeys: ReadonlySet<string>,
): readonly FlowGroup[] {
  const allGroupIds = new Set(groups.map((g) => g.id));
  return groups
    .map((g) => ({
      ...g,
      stateKeys: g.stateKeys.filter((k) => stateKeys.has(k)),
      groupIds: (g.groupIds ?? []).filter((id) => id !== g.id && allGroupIds.has(id)),
    }))
    .filter((g) => g.stateKeys.length > 0 || g.groupIds.length > 0)
    .map((g) => ({
      id: g.id,
      name: g.name,
      stateKeys: g.stateKeys,
      ...(g.groupIds.length ? { groupIds: g.groupIds } : {}),
      ...(g.color ? { color: g.color } : {}),
    }));
}

/**
 * Bring the graph into canonical wire form: exactly the schema fields, with empty
 * optionals dropped. A flow version stores this form. The round-trip guarantee holds:
 * `normalize(parse(serialize(g))) === normalize(g)`.
 *
 * The legacy `collapsed` flag is dropped, because content opens through drill-down.
 */
export function normalizeFlowGraph(graph: FlowGraph): FlowGraph {
  const states = graph.states.map(normalizeState);
  const transitions = (graph.transitions ?? []).map(normalizeTransition);
  const positions = graph.layout?.positions ?? {};
  const groups = normalizeGroups(graph.layout?.groups ?? [], new Set(states.map((s) => s.key)));
  const layout: FlowLayout = {
    ...(Object.keys(positions).length > 0 ? { positions: { ...positions } } : {}),
    ...(groups.length > 0 ? { groups } : {}),
  };
  return { states, transitions, ...(layout.positions || layout.groups ? { layout } : {}) };
}

export function serializeFlowGraph(graph: FlowGraph): string {
  return JSON.stringify(normalizeFlowGraph(graph), null, 2);
}

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
 *
 * Layers are the longest path from the initial state; the Bellman-style relaxation stops even with
 * cycles, because the iteration bound limits it.
 */
export function autoLayout(graph: FlowGraph): FlowGraph {
  const existing = { ...(graph.layout?.positions ?? {}) };
  const keys = graph.states.map((s) => s.key);
  const keySet = new Set(keys);
  const edges = (graph.transitions ?? []).filter(
    (t) => t.from !== t.to && keySet.has(t.from) && keySet.has(t.to),
  );
  const out: Neighbors = new Map(
    [...keySet].map((k) => [k, edges.filter((t) => t.from === k).map((t) => t.to)]),
  );
  const incoming: Neighbors = new Map(
    [...keySet].map((k) => [k, edges.filter((t) => t.to === k).map((t) => t.from)]),
  );
  const initial = graph.states.find((s) => s.isInitial)?.key ?? keys[0];
  const reached = relaxDepths(
    new Map(initial ? [[initial, 0]] : []),
    out,
    keys.length,
    keys.length,
  );
  const maxDepth = Math.max(0, ...reached.values());
  const depth = new Map(keys.map((k) => [k, reached.get(k) ?? maxDepth + 1]));
  const layerDepths = [...new Set(keys.map((k) => depth.get(k)!))].sort((a, b) => a - b);
  const initialLayers: Layers = new Map(
    layerDepths.map((d) => [d, keys.filter((k) => depth.get(k) === d)]),
  );
  const sweep = [
    ...layerDepths.map((d) => [d, incoming] as const),
    ...[...layerDepths].reverse().map((d) => [d, out] as const),
  ];
  const layers = [...sweep, ...sweep, ...sweep].reduce(
    (acc, [d, neighbors]) => withEntry(acc, d, byBarycenter(acc, d, neighbors, depth)),
    initialLayers,
  );
  const tallest = Math.max(...layerDepths.map((d) => layers.get(d)!.length), 1);
  const computed = Object.fromEntries(
    layerDepths.flatMap((d) => {
      const layer = layers.get(d)!;
      const offset = ((tallest - layer.length) * ROW_GAP) / 2;
      return layer.map((k, row) => [k, { x: PAD + d * COL_GAP, y: PAD + offset + row * ROW_GAP }]);
    }),
  );
  return {
    ...graph,
    layout: { ...(graph.layout ?? {}), positions: { ...computed, ...existing } },
  };
}

/** The neighbors of each state key along the edges. */
type Neighbors = ReadonlyMap<string, readonly string[]>;

/** The state keys of each layer, in their row order. */
type Layers = ReadonlyMap<number, readonly string[]>;

/**
 * Relax the longest-path depths until nothing changes or the pass budget ends. Each pass
 * walks the edges in order and sees the depths that the same pass already raised. A depth
 * never exceeds `cap`, so a cycle stops.
 */
function relaxDepths(
  depth: ReadonlyMap<string, number>,
  out: Neighbors,
  cap: number,
  passes: number,
): ReadonlyMap<string, number> {
  if (passes === 0) return depth;
  const pairs = [...out].flatMap(([from, targets]) => targets.map((to) => [from, to] as const));
  const next = pairs.reduce((acc, [from, to]) => {
    const d = acc.get(from);
    const candidate = d === undefined ? -1 : d + 1;
    return d !== undefined && candidate > (acc.get(to) ?? -1) && candidate <= cap
      ? withEntry(acc, to, candidate)
      : acc;
  }, depth);
  return next === depth ? depth : relaxDepths(next, out, cap, passes - 1);
}

/**
 * One layer ordered by the barycenter of its neighbors' rows. A key without a placed
 * neighbor keeps its own row as its weight.
 */
function byBarycenter(
  layers: Layers,
  d: number,
  neighbors: Neighbors,
  depth: ReadonlyMap<string, number>,
): readonly string[] {
  const layer = layers.get(d)!;
  const weight = new Map(
    layer.map((k) => {
      const rows = (neighbors.get(k) ?? [])
        .map((n) => layers.get(depth.get(n)!)!.indexOf(n))
        .filter((i) => i >= 0);
      const center =
        rows.length > 0 ? rows.reduce((a, b) => a + b, 0) / rows.length : layer.indexOf(k);
      return [k, center] as const;
    }),
  );
  return [...layer].sort((a, b) => weight.get(a)! - weight.get(b)!);
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
