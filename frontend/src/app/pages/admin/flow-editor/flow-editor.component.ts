import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  HostListener,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ButtonComponent, CheckboxComponent, SelectComponent, type SelectOption } from '@shared/ui';
import { GuardEditorComponent } from './guard-editor.component';
import { ToastService } from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import { AdminOptionsService } from '../admin-options.service';
import {
  ACTION_TYPES,
  type ActionDef,
  type ActionType,
  COMPARE_OPS,
  type CompareOp,
  type FlowGraph,
  type Guard,
  GUARD_ACTOR_OPERATORS,
  GUARD_CONDITION_OPERATORS,
  type GuardLeafOperator,
  type NotifyRecipient,
  type NotifyRecipientKind,
  NOTIFY_RECIPIENT_KINDS,
  type StateConfig,
  type StateDef,
  type StateKind,
  type TransitionBranch,
  type TransitionDef,
} from '../admin.models';
import {
  autoLayout,
  blankState,
  blankTransition,
  normalizeFlowGraph,
  serializeFlowGraph,
  validateFlowGraph,
} from '../flow-graph.util';

/** Aktuelle Auswahl im Canvas: ein State (per key) oder eine Transition (per Index). */
type Selection =
  | { kind: 'state'; key: string }
  | { kind: 'transition'; index: number }
  | null;

/**
 * Eine Gruppe ausgehender Übergänge eines Knotens mit identischem Guard (#8). Pro
 * unterschiedlichem Guard ein Ausgangs-Punkt; die Reihenfolge der Gruppen ist die
 * Auswertungs-/Prioritätsreihenfolge (erster passender Guard gewinnt).
 */
interface GuardGroup {
  /** Stabile Signatur des Guards (`''` = kein Guard / Catch-all). */
  sig: string;
  guard: TransitionDef['guard'] | null;
  op: string;
  value: string;
  /** Indizes der zugehörigen Übergänge im `transitions`-Array. */
  indices: number[];
}

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
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    CheckboxComponent,
    SelectComponent,
    GuardEditorComponent,
  ],
  templateUrl: './flow-editor.component.html',
  styleUrl: './flow-editor.component.scss',
})
export class FlowEditorComponent {
  private readonly api = inject(AdminApiService);
  private readonly options = inject(AdminOptionsService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly canvas = viewChild<ElementRef<SVGSVGElement>>('canvas');

  protected readonly actionTypes = ACTION_TYPES;
  protected readonly compareOps = COMPARE_OPS;

  /** State-Arten (#28-Redesign): nur noch normal + vote. */
  protected readonly stateKinds: StateKind[] = ['normal', 'vote'];
  /** Gremien + globale Rollen für Config + Guards/Actions. */
  protected readonly gremiumOptions = signal<SelectOption[]>([]);
  protected readonly globalRoleOptions = signal<SelectOption[]>([]);
  /** Konfigurierte Webhooks (für die `webhook`-Action). */
  protected readonly webhookOptions = signal<SelectOption[]>([]);
  /** Benannte Deadline-Policies (#13) — ein State kann eine per Schlüssel referenzieren. */
  protected readonly deadlinePolicyOptions = signal<SelectOption[]>([]);

  protected readonly graph = signal<FlowGraph>(autoLayout(blankGraph()));

  /** Undo/Redo-Historie über Graph-Snapshots (#flow-shortcuts). */
  private undoStack: FlowGraph[] = [];
  private redoStack: FlowGraph[] = [];
  private lastGraph: FlowGraph = this.graph();
  private applyingHistory = false;
  /** Reaktive Verfügbarkeit für die Toolbar-Buttons. */
  protected readonly canUndo = signal(false);
  protected readonly canRedo = signal(false);

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
  /** Branch (pass/fail), wenn von einem Branch-Punkt gezogen wird. */
  private connectBranch: string | null = null;
  /** Guard des Ausgangs-Punkts, von dem gezogen wird (geerbt vom neuen Übergang). */
  private connectGuard: TransitionDef['guard'] | null = null;

  /**
   * Sichtfenster (Zoom/Pan) in Welt-Koordinaten. ``null`` = ganzer Inhalt (Fit).
   * Gesteuert via Mausrad (Zoom am Cursor) + Ziehen auf leerer Fläche (Pan);
   * ``toSvg`` rechnet über ``getScreenCTM`` automatisch korrekt (Drag bleibt exakt).
   */
  protected readonly view = signal<{ x: number; y: number; w: number; h: number } | null>(null);
  /** Welt-Punkt unter dem Cursor beim Pan-Start (bleibt fix »unter dem Finger«). */
  private panGrab: { x: number; y: number } | null = null;

  constructor() {
    // Globaler Flow (#28): den aktiven globalen Flow laden, falls vorhanden, sonst
    // mit leerem Graphen starten.
    this.api
      .getGlobalFlow()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (graph) => {
          if (graph && graph.states?.length) {
            // Initiales Laden ist kein Undo-Schritt.
            this.applyingHistory = true;
            this.graph.set(autoLayout(normalizeFlowGraph(graph)));
          }
        },
        error: () => undefined,
      });
    // Gremien für vote-State-Config + Committee-Guards/Actions.
    this.options
      .gremiumOptions()
      .pipe(takeUntilDestroyed())
      .subscribe({ next: (o) => this.gremiumOptions.set(o), error: () => undefined });
    // Globale Rollen für roleIs/applicantRoleIs-Guards.
    this.api
      .listRoles()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (roles) =>
          this.globalRoleOptions.set(
            roles.map((r) => ({ value: r.key, label: `${r.label['de'] ?? r.key} (${r.key})` })),
          ),
        error: () => undefined,
      });
    // Konfigurierte Webhooks für die `webhook`-Action.
    this.api
      .listWebhooks()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (hooks) =>
          this.webhookOptions.set(hooks.map((h) => ({ value: h.id, label: h.name || h.url }))),
        error: () => undefined,
      });
    // Benannte Deadline-Policies (#13): pro State referenzierbar per Schlüssel.
    this.api
      .listDeadlinePolicies()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (policies) =>
          this.deadlinePolicyOptions.set(
            policies.map((p) => ({ value: p.key, label: `${p.label['de'] ?? p.key} (${p.key})` })),
          ),
        error: () => undefined,
      });

    // Strukturelle Graph-Änderungen (States/Transitions, nicht reine Positionen)
    // als Undo-Schritt festhalten — Knoten-Verschiebungen fluten die Historie nicht.
    effect(() => {
      const g = this.graph();
      if (this.applyingHistory) {
        this.applyingHistory = false;
        this.lastGraph = g;
        return;
      }
      if (g === this.lastGraph) return;
      if (structuralKey(g) !== structuralKey(this.lastGraph)) {
        this.undoStack.push(this.lastGraph);
        if (this.undoStack.length > 100) this.undoStack.shift();
        this.redoStack = [];
        this.syncHistoryFlags();
      }
      this.lastGraph = g; // auch bei Layout-only-Änderungen mitziehen
    });
  }

  private syncHistoryFlags(): void {
    this.canUndo.set(this.undoStack.length > 0);
    this.canRedo.set(this.redoStack.length > 0);
  }

  /** Gültige Ergebnis-Zweige je Quell-State-Art (#28): vote→pass/fail, sonst keine. */
  protected branchesFor(fromKey: string): TransitionBranch[] {
    return this.stateByKey(fromKey)?.kind === 'vote' ? ['pass', 'fail'] : [];
  }

  protected readonly validation = computed(() => validateFlowGraph(this.graph()));
  protected readonly json = computed(() => serializeFlowGraph(this.graph()));

  /** Knoten-Positionen (Top-Left) aus dem Layout. */
  private readonly positions = computed(() => this.graph().layout?.positions ?? {});

  protected readonly nodes = computed(() => {
    const pos = this.positions();
    const sel = this.selection();
    const transitions = this.graph().transitions ?? [];
    return this.graph().states.map((s) => {
      const branches = this.branchDotsFor(s.kind);
      // vote/approval: ein beschrifteter Punkt je Branch (pass/fail bzw. accept/
      // reject). Sonst: ein Punkt je unterschiedlichem Guard (+ Default-Punkt zum
      // Aufziehen neuer, guard-loser Kanten).
      const dots = branches.length
        ? branches.map((b, i) => ({
            id: b,
            branch: b as string | null,
            guard: null as TransitionDef['guard'] | null,
            cy: this.dotY(i, branches.length),
            label: b,
          }))
        : this.outDots(s.key, transitions).map((gp, i, arr) => ({
            id: gp.sig || 'out',
            branch: null as string | null,
            // Beim Aufziehen vom Guard-Punkt erbt der neue Übergang dessen Guard.
            guard: gp.guard ?? null,
            cy: this.dotY(i, arr.length),
            label: gp.sig ? this.guardGroupLabel(gp) : '',
          }));
      return {
        key: s.key,
        label: this.label(s),
        kind: s.kind ?? 'normal',
        color: s.color ?? null,
        isInitial: !!s.isInitial,
        selected: sel?.kind === 'state' && sel.key === s.key,
        x: pos[s.key]?.x ?? 0,
        y: pos[s.key]?.y ?? 0,
        dots,
      };
    });
  });

  private branchDotsFor(kind: string | null | undefined): string[] {
    return kind === 'vote' ? ['pass', 'fail'] : [];
  }

  /** Ausgehende Übergänge nach Guard gruppieren, in Array-(=Prioritäts-)Reihenfolge. */
  private groupsOf(transitions: readonly TransitionDef[], fromKey: string): GuardGroup[] {
    const bySig = new Map<string, GuardGroup>();
    const order: GuardGroup[] = [];
    transitions.forEach((t, index) => {
      if (t.from !== fromKey) return;
      const sig = t.guard ? JSON.stringify(t.guard) : '';
      let g = bySig.get(sig);
      if (!g) {
        g = {
          sig,
          guard: t.guard ?? null,
          op: t.guard ? Object.keys(t.guard)[0] : '',
          value: t.guard ? String(Object.values(t.guard)[0] ?? '') : '',
          indices: [],
        };
        bySig.set(sig, g);
        order.push(g);
      }
      g.indices.push(index);
    });
    return order;
  }

  /** Ausgangs-Punkte eines normalen Knotens: je Guard-Gruppe einer, plus ein
   *  Default-Punkt (Catch-all) zum Zeichnen neuer Kanten, falls keiner existiert. */
  private outDots(fromKey: string, transitions: readonly TransitionDef[]): GuardGroup[] {
    const groups = this.groupsOf(transitions, fromKey);
    if (!groups.some((g) => g.sig === '')) {
      groups.push({ sig: '', guard: null, op: '', value: '', indices: [] });
    }
    return groups;
  }

  /** Guard-Gruppen eines Knotens für die Prioritäts-Liste im Inspektor (#8). */
  protected guardGroupsFor(fromKey: string): GuardGroup[] {
    return this.groupsOf(this.graph().transitions ?? [], fromKey);
  }

  /** Klarname einer Guard-Gruppe (Operator + Wert; leer = Catch-all). */
  protected guardGroupLabel(g: GuardGroup): string {
    if (!g.sig) return this.i18n.translate('admin.flow.guardDefault');
    const opLabel = this.i18n.translate(`admin.flow.guardOp.${g.op}` as TranslationKey);
    return g.value ? `${opLabel}: ${g.value}` : opLabel;
  }

  /** Guard-Gruppe im Prioritäts-Stack nach oben/unten schieben (#8). Schreibt die
   *  `order`-Felder neu, sodass die Array-Reihenfolge der Auswertung entspricht. */
  protected moveGuardUp(fromKey: string, sig: string): void {
    this.reorderGuard(fromKey, sig, -1);
  }
  protected moveGuardDown(fromKey: string, sig: string): void {
    this.reorderGuard(fromKey, sig, 1);
  }

  private reorderGuard(fromKey: string, sig: string, dir: -1 | 1): void {
    this.graph.update((g) => {
      const all = g.transitions ?? [];
      const groups = this.groupsOf(all, fromKey);
      const gi = groups.findIndex((x) => x.sig === sig);
      const ni = gi + dir;
      if (gi < 0 || ni < 0 || ni >= groups.length) return g;
      [groups[gi], groups[ni]] = [groups[ni], groups[gi]];
      const outgoing = groups.flatMap((grp) => grp.indices.map((i) => all[i]));
      const others = all.filter((t) => t.from !== fromKey);
      const next = [...others, ...outgoing].map((t, i) => ({ ...t, order: i }));
      return { ...g, transitions: next };
    });
  }

  private dotY(i: number, n: number): number {
    if (n <= 1) return NODE_H / 2;
    // Punkte gleichmäßig über die Knotenhöhe verteilen (Rand-Abstand 12px).
    const top = 12;
    const span = NODE_H - 2 * top;
    return top + (span * i) / (n - 1);
  }

  protected readonly edges = computed(() => {
    const pos = this.positions();
    const sel = this.selection();
    const transitions = this.graph().transitions ?? [];
    const kindOf = new Map(this.graph().states.map((s) => [s.key, s.kind] as const));
    return transitions
      .map((t, index) => ({ t, index }))
      .filter(({ t }) => pos[t.from] && pos[t.to])
      .map(({ t, index }) => {
        const a = pos[t.from];
        const b = pos[t.to];
        const x1 = a.x + NODE_W;
        // Start am Ausgangs-Punkt: Branch (pass/fail …) bzw. dem Guard-Punkt (#8).
        const y1 = a.y + this.outDotYFor(t.from, kindOf.get(t.from), t, transitions);
        const x2 = b.x;
        const y2 = b.y + NODE_H / 2;
        return {
          index,
          x1,
          y1,
          x2,
          y2,
          d: this.edgePath(x1, y1, x2, y2),
          mx: (x1 + x2) / 2,
          my: (y1 + y2) / 2,
          label: t.label?.['de'] ?? '',
          automatic: !!t.automatic,
          selected: sel?.kind === 'transition' && sel.index === index,
        };
      });
  });

  /** Y-Offset des Ausgangs-Punkts für einen (ggf. Branch-)Übergang innerhalb des Knotens. */
  private branchDotY(kind: string | null | undefined, branch: TransitionBranch | null | undefined): number {
    const dots = this.branchDotsFor(kind);
    const i = branch ? dots.indexOf(branch) : -1;
    return i >= 0 ? this.dotY(i, dots.length) : NODE_H / 2;
  }

  /** Y-Offset des Ausgangs-Punkts: Branch-Punkt (vote/approval) bzw. der zum Guard
   *  des Übergangs gehörende Punkt (normale Knoten, #8). */
  private outDotYFor(
    fromKey: string,
    kind: string | null | undefined,
    t: TransitionDef,
    transitions: readonly TransitionDef[],
  ): number {
    if (this.branchDotsFor(kind).length) return this.branchDotY(kind, t.branch);
    const dots = this.outDots(fromKey, transitions);
    const sig = t.guard ? JSON.stringify(t.guard) : '';
    const i = dots.findIndex((g) => g.sig === sig);
    return this.dotY(i < 0 ? dots.length - 1 : i, dots.length);
  }

  /** Glatte (kubische Bézier) horizontale Kante zwischen zwei Punkten. */
  private edgePath(x1: number, y1: number, x2: number, y2: number): string {
    const dx = Math.max(Math.abs(x2 - x1) * 0.5, 30);
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  }

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
  protected readonly viewBox = computed(() => {
    const v = this.view();
    return v ? `${v.x} ${v.y} ${v.w} ${v.h}` : `0 0 ${this.canvasW()} ${this.canvasH()}`;
  });

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

  protected kindLabel(k: string): string {
    return this.i18n.translate(`admin.flow.kind.${k}` as TranslationKey);
  }

  /** Von/Nach-Optionen als „Klarname (key)" (FE5). */
  protected stateOptions(): SelectOption[] {
    return this.graph().states.map((s) => ({ value: s.key, label: `${this.label(s)} (${s.key})` }));
  }

  /** Guard-Operatoren mit übersetztem Klarnamen. Akteur-Gates (roleIs/isInCommittee)
   *  nur auf **manuellen** Übergängen — automatische bekommen nur Bedingungen (#28). */
  protected guardOpOptions(automatic: boolean | undefined): SelectOption[] {
    const ops: readonly string[] = automatic
      ? GUARD_CONDITION_OPERATORS
      : [...GUARD_CONDITION_OPERATORS, ...GUARD_ACTOR_OPERATORS];
    return ops.map((op) => ({
      value: op,
      label: this.i18n.translate(`admin.flow.guardOp.${op}` as TranslationKey),
    }));
  }

  /** Vergleichs-Operatoren des `compare`-Guards als Dropdown. */
  protected compareOpOptions(): SelectOption[] {
    return this.compareOps.map((op) => ({ value: op, label: op }));
  }

  /** Empfänger-Arten einer `notify`-Action als Dropdown. */
  protected recipientKindOptions(): SelectOption[] {
    return NOTIFY_RECIPIENT_KINDS.map((k) => ({
      value: k,
      label: this.i18n.translate(`admin.flow.recipientKind.${k}` as TranslationKey),
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

  /**
   * Art des Wert-Controls je Guard-Operator (#28):
   * - `none`      → boolesche Operatoren (deadlinePassed/budgetFitsApplication)
   * - `role`      → roleIs/applicantRoleIs → globale-Rollen-Dropdown
   * - `committee` → isInCommittee/applicantCommitteeIs → Gremium-Dropdown
   * - `compare`   → typisierter Vergleich (Feld + Operator + Wert)
   * - `text`      → budgetIs/hasField → Freitext
   */
  protected guardValueKind(op: string): 'none' | 'role' | 'committee' | 'compare' | 'text' {
    if (op === 'deadlinePassed' || op === 'budgetFitsApplication' || !op) return 'none';
    if (op === 'roleIs' || op === 'applicantRoleIs') return 'role';
    if (op === 'isInCommittee' || op === 'applicantCommitteeIs') return 'committee';
    if (op === 'compare') return 'compare';
    return 'text';
  }

  /** Annotation/Hinweis für das Guard-Wertfeld je Operator. */
  protected guardValueHint(op: string): string {
    return this.i18n.translate(`admin.flow.guardHint.${op}` as TranslationKey);
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

  protected setStateColor(key: string, color: string): void {
    this.graph.update((g) => ({
      ...g,
      states: g.states.map((s) => (s.key === key ? { ...s, color: color || null } : s)),
    }));
  }

  protected setStateEditAllowed(key: string, on: boolean): void {
    this.graph.update((g) => ({
      ...g,
      states: g.states.map((s) => (s.key === key ? { ...s, editAllowed: on } : s)),
    }));
  }

  // --- state kind + config (#28) -------------------------------------------
  private patchState(key: string, patch: Partial<StateDef>): void {
    this.graph.update((g) => ({
      ...g,
      states: g.states.map((s) => (s.key === key ? { ...s, ...patch } : s)),
    }));
  }

  protected setStateKind(key: string, kind: string): void {
    const k = (kind || 'normal') as StateKind;
    // Beim Wechsel der Art kind-spezifische Config zurücksetzen (Deadline behalten).
    const policy = this.stateByKey(key)?.config?.deadlinePolicyKey;
    const config: StateConfig = policy ? { deadlinePolicyKey: policy } : {};
    this.patchState(key, { kind: k === 'normal' ? null : k, config });
  }

  private patchConfig(key: string, patch: Partial<StateConfig>): void {
    this.graph.update((g) => ({
      ...g,
      states: g.states.map((s) =>
        s.key === key ? { ...s, config: { ...(s.config ?? {}), ...patch } } : s,
      ),
    }));
  }

  protected setStateGremium(key: string, gremiumId: string): void {
    this.patchConfig(key, { gremiumId: gremiumId || undefined });
  }

  /** Deadline-Policy eines States setzen/entfernen (#13). */
  protected setStateDeadlinePolicy(key: string, policyKey: string): void {
    this.patchConfig(key, { deadlinePolicyKey: policyKey || undefined });
  }

  private stateByKey(key: string): StateDef | undefined {
    return this.graph().states.find((s) => s.key === key);
  }

  protected setTransitionBranch(index: number, branch: string): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) =>
        idx === index ? { ...t, branch: (branch || null) as TransitionBranch | null } : t,
      ),
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

  /** Ganzen Guard-Baum eines Übergangs setzen (rekursiver Editor, #28). */
  protected setGuard(index: number, guard: Guard | null): void {
    this.patchTransition(index, (t) => {
      if (!guard) {
        const next = { ...t };
        delete next.guard;
        return next;
      }
      return { ...t, guard };
    });
  }

  /** Operator wählen → Guard mit sinnvollem Default initialisieren (leer = kein Guard). */
  protected setGuardOp(index: number, op: string): void {
    this.patchTransition(index, (t) => {
      if (!op) {
        const next = { ...t };
        delete next.guard;
        return next;
      }
      return { ...t, guard: this.defaultGuard(op as GuardLeafOperator) };
    });
  }

  private defaultGuard(op: GuardLeafOperator): Record<string, unknown> {
    if (op === 'deadlinePassed' || op === 'budgetFitsApplication') return { [op]: true };
    if (op === 'compare') return { compare: { field: '', op: '==', value: '' } };
    return { [op]: '' };
  }

  /** Einwertiger Guard-Wert (role/committee/budgetIs/hasField). */
  protected setGuardValue(index: number, value: string): void {
    this.patchTransition(index, (t) => {
      const op = this.guardOp(t);
      return op ? { ...t, guard: { [op]: value } } : t;
    });
  }

  /** Boolescher Guard-Wert (deadlinePassed/budgetFitsApplication). */
  protected setGuardBool(index: number, on: boolean): void {
    this.patchTransition(index, (t) => {
      const op = this.guardOp(t);
      return op ? { ...t, guard: { [op]: on } } : t;
    });
  }

  protected guardOp(t: TransitionDef): string {
    return t.guard ? Object.keys(t.guard)[0] : '';
  }

  protected guardValue(t: TransitionDef): string {
    if (!t.guard) return '';
    const v = Object.values(t.guard)[0];
    return v == null || typeof v === 'object' ? '' : String(v);
  }

  protected guardBool(t: TransitionDef): boolean {
    return !!(t.guard && Object.values(t.guard)[0] === true);
  }

  // --- compare-Guard -------------------------------------------------------
  private compareSpec(t: TransitionDef): { field: string; op: string; value: unknown } {
    const c = t.guard?.['compare'];
    return typeof c === 'object' && c !== null
      ? (c as { field: string; op: string; value: unknown })
      : { field: '', op: '==', value: '' };
  }
  protected compareField(t: TransitionDef): string {
    return String(this.compareSpec(t).field ?? '');
  }
  protected compareOp(t: TransitionDef): string {
    return String(this.compareSpec(t).op ?? '==');
  }
  protected compareValue(t: TransitionDef): string {
    const v = this.compareSpec(t).value;
    return v == null ? '' : Array.isArray(v) ? v.join(', ') : String(v);
  }
  protected setCompare(index: number, patch: { field?: string; op?: string; value?: string }): void {
    this.patchTransition(index, (t) => {
      const cur = this.compareSpec(t);
      const op = patch.op ?? cur.op;
      let value: unknown = patch.value ?? cur.value;
      // `in` erwartet eine Liste — Komma-getrennte Eingabe splitten.
      if (op === 'in' && typeof value === 'string') {
        value = value.split(',').map((s) => s.trim()).filter(Boolean);
      }
      return {
        ...t,
        guard: { compare: { field: patch.field ?? cur.field, op: op as CompareOp, value } },
      };
    });
  }

  // --- actions -------------------------------------------------------------
  protected addAction(index: number, type: string): void {
    if (!type) return;
    const initial: ActionDef =
      type === 'notify'
        ? { type: 'notify', recipients: [] }
        : ({ type: type as ActionType } as ActionDef);
    this.patchTransition(index, (t) => ({ ...t, actions: [...(t.actions ?? []), initial] }));
  }

  /** Einen Parameter einer Action setzen (webhookId/gremiumId/budgetId). */
  protected setActionParam(index: number, ai: number, key: string, value: string): void {
    this.patchTransition(index, (t) => ({
      ...t,
      actions: (t.actions ?? []).map((a, k) => (k === ai ? { ...a, [key]: value } : a)),
    }));
  }

  protected actionParam(act: ActionDef, key: string): string {
    const v = act[key];
    return typeof v === 'string' ? v : '';
  }

  // --- notify-Empfänger ----------------------------------------------------
  protected recipientsOf(act: ActionDef): NotifyRecipient[] {
    return Array.isArray(act['recipients']) ? (act['recipients'] as NotifyRecipient[]) : [];
  }
  private patchRecipients(
    index: number,
    ai: number,
    fn: (list: NotifyRecipient[]) => NotifyRecipient[],
  ): void {
    this.patchTransition(index, (t) => ({
      ...t,
      actions: (t.actions ?? []).map((a, k) =>
        k === ai ? { ...a, recipients: fn(this.recipientsOf(a)) } : a,
      ),
    }));
  }
  protected addRecipient(index: number, ai: number): void {
    this.patchRecipients(index, ai, (list) => [...list, { kind: 'applicant' }]);
  }
  protected removeRecipient(index: number, ai: number, ri: number): void {
    this.patchRecipients(index, ai, (list) => list.filter((_, i) => i !== ri));
  }
  protected setRecipientKind(index: number, ai: number, ri: number, kind: string): void {
    this.patchRecipients(index, ai, (list) =>
      list.map((r, i) =>
        i === ri ? { kind: kind as NotifyRecipientKind, ref: kind === 'applicant' ? undefined : (r.ref ?? '') } : r,
      ),
    );
  }
  protected setRecipientRef(index: number, ai: number, ri: number, ref: string): void {
    this.patchRecipients(index, ai, (list) =>
      list.map((r, i) => (i === ri ? { ...r, ref } : r)),
    );
  }
  /** Braucht die Empfänger-Art einen `ref` (Gremium/Rolle/E-Mail)? */
  protected recipientNeedsRef(kind: string): boolean {
    return kind === 'gremium' || kind === 'role' || kind === 'email';
  }

  private patchTransition(index: number, fn: (t: TransitionDef) => TransitionDef): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) => (idx === index ? fn(t) : t)),
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

  // --- Undo/Redo + Tastatur (#flow-shortcuts) ------------------------------
  protected undo(): void {
    const prev = this.undoStack.pop();
    if (prev === undefined) return;
    this.redoStack.push(this.graph());
    this.applyingHistory = true;
    this.graph.set(prev);
    this.selection.set(null);
    this.syncHistoryFlags();
  }

  protected redo(): void {
    const next = this.redoStack.pop();
    if (next === undefined) return;
    this.undoStack.push(this.graph());
    this.applyingHistory = true;
    this.graph.set(next);
    this.selection.set(null);
    this.syncHistoryFlags();
  }

  /** Ausgewählten Knoten/Kante löschen (Del/Backspace). */
  protected deleteSelected(): void {
    const sel = this.selection();
    if (sel?.kind === 'state') this.removeSelectedState();
    else if (sel?.kind === 'transition') this.removeSelectedTransition();
  }

  /**
   * Editor-Tastenkürzel: Entf/Rück = Auswahl löschen, Einfg = State hinzufügen,
   * Strg+Z = Undo, Strg+Y / Strg+Shift+Z = Redo. In Eingabefeldern inaktiv
   * (außer Undo/Redo), damit normales Tippen unberührt bleibt.
   */
  @HostListener('document:keydown', ['$event'])
  protected onKeydown(event: KeyboardEvent): void {
    const target = event.target as HTMLElement | null;
    const tag = target?.tagName;
    const typing =
      tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || !!target?.isContentEditable;
    const mod = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();

    if (mod && key === 'z' && !event.shiftKey) {
      event.preventDefault();
      this.undo();
      return;
    }
    if (mod && (key === 'y' || (key === 'z' && event.shiftKey))) {
      event.preventDefault();
      this.redo();
      return;
    }
    if (typing) return;
    if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      this.deleteSelected();
      return;
    }
    if (event.key === 'Insert') {
      event.preventDefault();
      this.addState();
    }
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

  /** Vom Verbindungs-Punkt eines Knotens eine neue Kante aufziehen. Ein Branch-/
   *  Guard-Punkt überträgt seinen Branch bzw. Guard auf den neuen Übergang. */
  protected onConnectPointerDown(
    event: PointerEvent,
    key: string,
    branch: string | null = null,
    guard: TransitionDef['guard'] | null = null,
  ): void {
    event.stopPropagation();
    this.connectFrom = key;
    this.connectBranch = branch;
    this.connectGuard = guard;
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
      return;
    }
    if (this.panGrab) {
      // Welt-Punkt unter dem Cursor wieder auf ``panGrab`` schieben.
      const now = this.toSvg(event);
      const v = this.ensureView();
      this.view.set({ ...v, x: v.x + (this.panGrab.x - now.x), y: v.y + (this.panGrab.y - now.y) });
    }
  }

  protected onCanvasPointerUp(event: PointerEvent): void {
    if (this.panGrab) {
      this.panGrab = null;
      return;
    }
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
        const branch = this.connectBranch as TransitionBranch | null;
        const guard = this.connectGuard;
        const t: TransitionDef = blankTransition(from, target);
        if (branch) t.branch = branch;
        if (guard) t.guard = guard;
        this.graph.update((g) => ({ ...g, transitions: [...(g.transitions ?? []), t] }));
        this.selection.set({ kind: 'transition', index: (this.graph().transitions?.length ?? 1) - 1 });
      }
      this.connectFrom = null;
      this.connectBranch = null;
      this.connectGuard = null;
      this.tempEdge.set(null);
    }
  }

  protected selectEdge(index: number): void {
    this.selection.set({ kind: 'transition', index });
  }

  protected clearSelection(): void {
    if (!this.drag && !this.connectFrom) this.selection.set(null);
  }

  // --- Zoom & Pan ----------------------------------------------------------
  /** Aktuelles Sichtfenster (initialisiert es beim ersten Zoom/Pan auf »ganzer Inhalt«). */
  private ensureView(): { x: number; y: number; w: number; h: number } {
    const v = this.view();
    if (v) return v;
    const init = { x: 0, y: 0, w: this.canvasW(), h: this.canvasH() };
    this.view.set(init);
    return init;
  }

  /** Mausrad: Zoom um den Cursor (Welt-Punkt unter dem Cursor bleibt fix). */
  protected onWheel(event: WheelEvent): void {
    event.preventDefault();
    const v = this.ensureView();
    const c = this.toSvg(event);
    const factor = event.deltaY > 0 ? 1.12 : 1 / 1.12; // runter = rauszoomen
    this.applyZoom(v, factor, c);
  }

  protected zoomIn(): void {
    const v = this.ensureView();
    this.applyZoom(v, 1 / 1.2, { x: v.x + v.w / 2, y: v.y + v.h / 2 });
  }

  protected zoomOut(): void {
    const v = this.ensureView();
    this.applyZoom(v, 1.2, { x: v.x + v.w / 2, y: v.y + v.h / 2 });
  }

  /** Zoom/Fit zurücksetzen (ganzer Inhalt). */
  protected resetView(): void {
    this.view.set(null);
  }

  private applyZoom(
    v: { x: number; y: number; w: number; h: number },
    factor: number,
    center: { x: number; y: number },
  ): void {
    // Zoom relativ zur Inhalts-Breite begrenzen (0.2×…6×).
    const base = this.canvasW();
    const minW = base / 6;
    const maxW = base * 5;
    const w = Math.min(maxW, Math.max(minW, v.w * factor));
    const ratio = w / v.w;
    const h = v.h * ratio;
    // Welt-Punkt ``center`` bleibt an derselben Bildschirmstelle.
    const x = center.x - (center.x - v.x) * ratio;
    const y = center.y - (center.y - v.y) * ratio;
    this.view.set({ x, y, w, h });
  }

  /** Pointerdown auf leerer Fläche: Auswahl leeren + Pan starten. */
  protected onCanvasPointerDown(event: PointerEvent): void {
    this.clearSelection();
    this.panGrab = this.toSvg(event);
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
  }

  /** Client-Koordinaten → SVG-User-Space (für Drag/Connect/Zoom-Mathematik). */
  private toSvg(event: MouseEvent): { x: number; y: number } {
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
    const v = this.validation();
    if (!v.valid) {
      // Konkrete Meldung statt generisch (z. B. „vote-State braucht pass+fail").
      this.toast.error(v.errors[0] ?? this.i18n.translate('admin.common.invalid'));
      return;
    }
    const graph = normalizeFlowGraph(autoLayout(this.graph()));
    this.api.createGlobalFlowVersion(graph).subscribe({
      next: () => this.toast.success(this.i18n.translate('admin.common.saved')),
      error: (err: { error?: { detail?: string } }) =>
        this.toast.error(err?.error?.detail ?? this.i18n.translate('admin.common.saveFailed')),
    });
  }
}

/** Strukturelle Signatur (ohne Layout): zwei Graphen sind „gleich", wenn sich nur
 *  Knoten-Positionen unterscheiden — solche Änderungen sind kein Undo-Schritt. */
function structuralKey(g: FlowGraph): string {
  return JSON.stringify([g.states, g.transitions]);
}

function blankGraph(): FlowGraph {
  return { states: [], transitions: [] };
}

/** Eindeutigen State-Key erzeugen (`state`, `state2`, …). */
function uniqueKey(base: string, states: StateDef[]): string {
  const used = new Set(states.map((s) => s.key));
  if (!used.has(base)) return base;
  let i = 2;
  while (used.has(`${base}${i}`)) i++;
  return `${base}${i}`;
}
