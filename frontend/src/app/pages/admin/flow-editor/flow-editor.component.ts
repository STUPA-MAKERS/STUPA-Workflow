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
import { VersionHistoryComponent } from '../version-history/version-history.component';
import { AdminOptionsService } from '../admin-options.service';
import {
  ACTION_TYPES,
  type ActionDef,
  type ActionType,
  COMPARE_OPS,
  type CompareOp,
  type FlowGraph,
  type FlowGroup,
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
  layoutEntities,
  normalizeFlowGraph,
  serializeFlowGraph,
  validateFlowGraph,
} from '../flow-graph.util';
import { type BudgetTreeNode, BudgetTreeApi } from '../../budget/budget-tree.api';

/** Aktuelle Auswahl im Canvas: State (per key) oder Transition (per Index).
 *  Gruppen werden nicht selektiert — Klick öffnet sie (Drill-Down), ihre
 *  Einstellungen zeigt der Inspektor der geöffneten Ebene. */
type Selection =
  | { kind: 'state'; key: string }
  | { kind: 'transition'; index: number }
  | null;

/** Gruppen-Kasten im Canvas (#flow-groups): EIN Kasten je (Unter-)Gruppe der
 *  aktuellen Drill-Down-Ebene; wächst in der Höhe mit den Ausgangs-Punkten. */
interface GroupBox {
  id: string;
  name: string;
  color: string | null;
  multi: boolean;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Anzahl transitiv enthaltener States (Badge). */
  count: number;
  /** Transitiv enthaltene State-Keys (Drag verschiebt sie alle). */
  deepKeys: string[];
  /** Anzahl Ausgangs-Punkte (ausgehende Grenz-Kanten). */
  outCount: number;
  /** Y-Offsets der Ausgangs-Punkte (fester Abstand, zentriert). */
  outDotYs: number[];
}

/** Sichtbares Ende einer Kante auf der aktuellen Ebene (#flow-groups). */
type EndRef =
  | { type: 'state'; key: string }
  | { type: 'group'; id: string }
  | { type: 'proxy'; pid: string };

/** Proxy-Knoten im Drill-Down: externe Quelle (links) bzw. Ziel (rechts). */
interface ProxyBox {
  /** Stabile Id: `state:<key>` | `group:<id>`. */
  pid: string;
  label: string;
  isGroup: boolean;
  x: number;
  y: number;
}

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

/** Ausgangs-Punkte (#flow-quirks): FESTER Abstand statt Verteilung über die
 *  Knotenhöhe — Knoten/Gruppen wachsen bei vielen Punkten in die Höhe. */
const DOT_GAP = 22;
const DOT_PAD = 16;

/** Gruppen-Kasten-Geometrie (#flow-groups). */
const GROUP_W = 180;
const GROUP_H = 64;

/** Proxy-Knoten im Drill-Down: externe Quellen links, Ziele rechts. */
const PROXY_W = 150;
const PROXY_H = 44;
const PROXY_GAP = 78;
const PROXY_COL_GAP = 240;

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
    VersionHistoryComponent,
  ],
  templateUrl: './flow-editor.component.html',
  styleUrl: './flow-editor.component.scss',
})
export class FlowEditorComponent {
  private readonly api = inject(AdminApiService);
  private readonly options = inject(AdminOptionsService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  private readonly budgetApi = inject(BudgetTreeApi);

  protected readonly canvas = viewChild<ElementRef<SVGSVGElement>>('canvas');
  /** Versions-Sidebar — nach Save neu laden. */
  protected readonly history = viewChild(VersionHistoryComponent);

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
  /** Drill-Down-Kontext (#flow-groups): geöffnete Gruppe; null = oberste Ebene. */
  protected readonly currentGroupId = signal<string | null>(null);
  /** Mehrfachauswahl (Shift-Klick) für »Gruppe erstellen« — States + Gruppen. */
  protected readonly multiSel = signal<ReadonlySet<string>>(new Set());
  protected readonly multiSelGroups = signal<ReadonlySet<string>>(new Set());
  /** Kostenstellen-Namen (id → »Name (key)«) zum Auflösen von `budgetIs`-Guards (#7). */
  private readonly budgetNameById = signal<ReadonlyMap<string, string>>(new Map());
  /** Temporäre Kante während des Aufziehens eines neuen Übergangs. */
  protected readonly tempEdge = signal<{ x1: number; y1: number; x2: number; y2: number } | null>(
    null,
  );

  protected readonly NODE_W = NODE_W;
  protected readonly NODE_H = NODE_H;

  private drag: { key: string; dx: number; dy: number; moved: boolean } | null = null;
  /** Gruppen-Drag (#flow-groups): verschiebt alle Member-Positionen gemeinsam. */
  private groupDrag: { id: string; lastX: number; lastY: number; moved: boolean } | null = null;
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
        // Kerndaten des Editors: Fehler sichtbar machen statt leerer Canvas (#5-2).
        error: () => this.toast.error(this.i18n.translate('admin.flow.loadFailed')),
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
    // Kostenstellen-Baum (#7): `budgetIs`-Guards im Canvas mit Namen statt UUID anzeigen.
    this.budgetApi
      .tree()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (roots) => {
          const map = new Map<string, string>();
          const walk = (nodes: BudgetTreeNode[]): void => {
            for (const n of nodes) {
              map.set(n.id, `${n.name} (${n.key})`);
              if (n.children?.length) walk(n.children);
            }
          };
          walk(roots);
          this.budgetNameById.set(map);
        },
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

    // Drill-Down-Kontext darf nie auf eine gelöschte Gruppe zeigen (Undo/Redo,
    // Auflösen aus anderem Pfad) — dann zurück auf die oberste Ebene.
    effect(() => {
      const id = this.currentGroupId();
      if (id && !this.groupById().has(id)) this.currentGroupId.set(null);
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

  /** Größe der Mehrfachauswahl (States + Gruppen) für den Toolbar-Button. */
  protected readonly multiCount = computed(
    () => this.multiSel().size + this.multiSelGroups().size,
  );

  protected readonly validation = computed(() => validateFlowGraph(this.graph()));
  protected readonly json = computed(() => serializeFlowGraph(this.graph()));

  /** Knoten-Positionen (Top-Left) aus dem Layout. */
  private readonly positions = computed(() => this.graph().layout?.positions ?? {});

  // --- Gruppen (#flow-groups) — reine Darstellung, Engine unberührt ----------
  protected readonly groups = computed(() => this.graph().layout?.groups ?? []);

  private readonly groupById = computed(() => new Map(this.groups().map((g) => [g.id, g])));

  /** Parent-Beziehung der Gruppen (Kind-Id → Parent-Id) aus `groupIds`. */
  private readonly parentGroupId = computed(() => {
    const map = new Map<string, string>();
    for (const g of this.groups()) {
      for (const child of g.groupIds ?? []) map.set(child, g.id);
    }
    return map;
  });

  /** Direkter Besitzer eines States (Gruppen-Id) — fehlt ⇒ oberste Ebene. */
  private readonly stateOwnerId = computed(() => {
    const map = new Map<string, string>();
    for (const g of this.groups()) {
      for (const k of g.stateKeys) map.set(k, g.id);
    }
    return map;
  });

  /** Aktuell geöffnete Gruppe (Drill-Down); undefined auf der obersten Ebene
   *  oder wenn die Gruppe inzwischen weg ist (Undo). */
  protected readonly currentGroup = computed<FlowGroup | undefined>(() => {
    const id = this.currentGroupId();
    return id ? this.groupById().get(id) : undefined;
  });

  /** Breadcrumb-Pfad: oberste Ebene … aktuelle Gruppe. */
  protected readonly breadcrumbs = computed<FlowGroup[]>(() => {
    const byId = this.groupById();
    const parents = this.parentGroupId();
    const path: FlowGroup[] = [];
    let id = this.currentGroupId();
    while (id) {
      const g = byId.get(id);
      if (!g) break;
      path.unshift(g);
      id = parents.get(id) ?? null;
    }
    return path;
  });

  /** Transitiv enthaltene State-Keys einer Gruppe (inkl. Unter-Gruppen). */
  private deepStateKeys(groupId: string): string[] {
    const byId = this.groupById();
    const out: string[] = [];
    const seen = new Set<string>();
    const walk = (id: string): void => {
      if (seen.has(id)) return; // Zyklus-Schutz (sollte normalisiert nie vorkommen)
      seen.add(id);
      const g = byId.get(id);
      if (!g) return;
      out.push(...g.stateKeys);
      for (const child of g.groupIds ?? []) walk(child);
    };
    walk(groupId);
    return out;
  }

  /** State auf einer Ebene auflösen: direkt sichtbar ('state'), als Unter-
   *  Gruppen-Kasten ('group') oder außerhalb der Ebene (null → Proxy). */
  private resolveAt(
    stateKey: string,
    ctx: string | null,
  ): { kind: 'state' } | { kind: 'group'; id: string } | null {
    const owner = this.stateOwnerId().get(stateKey) ?? null;
    if (owner === ctx) return { kind: 'state' };
    const parents = this.parentGroupId();
    let g: string | null = owner;
    const guard = new Set<string>();
    while (g !== null && !guard.has(g)) {
      guard.add(g);
      const parent: string | null = parents.get(g) ?? null;
      if (parent === ctx) return { kind: 'group', id: g };
      g = parent;
    }
    return null;
  }

  /** Repräsentant eines EXTERNEN States für die Proxy-Spalten: das, was man auf
   *  der nächsthöheren Ebene von ihm sähe (State selbst oder seine Gruppe). */
  private proxyRefFor(stateKey: string): { pid: string; isGroup: boolean; entityId: string } {
    const parents = this.parentGroupId();
    let ctx = this.currentGroupId();
    while (ctx !== null) {
      ctx = parents.get(ctx) ?? null;
      const r = this.resolveAt(stateKey, ctx);
      if (r) {
        return r.kind === 'state'
          ? { pid: `state:${stateKey}`, isGroup: false, entityId: stateKey }
          : { pid: `group:${r.id}`, isGroup: true, entityId: r.id };
      }
    }
    return { pid: `state:${stateKey}`, isGroup: false, entityId: stateKey };
  }

  /** States der aktuellen Ebene (direkte Mitglieder). */
  private readonly visibleStates = computed(() => {
    const ctx = this.currentGroupId();
    const owner = this.stateOwnerId();
    return this.graph().states.filter((s) => (owner.get(s.key) ?? null) === ctx);
  });

  /** Unter-Gruppen der aktuellen Ebene. */
  private readonly childGroups = computed(() => {
    const ctx = this.currentGroupId();
    const parents = this.parentGroupId();
    return this.groups().filter((g) => (parents.get(g.id) ?? null) === ctx);
  });

  /** Sichtbare Kanten-Enden je Transition (null = auf dieser Ebene unsichtbar:
   *  komplett intern in einer Unter-Gruppe oder komplett extern). */
  private readonly edgeEnds = computed<({ src: EndRef; dst: EndRef } | null)[]>(() => {
    const ctx = this.currentGroupId();
    return (this.graph().transitions ?? []).map((t) => {
      const src = this.resolveAt(t.from, ctx);
      const dst = this.resolveAt(t.to, ctx);
      if (!src && !dst) return null;
      if (src && dst) {
        if (src.kind === 'group' && dst.kind === 'group' && src.id === dst.id) return null;
        if (src.kind === 'state' && dst.kind === 'state' && t.from === t.to) return null;
      }
      const toRef = (r: { kind: 'state' } | { kind: 'group'; id: string } | null, key: string): EndRef =>
        r === null
          ? { type: 'proxy', pid: this.proxyRefFor(key).pid }
          : r.kind === 'state'
            ? { type: 'state', key }
            : { type: 'group', id: r.id };
      return { src: toRef(src, t.from), dst: toRef(dst, t.to) };
    });
  });

  /** Gruppen-Kästen der aktuellen Ebene: Position = Mitte der (unsichtbaren)
   *  Member-BBox, Höhe wächst mit den Ausgangs-Punkten (fixer Abstand). */
  protected readonly groupBoxes = computed<GroupBox[]>(() => {
    const pos = this.positions();
    const ends = this.edgeEnds();
    const multi = this.multiSelGroups();
    return this.childGroups()
      .map((g) => {
        const deepKeys = this.deepStateKeys(g.id);
        const pts = deepKeys.map((k) => pos[k]).filter((p): p is { x: number; y: number } => !!p);
        if (pts.length === 0) return null;
        const minX = Math.min(...pts.map((p) => p.x));
        const minY = Math.min(...pts.map((p) => p.y));
        const maxX = Math.max(...pts.map((p) => p.x)) + NODE_W;
        const maxY = Math.max(...pts.map((p) => p.y)) + NODE_H;
        const outCount = ends.filter((e) => e?.src.type === 'group' && e.src.id === g.id).length;
        const h = Math.max(GROUP_H, 2 * DOT_PAD + Math.max(0, outCount - 1) * DOT_GAP);
        const cx = (minX + maxX) / 2;
        const cy = (minY + maxY) / 2;
        return {
          id: g.id,
          name: g.name,
          color: g.color ?? null,
          multi: multi.has(g.id),
          x: cx - GROUP_W / 2,
          y: cy - h / 2,
          w: GROUP_W,
          h,
          count: deepKeys.length,
          deepKeys,
          outCount,
          outDotYs: Array.from({ length: outCount }, (_, i) => this.dotY(i, outCount, h)),
        };
      })
      .filter((b): b is GroupBox => b !== null);
  });

  /** Proxy-Spalten im Drill-Down: externe Quellen links, externe Ziele rechts. */
  protected readonly proxies = computed<{ left: ProxyBox[]; right: ProxyBox[] }>(() => {
    if (this.currentGroupId() === null) return { left: [], right: [] };
    const ends = this.edgeEnds();
    const transitions = this.graph().transitions ?? [];
    const leftIds: string[] = [];
    const rightIds: string[] = [];
    ends.forEach((e, i) => {
      if (!e) return;
      if (e.src.type === 'proxy' && !leftIds.includes(e.src.pid)) leftIds.push(e.src.pid);
      if (e.dst.type === 'proxy' && !rightIds.includes(e.dst.pid)) rightIds.push(e.dst.pid);
      void transitions[i];
    });
    // Spalten links/rechts neben der Inhalts-BBox (Nodes + Gruppen-Kästen).
    const xs: number[] = [];
    const ys: number[] = [];
    for (const n of this.nodes()) {
      xs.push(n.x, n.x + NODE_W);
      ys.push(n.y);
    }
    for (const b of this.groupBoxes()) {
      xs.push(b.x, b.x + b.w);
      ys.push(b.y);
    }
    const minX = xs.length ? Math.min(...xs) : MARGIN;
    const maxX = xs.length ? Math.max(...xs) : MARGIN + NODE_W;
    const minY = ys.length ? Math.min(...ys) : MARGIN;
    const label = (pid: string): { label: string; isGroup: boolean } => {
      if (pid.startsWith('group:')) {
        const g = this.groupById().get(pid.slice('group:'.length));
        return { label: g?.name ?? pid, isGroup: true };
      }
      const key = pid.slice('state:'.length);
      const s = this.graph().states.find((x) => x.key === key);
      return { label: s ? this.label(s) : key, isGroup: false };
    };
    const make = (ids: string[], x: number): ProxyBox[] =>
      ids.map((pid, i) => ({ pid, ...label(pid), x, y: minY + i * PROXY_GAP }));
    return {
      left: make(leftIds, minX - PROXY_COL_GAP),
      right: make(rightIds, maxX + PROXY_COL_GAP),
    };
  });

  protected readonly nodes = computed(() => {
    const pos = this.positions();
    const sel = this.selection();
    const multi = this.multiSel();
    const transitions = this.graph().transitions ?? [];
    return this.visibleStates().map((s) => {
      // vote: ein beschrifteter Punkt je Branch (pass/fail) PLUS die Guard-Punkte
      // für manuelle Ausgänge (z. B. »Wahl abbrechen«, #abort-vote). Normal: ein
      // Punkt je unterschiedlichem Guard (+ Default-Punkt zum Aufziehen neuer,
      // guard-loser Kanten).
      const branches = this.sortedBranchDots(s.key, s.kind, transitions, pos);
      const groups = this.outDots(s.key, transitions);
      const total = branches.length + groups.length;
      const h = this.nodeHeight(total);
      const dots = [
        ...branches.map((b, i) => ({
          id: b,
          branch: b as string | null,
          guard: null as TransitionDef['guard'] | null,
          cy: this.dotY(i, total, h),
          label: b,
        })),
        ...groups.map((gp, i) => ({
          id: gp.sig || 'out',
          branch: null as string | null,
          // Beim Aufziehen vom Guard-Punkt erbt der neue Übergang dessen Guard.
          guard: gp.guard ?? null,
          cy: this.dotY(branches.length + i, total, h),
          label: gp.sig ? this.guardGroupLabel(gp) : '',
        })),
      ];
      return {
        key: s.key,
        label: this.label(s),
        kind: s.kind ?? 'normal',
        color: s.color ?? null,
        isInitial: !!s.isInitial,
        selected: sel?.kind === 'state' && sel.key === s.key,
        multi: multi.has(s.key),
        x: pos[s.key]?.x ?? 0,
        y: pos[s.key]?.y ?? 0,
        h,
        dots,
      };
    });
  });

  /** Knotenhöhe: wächst, sobald die Punkte mit festem Abstand nicht mehr in die
   *  Grundhöhe passen (#flow-quirks). */
  private nodeHeight(dotCount: number): number {
    return Math.max(NODE_H, 2 * DOT_PAD + Math.max(0, dotCount - 1) * DOT_GAP);
  }

  private branchDotsFor(kind: string | null | undefined): string[] {
    return kind === 'vote' ? ['pass', 'fail'] : [];
  }

  /** Branch-Punkte nach Ziel-Höhe sortieren (#flow-quirks): zeigt »pass« nach unten
   *  und »fail« nach oben, tauschen die Punkte — die Kanten kreuzen sich sonst
   *  direkt vor dem Knoten. Guard-Punkte bleiben in Prioritäts-Reihenfolge. */
  private sortedBranchDots(
    fromKey: string,
    kind: string | null | undefined,
    transitions: readonly TransitionDef[],
    pos: Record<string, { x: number; y: number }>,
  ): string[] {
    const branches = this.branchDotsFor(kind);
    if (branches.length < 2) return branches;
    const avgTargetY = (branch: string): number | null => {
      const ys = transitions
        .filter((t) => t.from === fromKey && t.branch === branch && pos[t.to])
        .map((t) => pos[t.to].y);
      return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : null;
    };
    return [...branches].sort((a, b) => {
      const ya = avgTargetY(a);
      const yb = avgTargetY(b);
      if (ya == null || yb == null) return 0;
      return ya - yb;
    });
  }

  /** Ausgehende Übergänge nach Guard gruppieren, in Array-(=Prioritäts-)Reihenfolge.
   *  Branch-Übergänge (pass/fail eines vote-States) bleiben außen vor — sie haben
   *  eigene Punkte und keine Guard-Priorität. */
  private groupsOf(transitions: readonly TransitionDef[], fromKey: string): GuardGroup[] {
    const bySig = new Map<string, GuardGroup>();
    const order: GuardGroup[] = [];
    transitions.forEach((t, index) => {
      if (t.from !== fromKey || t.branch) return;
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

  /** Klarname einer Guard-Gruppe (Operator + Wert; leer = Catch-all).
   *  Human-readable (#7): Kombinatoren nutzen die `guardCombinator`-Keys (nicht
   *  `guardOp.and` — den Key gibt es nicht), `compare` zeigt »feld op wert«, und
   *  Rollen-/Gremien-/Kostenstellen-Referenzen werden zu Namen aufgelöst. */
  protected guardGroupLabel(g: GuardGroup): string {
    if (!g.sig) return this.i18n.translate('admin.flow.guardDefault');
    if (g.op === 'and' || g.op === 'or' || g.op === 'not') {
      const opLabel = this.i18n.translate(`admin.flow.guardCombinator.${g.op}` as TranslationKey);
      const children = (g.guard as Record<string, unknown> | null)?.[g.op];
      const n = Array.isArray(children) ? children.length : 1;
      return `${opLabel} (${n})`;
    }
    const opLabel = this.i18n.translate(`admin.flow.guardOp.${g.op}` as TranslationKey);
    if (g.op === 'compare') {
      const c = (g.guard as Record<string, unknown> | null)?.['compare'];
      if (c && typeof c === 'object') {
        const spec = c as { field?: unknown; op?: unknown; value?: unknown };
        const value = Array.isArray(spec.value)
          ? spec.value.join(', ')
          : String(spec.value ?? '');
        return `${String(spec.field ?? '')} ${String(spec.op ?? '==')} ${value}`.trim();
      }
      return opLabel;
    }
    const value = this.resolveGuardValue(g.op, g.value);
    return value ? `${opLabel}: ${value}` : opLabel;
  }

  /** Klarname des Guards EINES Übergangs (für die In/Out-Listen, #10). */
  protected transitionGuardLabel(t: TransitionDef): string {
    if (!t.guard) return this.i18n.translate('admin.flow.guardDefault');
    const op = Object.keys(t.guard)[0] ?? '';
    const v = Object.values(t.guard)[0];
    return this.guardGroupLabel({
      sig: JSON.stringify(t.guard),
      guard: t.guard,
      op,
      value: v == null || typeof v === 'object' ? '' : String(v),
      indices: [],
    });
  }

  /** Eingehende/ausgehende Übergänge des selektierten States als Listen (#10);
   *  Klick auf eine Zeile selektiert den Übergang (Inspektor + Guard-Pane). */
  protected readonly stateTransitionLists = computed(() => {
    const sel = this.selection();
    if (sel?.kind !== 'state') return null;
    const labelOf = new Map(this.graph().states.map((s) => [s.key, this.label(s)]));
    const rows = (match: (t: TransitionDef) => boolean) =>
      (this.graph().transitions ?? [])
        .map((t, index) => ({ t, index }))
        .filter(({ t }) => match(t))
        .map(({ t, index }) => ({
          index,
          from: labelOf.get(t.from) ?? t.from,
          to: labelOf.get(t.to) ?? t.to,
          label: t.label?.['de'] || t.label?.['en'] || '',
          guard: this.transitionGuardLabel(t),
          automatic: !!t.automatic,
          branch: t.branch ?? null,
        }));
    return {
      incoming: rows((t) => t.to === sel.key),
      outgoing: rows((t) => t.from === sel.key),
    };
  });

  /** Guard-Wert auflösen (#7): Rollen-Key/Gremium-UUID/Kostenstellen-UUID → Klarname
   *  aus den geladenen Katalogen; unbekannte Werte bleiben roh sichtbar. */
  private resolveGuardValue(op: string, value: string): string {
    if (!value) return value;
    const kind = this.guardValueKind(op);
    if (kind === 'role') return this.optionLabel(this.globalRoleOptions(), value);
    if (kind === 'committee') return this.optionLabel(this.gremiumOptions(), value);
    if (op === 'budgetIs') return this.budgetNameById().get(value) ?? value;
    return value;
  }

  private optionLabel(options: SelectOption[], value: string): string {
    return options.find((o) => o.value === value)?.label ?? value;
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
      // Branch-Übergänge des Knotens sind nicht Teil der Guard-Gruppen — mitnehmen,
      // sonst gingen pass/fail eines vote-States beim Umsortieren verloren.
      const others = all.filter((t) => t.from !== fromKey || t.branch);
      const next = [...others, ...outgoing].map((t, i) => ({ ...t, order: i }));
      return { ...g, transitions: next };
    });
  }

  /** Y eines Ausgangs-Punkts: FESTER Abstand, mittig zentriert — der Knoten/
   *  Kasten wächst stattdessen in die Höhe (#flow-quirks). */
  private dotY(i: number, n: number, h: number): number {
    if (n <= 1) return h / 2;
    return h / 2 - ((n - 1) * DOT_GAP) / 2 + i * DOT_GAP;
  }

  protected readonly edges = computed(() => {
    const pos = this.positions();
    const sel = this.selection();
    const transitions = this.graph().transitions ?? [];
    const kindOf = new Map(this.graph().states.map((s) => [s.key, s.kind] as const));
    const ends = this.edgeEnds();
    const nodeH = new Map(this.nodes().map((n) => [n.key, n.h]));
    const boxes = new Map(this.groupBoxes().map((b) => [b.id, b]));
    const { left, right } = this.proxies();
    const leftBy = new Map(left.map((p) => [p.pid, p]));
    const rightBy = new Map(right.map((p) => [p.pid, p]));
    // Ausgangs-Punkt-Index je Gruppen-Kante: Reihenfolge des Auftretens.
    const groupOutSeen = new Map<string, number>();
    return transitions
      .map((t, index) => ({ t, index, e: ends[index] }))
      .filter((x): x is { t: TransitionDef; index: number; e: { src: EndRef; dst: EndRef } } => !!x.e)
      .filter(({ t, e }) =>
        (e.src.type !== 'state' || !!pos[t.from]) && (e.dst.type !== 'state' || !!pos[t.to]),
      )
      .map(({ t, index, e }) => {
        let x1: number;
        let y1: number;
        if (e.src.type === 'state') {
          const a = pos[t.from];
          x1 = a.x + NODE_W;
          // Start am Ausgangs-Punkt: Branch (pass/fail …) bzw. dem Guard-Punkt (#8).
          y1 =
            a.y +
            this.outDotYFor(
              t.from, kindOf.get(t.from), t, transitions, pos, nodeH.get(t.from) ?? NODE_H,
            );
        } else if (e.src.type === 'group') {
          const b = boxes.get(e.src.id);
          const j = groupOutSeen.get(e.src.id) ?? 0;
          groupOutSeen.set(e.src.id, j + 1);
          x1 = (b?.x ?? 0) + (b?.w ?? GROUP_W);
          y1 = (b?.y ?? 0) + this.dotY(j, b?.outCount ?? 1, b?.h ?? GROUP_H);
        } else {
          const p = leftBy.get(e.src.pid);
          x1 = (p?.x ?? 0) + PROXY_W;
          y1 = (p?.y ?? 0) + PROXY_H / 2;
        }
        let x2: number;
        let y2: number;
        if (e.dst.type === 'state') {
          const b = pos[t.to];
          x2 = b.x;
          y2 = b.y + (nodeH.get(t.to) ?? NODE_H) / 2;
        } else if (e.dst.type === 'group') {
          const b = boxes.get(e.dst.id);
          x2 = b?.x ?? 0;
          y2 = (b?.y ?? 0) + (b?.h ?? GROUP_H) / 2;
        } else {
          const p = rightBy.get(e.dst.pid);
          x2 = p?.x ?? 0;
          y2 = (p?.y ?? 0) + PROXY_H / 2;
        }
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
          color: t.color ?? null,
          selected: sel?.kind === 'transition' && sel.index === index,
        };
      });
  });

  /** Y-Offset des Ausgangs-Punkts: Branch-Punkt (vote) bzw. der zum Guard des
   *  Übergangs gehörende Punkt — konsistent zur kombinierten Punkt-Liste in
   *  ``nodes`` (vote-Knoten tragen Branch- UND Guard-Punkte, #abort-vote). */
  private outDotYFor(
    fromKey: string,
    kind: string | null | undefined,
    t: TransitionDef,
    transitions: readonly TransitionDef[],
    pos: Record<string, { x: number; y: number }>,
    h: number,
  ): number {
    const branches = this.sortedBranchDots(fromKey, kind, transitions, pos);
    const groups = this.outDots(fromKey, transitions);
    const total = branches.length + groups.length;
    if (t.branch) {
      const i = branches.indexOf(t.branch);
      return i >= 0 ? this.dotY(i, total, h) : h / 2;
    }
    const sig = t.guard ? JSON.stringify(t.guard) : '';
    const i = groups.findIndex((g) => g.sig === sig);
    return this.dotY(branches.length + (i < 0 ? groups.length - 1 : i), total, h);
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
  /** Inhalts-BBox der aktuellen Ebene (Nodes + Gruppen-Kästen + Proxies) —
   *  Proxies können links von x=0 liegen, daher echte Bounds statt 0/0. */
  protected readonly contentBounds = computed(() => {
    const xs: number[] = [];
    const ys: number[] = [];
    for (const n of this.nodes()) {
      xs.push(n.x, n.x + NODE_W);
      ys.push(n.y, n.y + n.h);
    }
    for (const b of this.groupBoxes()) {
      xs.push(b.x, b.x + b.w);
      ys.push(b.y, b.y + b.h);
    }
    const { left, right } = this.proxies();
    for (const p of [...left, ...right]) {
      xs.push(p.x, p.x + PROXY_W);
      ys.push(p.y, p.y + PROXY_H);
    }
    if (!xs.length) return { x: 0, y: 0, w: 480, h: 320 };
    const minX = Math.min(...xs) - MARGIN;
    const minY = Math.min(...ys) - MARGIN;
    return {
      x: minX,
      y: minY,
      w: Math.max(Math.max(...xs) + MARGIN - minX, 480),
      h: Math.max(Math.max(...ys) + MARGIN - minY, 320),
    };
  });
  protected readonly viewBox = computed(() => {
    const v = this.view();
    const b = this.contentBounds();
    return v ? `${v.x} ${v.y} ${v.w} ${v.h}` : `${b.x} ${b.y} ${b.w} ${b.h}`;
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
  /** Neuen State anlegen — innerhalb einer geöffneten Gruppe wird er deren
   *  Mitglied (sonst wäre er auf dieser Ebene unsichtbar). */
  protected addState(): void {
    const key = uniqueKey('state', this.graph().states);
    const ctx = this.currentGroupId();
    this.graph.update((g) => {
      const next = autoLayout({
        ...g,
        states: [...g.states, blankState(key, g.states.length === 0)],
      });
      if (!ctx) return next;
      return {
        ...next,
        layout: {
          ...(next.layout ?? {}),
          groups: (next.layout?.groups ?? []).map((gr) =>
            gr.id === ctx ? { ...gr, stateKeys: [...gr.stateKeys, key] } : gr,
          ),
        },
      };
    });
    this.selection.set({ kind: 'state', key });
  }

  protected removeSelectedState(): void {
    const sel = this.selection();
    if (sel?.kind !== 'state') return;
    const key = sel.key;
    this.graph.update((g) => {
      const positions = { ...(g.layout?.positions ?? {}) };
      delete positions[key];
      // Gruppen-Mitgliedschaft mit entfernen; leere Gruppen (keine States UND
      // keine Unter-Gruppen) verschwinden.
      const groups = (g.layout?.groups ?? [])
        .map((gr) => ({ ...gr, stateKeys: gr.stateKeys.filter((k) => k !== key) }))
        .filter((gr) => gr.stateKeys.length > 0 || (gr.groupIds ?? []).length > 0);
      return {
        ...g,
        states: g.states.filter((s) => s.key !== key),
        transitions: (g.transitions ?? []).filter((t) => t.from !== key && t.to !== key),
        layout: { positions, ...(groups.length ? { groups } : {}) },
      };
    });
    this.selection.set(null);
    this.multiSel.set(new Set());
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
      // Gruppen-Mitgliedschaft folgt der Umbenennung.
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

  protected setStateTerminal(key: string, on: boolean): void {
    this.graph.update((g) => ({
      ...g,
      states: g.states.map((s) => (s.key === key ? { ...s, isTerminal: on } : s)),
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

  /** Farbe eines Übergangs setzen/entfernen (#flow): färbt Pfeil + Entscheidungs-Button. */
  protected setTransitionColor(index: number, color: string): void {
    this.patchTransition(index, (t) => ({ ...t, color: color || null }));
  }

  protected setTransitionAutomatic(index: number, on: boolean): void {
    this.graph.update((g) => ({
      ...g,
      transitions: (g.transitions ?? []).map((t, idx) =>
        idx === index ? { ...t, automatic: on } : t,
      ),
    }));
  }

  /** »Erfordert Aktion« (#requires-action): `true` (Default) wird nicht persistiert. */
  protected setTransitionRequiresAction(index: number, on: boolean): void {
    this.patchTransition(index, (t) => {
      if (on) {
        const next = { ...t };
        delete next.requiresAction;
        return next;
      }
      return { ...t, requiresAction: false };
    });
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

  /** Auto-Arrange der AKTUELLEN Ebene (#flow-groups): jede Unter-Gruppe verhält
   *  sich dabei wie EIN Knoten; ihre Member werden als Block mitverschoben. */
  protected relayout(): void {
    const visible = this.visibleStates();
    const childGroups = this.childGroups();
    const ends = this.edgeEnds();
    const entId = (r: EndRef): string | null =>
      r.type === 'state' ? `s:${r.key}` : r.type === 'group' ? `g:${r.id}` : null;
    const initialKey = this.graph().states.find((s) => s.isInitial)?.key;
    const entities = [
      ...visible.map((s) => ({ id: `s:${s.key}`, isInitial: !!s.isInitial })),
      ...childGroups.map((g) => ({
        id: `g:${g.id}`,
        isInitial: initialKey ? this.deepStateKeys(g.id).includes(initialKey) : false,
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
    this.graph.update((g) => {
      const positions = { ...(g.layout?.positions ?? {}) };
      for (const s of visible) {
        const p = target[`s:${s.key}`];
        if (p) positions[s.key] = p;
      }
      // Gruppe als Block: Member-BBox-Top-Left auf die Zielposition schieben.
      for (const grp of childGroups) {
        const p = target[`g:${grp.id}`];
        if (!p) continue;
        const deep = this.deepStateKeys(grp.id);
        const pts = deep
          .map((k) => positions[k])
          .filter((q): q is { x: number; y: number } => !!q);
        if (!pts.length) continue;
        const dx = p.x - Math.min(...pts.map((q) => q.x));
        const dy = p.y - Math.min(...pts.map((q) => q.y));
        for (const k of deep) {
          const cur = positions[k];
          if (cur) positions[k] = { x: cur.x + dx, y: cur.y + dy };
        }
      }
      return { ...g, layout: { ...(g.layout ?? {}), positions } };
    });
    this.resetView();
  }

  // --- Gruppen-Operationen (#flow-groups) -----------------------------------
  /** Gruppe aus der Mehrfachauswahl (States + Gruppen der aktuellen Ebene)
   *  erstellen; Mitglieder verlassen ihre bisherige Klammer. Innerhalb einer
   *  geöffneten Gruppe entsteht eine Unter-Gruppe (Schachtelung). */
  protected createGroupFromSelection(): void {
    const stateKeys = [...this.multiSel()];
    const groupIds = [...this.multiSelGroups()];
    if (stateKeys.length + groupIds.length < 2) return;
    const existing = this.groups();
    const used = new Set(existing.map((g) => g.id));
    let n = existing.length + 1;
    while (used.has(`grp${n}`)) n++;
    const id = `grp${n}`;
    const name = `${this.i18n.translate('admin.flow.group.defaultName')} ${n}`;
    const ctx = this.currentGroupId();
    this.graph.update((g) => {
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
    });
    this.multiSel.set(new Set());
    this.multiSelGroups.set(new Set());
  }

  private patchGroup(id: string, fn: (g: FlowGroup) => FlowGroup): void {
    this.graph.update((g) => ({
      ...g,
      layout: {
        ...(g.layout ?? {}),
        groups: (g.layout?.groups ?? []).map((gr) => (gr.id === id ? fn(gr) : gr)),
      },
    }));
  }

  protected renameGroup(id: string, name: string): void {
    this.patchGroup(id, (g) => ({ ...g, name }));
  }

  protected setGroupColor(id: string, color: string): void {
    this.patchGroup(id, (g) => ({ ...g, color: color || null }));
  }

  /** Aktuelle Gruppe auflösen: Inhalt wandert eine Ebene hoch (Parent bzw.
   *  oberste Ebene), nur die Klammer verschwindet. */
  protected dissolveCurrentGroup(): void {
    const id = this.currentGroupId();
    if (!id) return;
    const parent = this.parentGroupId().get(id) ?? null;
    this.graph.update((g) => {
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
                groupIds: [
                  ...(gr.groupIds ?? []).filter((cid) => cid !== id),
                  ...(me.groupIds ?? []),
                ],
              }
            : gr,
        );
      }
      const layout = { ...(g.layout ?? {}) };
      if (groups.length) layout.groups = groups;
      else delete layout.groups;
      return { ...g, layout };
    });
    this.navigateTo(parent);
  }

  // --- Drill-Down-Navigation (#flow-groups) ---------------------------------
  protected navigateTo(id: string | null): void {
    this.currentGroupId.set(id);
    this.selection.set(null);
    this.multiSel.set(new Set());
    this.multiSelGroups.set(new Set());
    this.resetView();
  }

  protected openGroup(id: string): void {
    this.navigateTo(id);
  }

  /** Klick auf einen Proxy: zum externen Ziel springen — Gruppe öffnen bzw. in
   *  die Ebene des States wechseln und ihn selektieren. */
  protected onProxyClick(pid: string): void {
    if (pid.startsWith('group:')) {
      this.navigateTo(pid.slice('group:'.length));
      return;
    }
    const key = pid.slice('state:'.length);
    this.navigateTo(this.stateOwnerId().get(key) ?? null);
    this.selection.set({ kind: 'state', key });
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
  /** Knoten greifen → verschieben **oder** (bei Klick ohne Bewegung) auswählen.
   *  Shift-Klick togglet die Mehrfachauswahl für »Gruppe erstellen« (#flow-groups). */
  protected onNodePointerDown(event: PointerEvent, key: string): void {
    event.stopPropagation();
    if (event.shiftKey) {
      const next = new Set(this.multiSel());
      if (next.has(key)) next.delete(key);
      else next.add(key);
      this.multiSel.set(next);
      return;
    }
    const p = this.toSvg(event);
    const pos = this.positions()[key] ?? { x: 0, y: 0 };
    this.drag = { key, dx: p.x - pos.x, dy: p.y - pos.y, moved: false };
    (event.target as Element).setPointerCapture?.(event.pointerId);
  }

  /** Gruppen-Kasten greifen: ziehen verschiebt alle (tiefen) Member gemeinsam,
   *  Klick ohne Bewegung ÖFFNET die Gruppe (Drill-Down). Shift-Klick togglet
   *  die Mehrfachauswahl (Gruppen sind gruppierbar → Schachtelung). */
  protected onGroupPointerDown(event: PointerEvent, id: string): void {
    event.stopPropagation();
    if (event.shiftKey) {
      const next = new Set(this.multiSelGroups());
      if (next.has(id)) next.delete(id);
      else next.add(id);
      this.multiSelGroups.set(next);
      return;
    }
    const p = this.toSvg(event);
    this.groupDrag = { id, lastX: p.x, lastY: p.y, moved: false };
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
        layout: {
          ...(g.layout ?? {}),
          positions: { ...(g.layout?.positions ?? {}), [key]: { x: nx, y: ny } },
        },
      }));
      return;
    }
    if (this.groupDrag) {
      const p = this.toSvg(event);
      const dx = p.x - this.groupDrag.lastX;
      const dy = p.y - this.groupDrag.lastY;
      this.groupDrag.lastX = p.x;
      this.groupDrag.lastY = p.y;
      this.groupDrag.moved = true;
      const id = this.groupDrag.id;
      const deepKeys = this.deepStateKeys(id);
      this.graph.update((g) => {
        const positions = { ...(g.layout?.positions ?? {}) };
        for (const k of deepKeys) {
          const cur = positions[k];
          if (cur) {
            positions[k] = {
              x: Math.max(0, Math.round(cur.x + dx)),
              y: Math.max(0, Math.round(cur.y + dy)),
            };
          }
        }
        return { ...g, layout: { ...(g.layout ?? {}), positions } };
      });
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
    if (this.groupDrag) {
      // Klick ohne Bewegung öffnet die Gruppe (Drill-Down, #flow-groups).
      if (!this.groupDrag.moved) this.openGroup(this.groupDrag.id);
      this.groupDrag = null;
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
    if (!this.drag && !this.connectFrom && !this.groupDrag) {
      this.selection.set(null);
      if (this.multiSel().size) this.multiSel.set(new Set());
    }
  }

  // --- Zoom & Pan ----------------------------------------------------------
  /** Aktuelles Sichtfenster (initialisiert es beim ersten Zoom/Pan auf »ganzer Inhalt«). */
  private ensureView(): { x: number; y: number; w: number; h: number } {
    const v = this.view();
    if (v) return v;
    const init = { ...this.contentBounds() };
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
    const base = this.contentBounds().w;
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

  /** State, dessen Knoten-Rechteck den Punkt enthält (für Connect-Ziel).
   *  Nur auf der aktuellen Ebene sichtbare Nodes — in eine Gruppe verbindet
   *  man per Drill-Down (#flow-groups). */
  private nodeAt(p: { x: number; y: number }): string | null {
    for (const n of this.nodes()) {
      if (p.x >= n.x && p.x <= n.x + NODE_W && p.y >= n.y && p.y <= n.y + n.h) {
        return n.key;
      }
    }
    return null;
  }

  // --- save ----------------------------------------------------------------
  /** Speichern läuft — gegen Doppel-Klick (sonst zwei Flow-Versionen aus einem Klick). */
  protected readonly saving = signal(false);

  protected save(): void {
    if (this.saving()) return;
    const v = this.validation();
    if (!v.valid) {
      // Konkrete Meldung statt generisch (z. B. „vote-State braucht pass+fail").
      this.toast.error(v.errors[0] ?? this.i18n.translate('admin.common.invalid'));
      return;
    }
    const graph = normalizeFlowGraph(autoLayout(this.graph()));
    this.saving.set(true);
    this.api.createGlobalFlowVersion(graph).subscribe({
      next: () => {
        this.saving.set(false);
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.history()?.reload();
      },
      error: (err: { error?: { detail?: string } }) => {
        this.saving.set(false);
        this.toast.error(err?.error?.detail ?? this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  /** Aktiven globalen Flow neu laden (nach Versions-Restore aus der Sidebar). */
  protected reloadFlow(): void {
    this.api.getGlobalFlow().subscribe({
      next: (graph) => {
        if (graph && graph.states?.length) {
          this.applyingHistory = true;
          this.graph.set(autoLayout(normalizeFlowGraph(graph)));
        }
      },
      error: () => this.toast.error(this.i18n.translate('admin.flow.loadFailed')),
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
