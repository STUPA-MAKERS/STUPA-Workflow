import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ButtonComponent, CheckboxComponent, SelectComponent, type SelectOption } from '@shared/ui';
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

type Mode = 'simple' | 'expert';

/**
 * Flow-Editor (T-34, flows §9.5). States/Transitions als Liste + SVG-Diagramm.
 * **Simple-Modus**: Vorlagen/Presets, Guards/Actions ausgeblendet. **Expert-
 * Modus**: Guard-Operator + Action-Typen aus der Whitelist (kein Freitext-eval).
 * Graph→JSON-Mapping + Auto-Layout; Client-Validierung (ein Initial, erreichbar)
 * spiegelt `validate_flow_graph`. Speichern legt eine Flow-Version an.
 *
 * Hinweis: bewusst **ohne** schwere Graph-Lib (rete.js/@foblex/flow). Ein
 * eigenes, a11y-fähiges, testbares SVG hält Bundle + Komplexität klein; ein
 * Rich-Canvas kann später additiv folgen. (Abweichung von der Spec-Empfehlung.)
 */
@Component({
  selector: 'app-flow-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CheckboxComponent, SelectComponent],
  templateUrl: './flow-editor.component.html',
  styleUrl: './flow-editor.component.scss',
})
export class FlowEditorComponent {
  private readonly api = inject(AdminApiService);
  private readonly options = inject(AdminOptionsService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  /** Antragstypen als Auswahl (#69) — ersetzt das hartkodierte `'mock-type'`. */
  protected readonly typeOptions = signal<SelectOption[]>([]);
  protected readonly selectedTypeId = signal('');

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

  protected readonly categories = STATE_CATEGORIES;
  protected readonly guardOps = GUARD_LEAF_OPERATORS;
  protected readonly actionTypes = ACTION_TYPES;
  protected readonly presets = FLOW_PRESETS;

  protected readonly mode = signal<Mode>('simple');
  protected readonly graph = signal<FlowGraph>({ states: [], transitions: [] });
  protected readonly selectedPreset = signal<string>(FLOW_PRESETS[0].key);

  protected readonly validation = computed(() => validateFlowGraph(this.graph()));
  protected readonly laidOut = computed(() => autoLayout(this.graph()));
  protected readonly json = computed(() => serializeFlowGraph(this.graph()));

  /** Diagramm-Knoten (Position + Label) für das SVG. */
  protected readonly nodes = computed(() => {
    const g = this.laidOut();
    const pos = g.layout?.positions ?? {};
    return g.states.map((s) => ({
      key: s.key,
      label: this.label(s),
      isInitial: !!s.isInitial,
      x: (pos[s.key]?.x ?? 0) + 20,
      y: (pos[s.key]?.y ?? 0) + 20,
    }));
  });

  protected readonly edges = computed(() => {
    const g = this.laidOut();
    const pos = g.layout?.positions ?? {};
    return (g.transitions ?? [])
      .filter((t) => pos[t.from] && pos[t.to])
      .map((t) => ({
        x1: pos[t.from].x + 80,
        y1: pos[t.from].y + 40,
        x2: pos[t.to].x + 20,
        y2: pos[t.to].y + 40,
      }));
  });

  protected readonly viewBox = computed(() => {
    const pos = this.laidOut().layout?.positions ?? {};
    const xs = Object.values(pos).map((p) => p.x);
    const ys = Object.values(pos).map((p) => p.y);
    const w = (xs.length ? Math.max(...xs) : 0) + 160;
    const h = (ys.length ? Math.max(...ys) : 0) + 100;
    return `0 0 ${w} ${h}`;
  });

  protected label(s: StateDef): string {
    return s.label['de'] || s.label['en'] || s.key;
  }

  protected catLabel(c: StateCategory): string {
    return this.i18n.translate(`admin.flow.cat.${c}` as TranslationKey);
  }

  // --- mode / presets ------------------------------------------------------
  protected setMode(m: Mode): void {
    this.mode.set(m);
  }

  protected applyPreset(): void {
    const preset = this.presets.find((p) => p.key === this.selectedPreset());
    if (preset) this.graph.set(JSON.parse(JSON.stringify(preset.graph)) as FlowGraph);
  }

  // --- states --------------------------------------------------------------
  protected addState(): void {
    this.graph.update((g) => ({
      ...g,
      states: [...g.states, blankState('', g.states.length === 0)],
    }));
  }

  protected removeState(i: number): void {
    this.graph.update((g) => ({ ...g, states: g.states.filter((_, idx) => idx !== i) }));
  }

  /** Genau ein Initial: gewählten State setzen, alle anderen zurücksetzen. */
  protected setInitial(key: string): void {
    this.graph.update((g) => ({
      ...g,
      states: g.states.map((s) => ({ ...s, isInitial: s.key === key })),
    }));
  }

  protected setStateCategory(i: number, category: string): void {
    this.graph.update((g) => ({
      ...g,
      states: g.states.map((s, idx) =>
        idx === i ? { ...s, category: (category || null) as StateCategory | null } : s,
      ),
    }));
  }

  // --- transitions ---------------------------------------------------------
  protected addTransition(): void {
    const first = this.graph().states[0]?.key ?? '';
    this.graph.update((g) => ({
      ...g,
      transitions: [...(g.transitions ?? []), blankTransition(first, first)],
    }));
  }

  protected removeTransition(i: number): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).filter((_, idx) => idx !== i),
    }));
  }

  protected setGuard(i: number, op: string, value: string): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) => {
        if (idx !== i) return t;
        if (!op) {
          const next = { ...t };
          delete next.guard;
          return next;
        }
        return { ...t, guard: { [op]: coerceGuardValue(op as GuardLeafOperator, value) } };
      }),
    }));
  }

  protected setTransitionLabel(i: number, value: string): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) =>
        idx === i ? { ...t, label: value ? { de: value } : null } : t,
      ),
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

  protected addAction(i: number, type: string): void {
    if (!type) return;
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) =>
        idx === i ? { ...t, actions: [...(t.actions ?? []), { type: type as ActionType }] } : t,
      ),
    }));
  }

  protected removeAction(i: number, ai: number): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) =>
        idx === i ? { ...t, actions: (t.actions ?? []).filter((_, k) => k !== ai) } : t,
      ),
    }));
  }

  protected touch(): void {
    this.graph.update((g) => ({ ...g }));
  }

  protected relayout(): void {
    this.graph.update((g) => autoLayout({ ...g, layout: null }));
  }

  // --- save ----------------------------------------------------------------
  protected save(): void {
    const typeId = this.selectedTypeId();
    if (!this.validation().valid || !typeId) {
      this.toast.error(this.i18n.translate('admin.common.invalid'));
      return;
    }
    const graph = normalizeFlowGraph(autoLayout(this.graph()));
    // Echte applicationType-UUID aus der Auswahl (#69) statt hartkodiertem 'mock-type'.
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

export type { FlowPreset };
