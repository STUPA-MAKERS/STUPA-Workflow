/**
 * Flow-Graph-Helfer (T-34, Flow-Editor). Client-Validierung + Graph↔JSON +
 * Auto-Layout. Die Validierung spiegelt `app/shared/config_schemas.py`
 * (`validate_flow_graph`): ≥1 State, **genau ein** Initial, keine Doppel-Keys,
 * keine danglenden `from`/`to`, alle States vom Initial erreichbar, Guards/
 * Actions nur aus der Whitelist. Der Server validiert beim Speichern erneut
 * autoritativ — das ist reines Sofort-Feedback im UI.
 */
import {
  type FlowGraph,
  type StateDef,
  type TransitionDef,
} from './admin.models';
import { validateAction, validateGuard } from './guard-builder.util';

/** Feld-/State-Keys: `^[a-z][a-z0-9_]*$` (config_schemas KEY_PATTERN). */
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
      // Akteur-Gates (roleIs/isInCommittee) nur auf **manuellen** Übergängen.
      validateGuard(t.guard, !t.automatic);
      for (const a of t.actions ?? []) {
        validateAction(a);
        // `addToNextSession` darf nur in einen vote-State führen (#28).
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

  // State-Art-Regeln (#28) — spiegelt `_validate_state_kinds` (BE), damit der Nutzer
  // den Fehler SOFORT sieht (statt erst beim Speichern als 422).
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
 * Graph in die kanonische Wire-Form bringen (genau die Schema-Felder, leere
 * Optionals weggelassen) — das, was als Flow-Version gespeichert wird. Stabil:
 * `normalize(parse(serialize(g))) === normalize(g)` (Round-Trip-Garantie).
 */
export function normalizeFlowGraph(graph: FlowGraph): FlowGraph {
  const states: StateDef[] = graph.states.map((s) => {
    const out: StateDef = { key: s.key, label: s.label };
    if (s.color) out.color = s.color;
    if (s.editAllowed === false) out.editAllowed = false;
    if (s.isInitial) out.isInitial = true;
    // State-Art + Config (#28) — `normal` ist der Default und wird weggelassen.
    if (s.kind && s.kind !== 'normal') out.kind = s.kind;
    if (s.config && Object.keys(s.config).length > 0) out.config = s.config;
    return out;
  });
  const transitions: TransitionDef[] = (graph.transitions ?? []).map((t) => {
    const out: TransitionDef = { from: t.from, to: t.to };
    if (t.label) out.label = t.label;
    if (t.guard) out.guard = t.guard;
    if (t.actions && t.actions.length > 0) out.actions = t.actions;
    if (t.order != null) out.order = t.order;
    if (t.automatic) out.automatic = true;
    if (t.branch) out.branch = t.branch; // Ergebnis-Zweig (#28)
    return out;
  });
  const out: FlowGraph = { states, transitions };
  if (graph.layout && graph.layout.positions && Object.keys(graph.layout.positions).length > 0) {
    out.layout = { positions: { ...graph.layout.positions } };
  }
  return out;
}

export function serializeFlowGraph(graph: FlowGraph): string {
  return JSON.stringify(normalizeFlowGraph(graph), null, 2);
}

export function parseFlowGraph(json: string): FlowGraph {
  const parsed = JSON.parse(json) as FlowGraph;
  return normalizeFlowGraph(parsed);
}

// --- Auto-Layout (BFS-Schichten) --------------------------------------------

const COL_GAP = 220;
const ROW_GAP = 120;
/** Linker/oberer Rand, damit Knoten nicht am Canvas-Rand kleben (#flow-pad). */
const PAD = 40;

/**
 * Fehlende Knoten-Positionen ergänzen: BFS-Schichten ab dem Initial-State
 * (Spalte = Distanz, Zeile = Reihenfolge in der Schicht). Bereits gesetzte
 * Positionen bleiben erhalten (Editor-Drag persistiert).
 */
export function autoLayout(graph: FlowGraph): FlowGraph {
  const positions: Record<string, { x: number; y: number }> = {
    ...(graph.layout?.positions ?? {}),
  };
  const keySet = new Set(graph.states.map((s) => s.key));
  const adjacency = new Map<string, string[]>();
  for (const k of keySet) adjacency.set(k, []);
  for (const t of graph.transitions ?? []) {
    if (keySet.has(t.from) && keySet.has(t.to)) adjacency.get(t.from)!.push(t.to);
  }

  const initial = graph.states.find((s) => s.isInitial)?.key ?? graph.states[0]?.key;
  const depth = new Map<string, number>();
  if (initial) {
    const queue: [string, number][] = [[initial, 0]];
    while (queue.length > 0) {
      const [node, d] = queue.shift()!;
      if (depth.has(node)) continue;
      depth.set(node, d);
      for (const next of adjacency.get(node) ?? []) queue.push([next, d + 1]);
    }
  }
  // Nicht erreichbare States hinter die tiefste Schicht hängen.
  let maxDepth = 0;
  for (const d of depth.values()) maxDepth = Math.max(maxDepth, d);
  for (const s of graph.states) {
    if (!depth.has(s.key)) depth.set(s.key, maxDepth + 1);
  }

  const rowCursor = new Map<number, number>();
  for (const s of graph.states) {
    if (positions[s.key]) continue;
    const d = depth.get(s.key) ?? 0;
    const row = rowCursor.get(d) ?? 0;
    rowCursor.set(d, row + 1);
    positions[s.key] = { x: PAD + d * COL_GAP, y: PAD + row * ROW_GAP };
  }
  return { ...graph, layout: { positions } };
}

// --- Fabriken ---------------------------------------------------------------

export function emptyFlowGraph(): FlowGraph {
  return { states: [], transitions: [] };
}

export function blankState(key = '', isInitial = false): StateDef {
  return { key, label: { de: '', en: '' }, isInitial, editAllowed: true };
}

export function blankTransition(from = '', to = ''): TransitionDef {
  return { from, to, actions: [] };
}
