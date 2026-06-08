import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ButtonComponent, CheckboxComponent, DialogComponent, SelectComponent, type SelectOption } from '@shared/ui';
import { ToastService } from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import { AdminOptionsService } from '../admin-options.service';
import {
  ACTION_TYPES,
  type ActionType,
  type FlowGraph,
  GUARD_LEAF_OPERATORS,
  type GuardLeafOperator,
  type StateCategory,
  type StateDef,
  type TransitionDef,
  VOTE_RESULTS,
} from '../admin.models';
import {
  STATE_CATEGORIES,
  autoLayout,
  blankState,
  blankTransition,
  normalizeFlowGraph,
  serializeFlowGraph,
  validateFlowGraph,
} from '../flow-graph.util';
import { FLOW_PRESETS, type FlowPreset } from './flow-presets';

/** Benutzer-Vorlage (im localStorage gesichert, #20). */
interface CustomTemplate {
  key: string;
  name: string;
  graph: FlowGraph;
}
const TEMPLATE_STORE = 'ap.flowTemplates';

/** Aktuelle Auswahl im Canvas: ein State (per key) oder eine Transition (per Index). */
type Selection =
  | { kind: 'state'; key: string }
  | { kind: 'transition'; index: number }
  | null;

const NODE_W = 150;
const NODE_H = 52;
const MARGIN = 40;

/**
 * Flow-Editor als **visueller Drag&Drop-Canvas** (#8, T-34, flows §9.5).
 *
 * States sind Knoten, die frei verschoben werden (Position persistiert im
 * `layout`); Übergänge werden gezeichnet, indem man vom Verbindungs-Punkt eines
 * Knotens auf einen Zielknoten zieht. Ein Klick auf Knoten/Kante öffnet das
 * Inspektor-Panel (Schlüssel/Label/Kategorie/Initial bzw. Guard/Actions/**automatisch**).
 * Im Simple-Modus bleiben Guards/Actions ausgeblendet (Presets genügen); der
 * Expert-Modus zeigt die Whitelist-Operatoren (kein Freitext-eval). Speichern legt
 * eine Flow-Version an; Client-Validierung spiegelt `validate_flow_graph`.
 */
@Component({
  selector: 'app-flow-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CheckboxComponent, SelectComponent, DialogComponent],
  templateUrl: './flow-editor.component.html',
  styleUrl: './flow-editor.component.scss',
})
export class FlowEditorComponent {
  private readonly api = inject(AdminApiService);
  private readonly options = inject(AdminOptionsService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly canvas = viewChild<ElementRef<SVGSVGElement>>('canvas');

  /** Antragstypen als Auswahl (#69) — ersetzt das hartkodierte `'mock-type'`. */
  protected readonly typeOptions = signal<SelectOption[]>([]);
  protected readonly selectedTypeId = signal('');

  protected readonly categories = STATE_CATEGORIES;
  protected readonly guardOps = GUARD_LEAF_OPERATORS;
  protected readonly actionTypes = ACTION_TYPES;
  protected readonly presets = FLOW_PRESETS;

  protected readonly graph = signal<FlowGraph>(autoLayout(blankGraph()));
  protected readonly selectedPreset = signal<string>(FLOW_PRESETS[0].key);

  /** Gespeicherte Benutzer-Vorlagen (#20) — im localStorage. */
  protected readonly customTemplates = signal<CustomTemplate[]>(loadTemplates());
  protected readonly saveOpen = signal(false);
  protected readonly templateName = signal('');

  /** Vorlagen-Dropdown: eingebaute Presets + eigene Vorlagen. */
  protected readonly presetOptions = computed(() => [
    ...this.presets.map((p) => ({ key: p.key, label: this.i18n.translate(p.labelKey) })),
    ...this.customTemplates().map((t) => ({ key: t.key, label: `★ ${t.name}` })),
  ]);

  protected selectedIsCustom(): boolean {
    return this.customTemplates().some((t) => t.key === this.selectedPreset());
  }

  /** Aktuell ausgewählter Knoten/Kante für das Inspektor-Panel. */
  protected readonly selection = signal<Selection>(null);
  /** Temporäre Kante während des Aufziehens eines neuen Übergangs. */
  protected readonly tempEdge = signal<{ x1: number; y1: number; x2: number; y2: number } | null>(
    null,
  );

  protected readonly NODE_W = NODE_W;
  protected readonly NODE_H = NODE_H;

  private drag: { key: string; dx: number; dy: number; moved: boolean } | null = null;
  private connectFrom: string | null = null;

  constructor() {
    this.options
      .applicationTypeOptions()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (opts) => {
          this.typeOptions.set(opts);
          if (opts.length && !this.selectedTypeId()) this.selectedTypeId.set(opts[0].value);
        },
        error: () => this.typeOptions.set([]),
      });
  }

  protected readonly validation = computed(() => validateFlowGraph(this.graph()));
  protected readonly json = computed(() => serializeFlowGraph(this.graph()));

  /** Knoten-Positionen (Top-Left) aus dem Layout. */
  private readonly positions = computed(() => this.graph().layout?.positions ?? {});

  protected readonly nodes = computed(() => {
    const pos = this.positions();
    const sel = this.selection();
    return this.graph().states.map((s) => ({
      key: s.key,
      label: this.label(s),
      category: s.category ?? null,
      isInitial: !!s.isInitial,
      selected: sel?.kind === 'state' && sel.key === s.key,
      x: pos[s.key]?.x ?? 0,
      y: pos[s.key]?.y ?? 0,
    }));
  });

  protected readonly edges = computed(() => {
    const pos = this.positions();
    const sel = this.selection();
    return (this.graph().transitions ?? [])
      .map((t, index) => ({ t, index }))
      .filter(({ t }) => pos[t.from] && pos[t.to])
      .map(({ t, index }) => {
        const a = pos[t.from];
        const b = pos[t.to];
        const x1 = a.x + NODE_W;
        const y1 = a.y + NODE_H / 2;
        const x2 = b.x;
        const y2 = b.y + NODE_H / 2;
        return {
          index,
          x1,
          y1,
          x2,
          y2,
          mx: (x1 + x2) / 2,
          my: (y1 + y2) / 2,
          label: t.label?.['de'] ?? '',
          automatic: !!t.automatic,
          selected: sel?.kind === 'transition' && sel.index === index,
        };
      });
  });

  /**
   * Canvas-Maße aus den Knoten-Positionen. Das SVG wird **1:1** gerendert
   * (`width`/`height` == viewBox), in einem scrollbaren Wrapper — so skaliert das
   * Diagramm beim Ziehen eines Knotens nicht um (kein Springen) und 1 User-Unit
   * entspricht 1 Pixel (exaktes Drag-Mapping).
   */
  protected readonly canvasW = computed(() => {
    const xs = Object.values(this.positions()).map((p) => p.x);
    return Math.max((xs.length ? Math.max(...xs) : 0) + NODE_W + MARGIN, 480);
  });
  protected readonly canvasH = computed(() => {
    const ys = Object.values(this.positions()).map((p) => p.y);
    return Math.max((ys.length ? Math.max(...ys) : 0) + NODE_H + MARGIN, 320);
  });
  protected readonly viewBox = computed(() => `0 0 ${this.canvasW()} ${this.canvasH()}`);

  /** Aktuell ausgewählter State (oder undefined). */
  protected readonly selectedState = computed<StateDef | undefined>(() => {
    const sel = this.selection();
    return sel?.kind === 'state' ? this.graph().states.find((s) => s.key === sel.key) : undefined;
  });

  protected readonly selectedTransition = computed<{ t: TransitionDef; index: number } | undefined>(
    () => {
      const sel = this.selection();
      if (sel?.kind !== 'transition') return undefined;
      const t = this.graph().transitions?.[sel.index];
      return t ? { t, index: sel.index } : undefined;
    },
  );

  protected label(s: StateDef): string {
    return s.label['de'] || s.label['en'] || s.key;
  }

  protected catLabel(c: StateCategory): string {
    return this.i18n.translate(`admin.flow.cat.${c}` as TranslationKey);
  }

  /** Von/Nach-Optionen als „Klarname (key)" (FE5). */
  protected stateOptions(): SelectOption[] {
    return this.graph().states.map((s) => ({ value: s.key, label: `${this.label(s)} (${s.key})` }));
  }

  /** Guard-Operatoren mit übersetztem Klarnamen (FE2). */
  protected guardOpOptions(): SelectOption[] {
    return this.guardOps.map((op) => ({
      value: op,
      label: this.i18n.translate(`admin.flow.guardOp.${op}` as TranslationKey),
    }));
  }

  /** Action-Typen mit übersetztem Klarnamen (FE6). */
  protected actionOptions(): SelectOption[] {
    return this.actionTypes.map((a) => ({
      value: a,
      label: this.i18n.translate(`admin.flow.actionType.${a}` as TranslationKey),
    }));
  }

  /** Übersetzter Action-Klarname + Beschreibung (FE6/FE7). */
  protected actionLabel(type: string): string {
    return this.i18n.translate(`admin.flow.actionType.${type}` as TranslationKey);
  }
  protected actionDesc(type: string): string {
    return this.i18n.translate(`admin.flow.actionDesc.${type}` as TranslationKey);
  }

  /** Wert-Optionen für `voteResult` (passed/rejected/tie) als Dropdown (FE1). */
  protected readonly voteResultOptions: SelectOption[] = VOTE_RESULTS.map((v) => ({
    value: v,
    label: this.i18n.translate(`admin.flow.voteResult.${v}` as TranslationKey),
  }));

  /**
   * Art des Wert-Controls je Guard-Operator (FE1):
   * - `none`  → boolesche/parameterlose Operatoren (kein Wertfeld)
   * - `vote`  → `voteResult` → Dropdown passed/rejected/tie
   * - `text`  → `roleIs`/`permissionIs` → Freitext mit Annotation
   */
  protected guardValueKind(op: string): 'none' | 'vote' | 'text' {
    if (op === 'voteResult') return 'vote';
    if (op === 'fieldsComplete' || op === 'deadlinePassed' || op === 'manual' || !op) return 'none';
    return 'text';
  }

  /** Annotation/Hinweis für das Guard-Wertfeld je Operator (FE1). */
  protected guardValueHint(op: string): string {
    return this.i18n.translate(`admin.flow.guardHint.${op}` as TranslationKey);
  }

  // --- presets / templates -------------------------------------------------
  protected applyPreset(): void {
    const key = this.selectedPreset();
    const graph =
      this.presets.find((p) => p.key === key)?.graph ??
      this.customTemplates().find((t) => t.key === key)?.graph;
    if (!graph) return;
    this.selection.set(null);
    this.graph.set(autoLayout(JSON.parse(JSON.stringify(graph)) as FlowGraph));
  }

  protected openSaveTemplate(): void {
    this.templateName.set('');
    this.saveOpen.set(true);
  }

  /** Aktuellen Graphen als wiederverwendbare Vorlage speichern (#20). */
  protected saveTemplate(): void {
    const name = this.templateName().trim();
    if (!name) return;
    const tpl: CustomTemplate = {
      key: `custom-${name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`,
      name,
      graph: normalizeFlowGraph(this.graph()),
    };
    const next = [...this.customTemplates().filter((t) => t.key !== tpl.key), tpl];
    this.customTemplates.set(next);
    saveTemplates(next);
    this.selectedPreset.set(tpl.key);
    this.saveOpen.set(false);
    this.toast.success(this.i18n.translate('admin.flow.templateSaved'));
  }

  protected deleteTemplate(): void {
    const key = this.selectedPreset();
    const next = this.customTemplates().filter((t) => t.key !== key);
    this.customTemplates.set(next);
    saveTemplates(next);
    this.selectedPreset.set(this.presets[0].key);
  }

  // --- states --------------------------------------------------------------
  protected addState(): void {
    const key = uniqueKey('state', this.graph().states);
    this.graph.update((g) =>
      autoLayout({ ...g, states: [...g.states, blankState(key, g.states.length === 0)] }),
    );
    this.selection.set({ kind: 'state', key });
  }

  protected removeSelectedState(): void {
    const sel = this.selection();
    if (sel?.kind !== 'state') return;
    const key = sel.key;
    this.graph.update((g) => {
      const positions = { ...(g.layout?.positions ?? {}) };
      delete positions[key];
      return {
        ...g,
        states: g.states.filter((s) => s.key !== key),
        transitions: (g.transitions ?? []).filter((t) => t.from !== key && t.to !== key),
        layout: { positions },
      };
    });
    this.selection.set(null);
  }

  /** Genau ein Initial: gewählten State setzen, alle anderen zurücksetzen. */
  protected setInitial(key: string): void {
    this.graph.update((g) => ({
      ...g,
      states: g.states.map((s) => ({ ...s, isInitial: s.key === key })),
    }));
  }

  protected setStateKey(oldKey: string, newKey: string): void {
    const key = newKey.trim();
    this.graph.update((g) => {
      const positions = { ...(g.layout?.positions ?? {}) };
      if (positions[oldKey] && key) {
        positions[key] = positions[oldKey];
        if (key !== oldKey) delete positions[oldKey];
      }
      return {
        ...g,
        states: g.states.map((s) => (s.key === oldKey ? { ...s, key } : s)),
        transitions: (g.transitions ?? []).map((t) => ({
          ...t,
          from: t.from === oldKey ? key : t.from,
          to: t.to === oldKey ? key : t.to,
        })),
        layout: { positions },
      };
    });
    this.selection.set({ kind: 'state', key });
  }

  protected setStateLabel(key: string, lang: 'de' | 'en', value: string): void {
    this.graph.update((g) => ({
      ...g,
      states: g.states.map((s) =>
        s.key === key ? { ...s, label: { ...s.label, [lang]: value } } : s,
      ),
    }));
  }

  protected setStateCategory(key: string, category: string): void {
    this.graph.update((g) => ({
      ...g,
      states: g.states.map((s) =>
        s.key === key ? { ...s, category: (category || null) as StateCategory | null } : s,
      ),
    }));
  }

  protected setStateEditAllowed(key: string, on: boolean): void {
    this.graph.update((g) => ({
      ...g,
      states: g.states.map((s) => (s.key === key ? { ...s, editAllowed: on } : s)),
    }));
  }

  // --- transitions ---------------------------------------------------------
  protected removeSelectedTransition(): void {
    const sel = this.selection();
    if (sel?.kind !== 'transition') return;
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).filter((_, idx) => idx !== sel.index),
    }));
    this.selection.set(null);
  }

  protected setTransitionEndpoint(index: number, end: 'from' | 'to', key: string): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) =>
        idx === index ? { ...t, [end]: key } : t,
      ),
    }));
  }

  protected setTransitionLabel(index: number, lang: 'de' | 'en', value: string): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) => {
        if (idx !== index) return t;
        const label = { ...(t.label ?? {}), [lang]: value };
        // Leere Sprachen wegräumen; bleibt nichts übrig → kein Label.
        const cleaned = Object.fromEntries(Object.entries(label).filter(([, v]) => v));
        return { ...t, label: Object.keys(cleaned).length ? cleaned : null };
      }),
    }));
  }

  protected setTransitionAutomatic(index: number, on: boolean): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) =>
        idx === index ? { ...t, automatic: on } : t,
      ),
    }));
  }

  protected setGuard(index: number, op: string, value: string): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) => {
        if (idx !== index) return t;
        if (!op) {
          const next = { ...t };
          delete next.guard;
          return next;
        }
        return { ...t, guard: { [op]: coerceGuardValue(op as GuardLeafOperator, value) } };
      }),
    }));
  }

  protected guardOp(t: TransitionDef): string {
    return t.guard ? Object.keys(t.guard)[0] : '';
  }

  protected guardValue(t: TransitionDef): string {
    if (!t.guard) return '';
    const v = Object.values(t.guard)[0];
    return v == null ? '' : String(v);
  }

  protected addAction(index: number, type: string): void {
    if (!type) return;
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) =>
        idx === index ? { ...t, actions: [...(t.actions ?? []), { type: type as ActionType }] } : t,
      ),
    }));
  }

  protected removeAction(index: number, ai: number): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) =>
        idx === index ? { ...t, actions: (t.actions ?? []).filter((_, k) => k !== ai) } : t,
      ),
    }));
  }

  protected relayout(): void {
    this.graph.update((g) => autoLayout({ ...g, layout: null }));
  }

  // --- Canvas-Interaktion (Drag & Connect) ---------------------------------
  /** Knoten greifen → verschieben **oder** (bei Klick ohne Bewegung) auswählen. */
  protected onNodePointerDown(event: PointerEvent, key: string): void {
    event.stopPropagation();
    const p = this.toSvg(event);
    const pos = this.positions()[key] ?? { x: 0, y: 0 };
    this.drag = { key, dx: p.x - pos.x, dy: p.y - pos.y, moved: false };
    (event.target as Element).setPointerCapture?.(event.pointerId);
  }

  /** Vom Verbindungs-Punkt eines Knotens eine neue Kante aufziehen. */
  protected onConnectPointerDown(event: PointerEvent, key: string): void {
    event.stopPropagation();
    this.connectFrom = key;
    const p = this.toSvg(event);
    this.tempEdge.set({ x1: p.x, y1: p.y, x2: p.x, y2: p.y });
    (event.target as Element).setPointerCapture?.(event.pointerId);
  }

  protected onCanvasPointerMove(event: PointerEvent): void {
    if (this.drag) {
      const p = this.toSvg(event);
      const nx = Math.max(0, Math.round(p.x - this.drag.dx));
      const ny = Math.max(0, Math.round(p.y - this.drag.dy));
      const key = this.drag.key;
      this.drag.moved = true;
      this.graph.update((g) => ({
        ...g,
        layout: { positions: { ...(g.layout?.positions ?? {}), [key]: { x: nx, y: ny } } },
      }));
      return;
    }
    if (this.connectFrom) {
      const from = this.positions()[this.connectFrom];
      const p = this.toSvg(event);
      this.tempEdge.set({ x1: from.x + NODE_W, y1: from.y + NODE_H / 2, x2: p.x, y2: p.y });
    }
  }

  protected onCanvasPointerUp(event: PointerEvent): void {
    if (this.drag) {
      // Klick ohne Bewegung = Auswahl; Bewegung = nur Position übernommen.
      if (!this.drag.moved) this.selection.set({ kind: 'state', key: this.drag.key });
      this.drag = null;
      return;
    }
    if (this.connectFrom) {
      const target = this.nodeAt(this.toSvg(event));
      if (target && target !== this.connectFrom) {
        const from = this.connectFrom;
        this.graph.update((g) => ({
          ...g,
          transitions: [...(g.transitions ?? []), blankTransition(from, target)],
        }));
        this.selection.set({ kind: 'transition', index: (this.graph().transitions?.length ?? 1) - 1 });
      }
      this.connectFrom = null;
      this.tempEdge.set(null);
    }
  }

  protected selectEdge(index: number): void {
    this.selection.set({ kind: 'transition', index });
  }

  protected clearSelection(): void {
    if (!this.drag && !this.connectFrom) this.selection.set(null);
  }

  /** Client-Koordinaten → SVG-User-Space (für Drag/Connect-Mathematik). */
  private toSvg(event: PointerEvent): { x: number; y: number } {
    const svg = this.canvas()?.nativeElement;
    if (!svg) return { x: event.clientX, y: event.clientY };
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: event.clientX, y: event.clientY };
    const pt = svg.createSVGPoint();
    pt.x = event.clientX;
    pt.y = event.clientY;
    const local = pt.matrixTransform(ctm.inverse());
    return { x: local.x, y: local.y };
  }

  /** State, dessen Knoten-Rechteck den Punkt enthält (für Connect-Ziel). */
  private nodeAt(p: { x: number; y: number }): string | null {
    const pos = this.positions();
    for (const s of this.graph().states) {
      const np = pos[s.key];
      if (np && p.x >= np.x && p.x <= np.x + NODE_W && p.y >= np.y && p.y <= np.y + NODE_H) {
        return s.key;
      }
    }
    return null;
  }

  // --- save ----------------------------------------------------------------
  protected save(): void {
    const typeId = this.selectedTypeId();
    if (!this.validation().valid || !typeId) {
      this.toast.error(this.i18n.translate('admin.common.invalid'));
      return;
    }
    const graph = normalizeFlowGraph(autoLayout(this.graph()));
    this.api.createFlowVersion(typeId, graph).subscribe({
      next: () => this.toast.success(this.i18n.translate('admin.common.saved')),
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}

/** Guard-Wert typgerecht casten: bool-artige Operatoren → boolean, sonst string. */
function coerceGuardValue(op: GuardLeafOperator, value: string): unknown {
  if (op === 'fieldsComplete' || op === 'deadlinePassed' || op === 'manual') {
    return value === 'true' || value === '1' || value === '';
  }
  return value;
}

function blankGraph(): FlowGraph {
  return { states: [], transitions: [] };
}

/** Benutzer-Vorlagen aus dem localStorage laden (defensiv, #20). */
function loadTemplates(): CustomTemplate[] {
  try {
    const raw = localStorage.getItem(TEMPLATE_STORE);
    const parsed = raw ? (JSON.parse(raw) as CustomTemplate[]) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveTemplates(templates: CustomTemplate[]): void {
  try {
    localStorage.setItem(TEMPLATE_STORE, JSON.stringify(templates));
  } catch {
    /* localStorage nicht verfügbar → Vorlage bleibt nur in dieser Session. */
  }
}

/** Eindeutigen State-Key erzeugen (`state`, `state2`, …). */
function uniqueKey(base: string, states: StateDef[]): string {
  const used = new Set(states.map((s) => s.key));
  if (!used.has(base)) return base;
  let i = 2;
  while (used.has(`${base}${i}`)) i++;
  return `${base}${i}`;
}

export type { FlowPreset };
