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
  type FlowGroup,
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
      // Einen vote-State entscheidet nur die Abstimmung (oder ein manueller Abbruch):
      // ein automatischer Ausgang würde sofort feuern, ohne dass je abgestimmt wurde
      // (#vote-bypass) — spiegelt den BE-Validator.
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
    if (s.isTerminal) out.isTerminal = true;
    // State-Art + Config (#28) — `normal` ist der Default und wird weggelassen.
    if (s.kind && s.kind !== 'normal') out.kind = s.kind;
    if (s.config && Object.keys(s.config).length > 0) out.config = s.config;
    return out;
  });
  const transitions: TransitionDef[] = (graph.transitions ?? []).map((t) => {
    const out: TransitionDef = { from: t.from, to: t.to };
    if (t.label) out.label = t.label;
    if (t.color) out.color = t.color; // Pfeil-/Button-Farbe (#flow) erhalten
    if (t.guard) out.guard = t.guard;
    if (t.actions && t.actions.length > 0) out.actions = t.actions;
    if (t.order != null) out.order = t.order;
    if (t.automatic) out.automatic = true;
    if (t.branch) out.branch = t.branch; // Ergebnis-Zweig (#28)
    // Default `true` wird weggelassen — nur das explizite Opt-out persistieren.
    if (t.requiresAction === false) out.requiresAction = false;
    return out;
  });
  const out: FlowGraph = { states, transitions };
  const keySet2 = new Set(states.map((s) => s.key));
  const positions = graph.layout?.positions ?? {};
  const layout: { positions?: Record<string, { x: number; y: number }>; groups?: FlowGroup[] } = {};
  if (Object.keys(positions).length > 0) layout.positions = { ...positions };
  // Gruppen (#flow-groups): nur existierende States/Gruppen referenzieren; eine
  // Gruppe ohne States UND ohne Unter-Gruppen verschwindet. Legacy-`collapsed`
  // wird wegnormalisiert (Inhalt öffnet sich heute per Drill-Down).
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

// --- Auto-Layout (Sugiyama-light: Schichten + Barycenter + Zentrierung) ------

const COL_GAP = 240;
const ROW_GAP = 130;
/** Linker/oberer Rand, damit Knoten nicht am Canvas-Rand kleben (#flow-pad). */
const PAD = 40;

/**
 * Fehlende Knoten-Positionen ergänzen (bereits gesetzte bleiben erhalten —
 * Editor-Drag persistiert). Layout-Algorithmus (#flow-autolayout):
 *
 * 1. **Schicht = längster Pfad** vom Initial-State (statt BFS): Knoten rücken
 *    so weit nach rechts wie nötig — Kanten zeigen überwiegend vorwärts,
 *    Rückkanten bleiben die Ausnahme statt Layout-Chaos.
 * 2. **Barycenter-Ordnung** je Schicht (3 Vor-/Rückwärts-Sweeps): Knoten
 *    sortieren sich neben ihre Nachbarn → deutlich weniger Kreuzungen.
 * 3. **Vertikale Zentrierung**: kleine Schichten mittig zur höchsten Schicht
 *    statt alle oben angeklebt.
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
    if (t.from === t.to) continue; // Self-Loops sind layout-neutral.
    if (keySet.has(t.from) && keySet.has(t.to)) {
      out.get(t.from)!.push(t.to);
      incoming.get(t.to)!.push(t.from);
    }
  }

  // 1. Schichten: längster Pfad ab Initial (Bellman-artige Relaxierung, durch
  //    die Iterationsgrenze auch bei Zyklen terminierend).
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
  // Nicht erreichbare States hinter die tiefste Schicht hängen.
  let maxDepth = 0;
  for (const d of depth.values()) maxDepth = Math.max(maxDepth, d);
  for (const k of keys) {
    if (!depth.has(k)) depth.set(k, maxDepth + 1);
  }

  // 2. Schicht-Listen (Initial-Reihenfolge = State-Reihenfolge) + Barycenter.
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

  // 3. Positionen: Spalte = Schicht, Zeile = Ordnung; Schicht vertikal mittig.
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
 * Kondensiertes Auto-Layout (#flow-groups): beliebige Entitäten (sichtbare
 * States + Gruppen-Kästen einer Drill-Down-Ebene) als Knoten eines virtuellen
 * Graphen anordnen — eine Gruppe verhält sich beim Auto-Arrange wie EIN Knoten.
 * Liefert frische Positionen je Entitäts-Id (bestehende werden ignoriert).
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
