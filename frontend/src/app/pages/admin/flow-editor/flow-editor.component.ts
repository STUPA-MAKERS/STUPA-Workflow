import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  HostListener,
  computed,
  effect,
  DestroyRef,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  EmptyStateComponent,
  IconComponent,
  MEDIA,
  mediaQuery,
  observeElementSize,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ScrollFadeDirective,
  type SelectOption,
  SkeletonComponent,
  StatusTextComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { AdminApiService } from '../admin-api.service';
import {
  COMPARE_OPS,
  type ActionDef,
  type FlowGraph,
  type Guard,
  type NotifyRecipient,
  type StateDef,
  type StateKind,
  type TransitionDef,
} from '../admin.models';
import {
  autoLayout,
  emptyFlowGraph,
  normalizeFlowGraph,
  serializeFlowGraph,
  validateFlowGraph,
} from '../flow-graph.util';
import { FabComponent } from '@shared/ui/fab/fab.component';
import { VersionHistoryComponent } from '../version-history/version-history.component';
import { FlowCanvasInteraction, type TempEdge } from './flow-canvas-interaction';
import { createFlowCanvasView } from './flow-canvas-view';
import { FLOW_LAYOUTER, type LevelLayout } from './flow-elk';
import { FlowEditorOptionsService } from './flow-editor-options.service';
import {
  type GuardGroup,
  type Selection,
  type TransitionLists,
  type ViewRect,
} from './flow-editor.models';
import * as ops from './flow-graph-ops.util';
import {
  actionParamOf,
  compareSpecOf,
  groupsOf,
  guardBoolOf,
  guardOpOf,
  guardValueKind,
  guardValueOf,
  recipientNeedsRef,
  recipientsOf,
} from './flow-guard.util';
import { FlowHistory, structuralKey } from './flow-history.util';
import {
  buildTransitionLists,
  guardGroupLabel,
  stateDisplayLabel,
  transitionGuardLabel,
} from './flow-label.util';
import { GroupInspectorComponent } from './group-inspector.component';
import { StateInspectorComponent, type GuardPriorityRow } from './state-inspector.component';
import { TransitionDetailComponent } from './transition-detail.component';
import { TransitionInspectorComponent } from './transition-inspector.component';
import { TransitionListsComponent } from './transition-lists.component';

/** How far one press of a scroll tongue pans the canvas, in screen px. */
const PAN_STEP = 240;
/** How long a tongue has to be held before it starts repeating. */
const HOLD_DELAY_MS = 300;
/** How often a held tongue pans once it repeats. */
const HOLD_INTERVAL_MS = 90;
/** Sub-pixel slack, so rounding at an edge does not read as hidden content. */
const EDGE_SLACK = 1;

/** A side of the canvas, and the direction its scroll tongue pans to. */
export type PanSide = 'left' | 'right' | 'up' | 'down';

/** The smallest scale of the start view: below it the labels are too small to read. */
const MIN_FIT_SCALE = 0.75;

/**
 * Flow editor as a visual drag-and-drop canvas.
 *
 * The editor places the states itself: ELK lays out each level from its structure
 * (`flow-elk.ts`) whenever it changes, and the lines run in right angles between the
 * layers. The positions stored in `layout` are only the places until the first layout
 * answers. Hovering or selecting a state, or selecting a transition, draws everything
 * else faint. To draw a transition, the user drags from a connector dot onto a target node.
 * A click on a node or an edge opens it in the inspector beside the canvas: a state
 * with its settings and its incoming and outgoing transitions, a transition with its
 * settings, its guard and its actions. "Versionen" in the header shows the version
 * history in the inspector. A save creates a flow version. Client validation mirrors
 * the server function `validate_flow_graph`. It accepts only whitelisted operators and
 * no free-text eval. The header says whether the flow is valid.
 *
 * Wide (`MEDIA.wide`): the canvas and the inspector fill the free height of the window
 * (route data `adminPane`), and the inspector scrolls inside itself. Narrower, the
 * inspector follows the canvas.
 */
@Component({
  selector: 'app-flow-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [FlowEditorOptionsService],
  imports: [
    SkeletonComponent,
    EmptyStateComponent,
    FabComponent,
    TranslatePipe,
    ButtonComponent,
    VersionHistoryComponent,
    StateInspectorComponent,
    TransitionInspectorComponent,
    GroupInspectorComponent,
    TransitionListsComponent,
    TransitionDetailComponent,
    PageHeaderComponent,
    IconComponent,
    StatusTextComponent,
    RowMenuComponent,
    ScrollFadeDirective,
  ],
  host: { '[class.fe-pane]': 'wide()' },
  templateUrl: './flow-editor.component.html',
  styleUrl: './flow-editor.component.scss',
})
export class FlowEditorComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  private readonly opts = inject(FlowEditorOptionsService);

  protected readonly canvas = viewChild<ElementRef<SVGSVGElement>>('canvas');
  /** The inspector. Wide, it scrolls inside itself. */
  private readonly panel = viewChild<ElementRef<HTMLElement>>('panel');
  /** The box around the canvas. Its size sets the scale of the fitted view. */
  private readonly canvasWrap = viewChild<ElementRef<HTMLElement>>('canvasWrap');

  /** Wide viewport: the canvas and the inspector fill the window side by side. */
  protected readonly wide = mediaQuery(MEDIA.wide);
  /** Phone: the header moves "Versionen" into a ⋮ menu. */
  protected readonly phone = mediaQuery(MEDIA.phone);

  /** The inspector shows the version history instead of the selection. */
  protected readonly showVersions = signal(false);
  /** The number of the active flow version, once the version history has loaded. */
  protected readonly currentVersion = signal<number | null>(null);
  /** The size of the canvas box in px (0 until it is measured). */
  private readonly canvasSize = signal({ w: 0, h: 0 });
  /** Version sidebar. The editor reloads it after each save. */
  protected readonly versionHistory = viewChild(VersionHistoryComponent);

  protected readonly compareOps = COMPARE_OPS;
  protected readonly stateKinds: StateKind[] = ['normal', 'vote'];

  protected readonly gremiumOptions = this.opts.gremiumOptions;
  protected readonly globalRoleOptions = this.opts.globalRoleOptions;
  protected readonly webhookOptions = this.opts.webhookOptions;
  protected readonly budgetTree = this.opts.budgetTree;

  protected readonly graph = signal<FlowGraph>(autoLayout(emptyFlowGraph()));
  /**
   * False until the first load settles, either with a flow or without one.
   *
   * The graph starts empty, and an empty graph fails validation with "no states". Shown
   * before the answer arrives that alert is not a finding about the flow, it is a finding
   * about the request being in flight.
   */
  protected readonly loaded = signal(false);
  /** The first read of the flow has not answered yet: a placeholder covers the canvas. */
  protected readonly loading = signal(true);

  private readonly history = new FlowHistory();
  protected readonly canUndo = this.history.canUndo;
  protected readonly canRedo = this.history.canRedo;
  private lastGraph: FlowGraph = this.graph();
  private applyingHistory = false;

  protected readonly selection = signal<Selection>(null);
  /** Drill-down context: the open group. A null value means the top level. */
  protected readonly currentGroupId = signal<string | null>(null);
  /** Multi-selection with shift-click for "create group": states and groups. */
  protected readonly multiSel = signal<ReadonlySet<string>>(new Set());
  protected readonly multiSelGroups = signal<ReadonlySet<string>>(new Set());
  /** Temporary edge while dragging out a new transition. */
  protected readonly tempEdge = signal<TempEdge | null>(null);
  /** Viewport (zoom and pan) in world coordinates. A null value fits the whole content. */
  protected readonly view = signal<ViewRect | null>(null);

  /** The state under the pointer (focus). */
  protected readonly hoverKey = signal<string | null>(null);

  private readonly layouter = inject(FLOW_LAYOUTER);
  /** The last layout that answered, with the input it answers. */
  private readonly levelLayout = signal<{ key: string; layout: LevelLayout } | null>(null);
  /** The layouter failed: the canvas shows the stored places. */
  private readonly layoutFailed = signal(false);

  private readonly vm = createFlowCanvasView({
    graph: this.graph,
    currentGroupId: this.currentGroupId,
    selection: this.selection,
    multiSel: this.multiSel,
    multiSelGroups: this.multiSelGroups,
    hover: this.hoverKey,
    layout: computed(() => {
      const r = this.levelLayout();
      if (!r) return null;
      return r.key === this.layoutKey() ? r.layout : { pos: r.layout.pos, routes: new Map() };
    }),
    stateLabel: (s) => this.label(s),
    guardDotLabel: (g) => this.guardGroupLabel(g),
  });

  protected readonly groups = this.vm.groups;
  protected readonly currentGroup = this.vm.currentGroup;
  protected readonly breadcrumbs = this.vm.breadcrumbs;
  protected readonly groupBoxes = this.vm.groupBoxes;
  protected readonly proxies = this.vm.proxies;
  protected readonly nodes = this.vm.nodes;
  protected readonly edges = this.vm.edges;
  protected readonly contentBounds = this.vm.contentBounds;
  private readonly layoutKey = computed(() => JSON.stringify(this.vm.layoutInput()));
  /**
   * The canvas waits for its first layout, so the boxes do not jump from the stored
   * places to the laid-out ones. Without a layouter or after a failure it shows at once.
   */
  protected readonly layoutPending = computed(
    () => !!this.layouter && !this.layoutFailed() && this.levelLayout() === null,
  );

  private readonly pointer = new FlowCanvasInteraction({
    svg: () => this.canvas()?.nativeElement,
    graph: () => this.graph(),
    updateGraph: (fn) => this.graph.update(fn),
    nodes: () => this.vm.nodes(),
    contentBounds: () => this.fitBounds(),
    openGroup: (id) => this.openGroup(id),
    selection: this.selection,
    multiSel: this.multiSel,
    multiSelGroups: this.multiSelGroups,
    tempEdge: this.tempEdge,
    view: this.view,
  });

  /**
   * The canvas box is measured, so a small flow shows at its real size instead of blown up to the
   * full box. The level is laid out again whenever its structure changes. Only the answer to the
   * newest input counts; an older one that answers late is dropped. The drill-down context must
   * never point at a deleted group, because undo, redo or a dissolve from another path can delete
   * it; it then falls back to the top level. Only structural graph changes (states and transitions,
   * not positions) are undo steps, so node moves do not flood the history.
   */
  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopHold());
    this.api
      .getGlobalFlow()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (graph) => {
          if (graph && graph.states?.length) {
            this.applyingHistory = true;
            this.graph.set(autoLayout(normalizeFlowGraph(graph)));
          }
          this.savedJson.set(this.json());
          this.loaded.set(true);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
          this.toast.error(this.i18n.translate('admin.flow.loadFailed'));
        },
      });

    observeElementSize(
      () => this.canvasWrap()?.nativeElement,
      ({ width, height }) => this.canvasSize.set({ w: Math.round(width), h: Math.round(height) }),
    );

    effect(() => {
      const input = this.vm.layoutInput();
      const key = this.layoutKey();
      const layouter = this.layouter;
      if (!layouter || untracked(this.levelLayout)?.key === key) return;
      const many = (n: number): string => this.i18n.translate('admin.flow.bundle', { n });
      layouter(input, many).then(
        (layout) => {
          if (key === this.layoutKey()) this.levelLayout.set({ key, layout });
        },
        () => this.layoutFailed.set(true),
      );
    });

    effect(() => {
      const id = this.currentGroupId();
      if (id && !this.vm.groupById().has(id)) this.currentGroupId.set(null);
    });

    effect(() => {
      const g = this.graph();
      if (this.applyingHistory) {
        this.applyingHistory = false;
        this.lastGraph = g;
        return;
      }
      if (g === this.lastGraph) return;
      if (structuralKey(g) !== structuralKey(this.lastGraph)) this.history.record(this.lastGraph);
      this.lastGraph = g;
    });
  }

  protected readonly multiCount = computed(() => this.multiSel().size + this.multiSelGroups().size);

  protected readonly validation = computed(() => validateFlowGraph(this.graph()));

  /** Validation reasons in the reader's language. The validator names them, it does not word them. */
  protected readonly validationMessages = computed(() =>
    this.validation().errors.map((e) => this.i18n.translate(e.key, e.params)),
  );
  protected readonly json = computed(() => serializeFlowGraph(this.graph()));
  /** The flow as the server has it (`json`), or null before the first load settles. */
  private readonly savedJson = signal<string | null>(null);
  /** The flow has changes that are not saved. Only then the page shows "Speichern". */
  protected readonly dirty = computed(() => {
    const saved = this.savedJson();
    return saved !== null && this.json() !== saved;
  });

  /**
   * The start view. A flow smaller than the canvas box keeps its real size (scale 1)
   * and sits in the middle of the box; a larger flow scales down to fit, but not below
   * `MIN_FIT_SCALE`, where the labels would be too small to read. A flow that does not
   * fit then starts at its left end (the initial state), centred in height, and the
   * reader pans to the rest. Before the box is measured (and in tests) it is the content
   * bounds.
   */
  protected readonly fitBounds = computed(() => {
    const b = this.contentBounds();
    const { w, h } = this.canvasSize();
    if (!w || !h) return b;
    const scale = Math.min(1, Math.max(MIN_FIT_SCALE, Math.min(w / b.w, h / b.h)));
    const vw = w / scale;
    const vh = h / scale;
    const x = vw >= b.w ? b.x - (vw - b.w) / 2 : b.x;
    return { x, y: b.y - (vh - b.h) / 2, w: vw, h: vh };
  });

  protected readonly viewBox = computed(() => {
    const v = this.view();
    const b = this.fitBounds();
    return v ? `${v.x} ${v.y} ${v.w} ${v.h}` : `${b.x} ${b.y} ${b.w} ${b.h}`;
  });

  /** The zoom in percent of the fitted view (100 % = the whole flow fits). */
  protected readonly zoomPercent = computed(() => {
    const v = this.view();
    return v ? Math.round((this.fitBounds().w / v.w) * 100) : 100;
  });

  /**
   * How much content each side of the canvas hides, in world units. The visible area is
   * the viewBox widened to the aspect of the box (`xMidYMid meet`), so a box that is
   * wider than the view shows more than the view itself.
   */
  protected readonly hiddenBy = computed<Record<PanSide, number> & { scale: number }>(() => {
    const { w, h } = this.canvasSize();
    const v = this.view() ?? this.fitBounds();
    if (!w || !h || !v.w || !v.h) return { left: 0, right: 0, up: 0, down: 0, scale: 1 };
    const scale = Math.min(w / v.w, h / v.h);
    const vw = w / scale;
    const vh = h / scale;
    const x = v.x - (vw - v.w) / 2;
    const y = v.y - (vh - v.h) / 2;
    const b = this.contentBounds();
    const slack = EDGE_SLACK / scale;
    const past = (n: number): number => (n > slack ? n : 0);
    return {
      left: past(x - b.x),
      right: past(b.x + b.w - (x + vw)),
      up: past(y - b.y),
      down: past(b.y + b.h - (y + vh)),
      scale,
    };
  });

  /** The tongue that is held down, for its pressed colour. */
  protected readonly heldSide = signal<PanSide | null>(null);
  private holdTimer?: ReturnType<typeof setTimeout>;
  private holdTick?: ReturnType<typeof setInterval>;

  /** One step towards a side; the last step stops at the edge of the content. */
  protected pan(side: PanSide): void {
    const hidden = this.hiddenBy();
    const d = Math.min(PAN_STEP / hidden.scale, hidden[side]);
    if (d <= 0) return;
    if (side === 'left') this.pointer.panBy(-d, 0);
    else if (side === 'right') this.pointer.panBy(d, 0);
    else if (side === 'up') this.pointer.panBy(0, -d);
    else this.pointer.panBy(0, d);
  }

  /**
   * Press to step, hold to keep going, as the tongues of the tables do: a wide flow
   * should not need fifteen clicks.
   */
  protected onTonguePress(event: PointerEvent, side: PanSide): void {
    if (event.button !== 0) return;
    this.stopHold();
    this.pan(side);
    this.heldSide.set(side);
    this.holdTimer = setTimeout(() => {
      this.holdTick = setInterval(() => this.pan(side), HOLD_INTERVAL_MS);
    }, HOLD_DELAY_MS);
  }

  /** Release, leave or cancel: the repeat stops with the gesture that started it. */
  protected stopHold(): void {
    if (this.holdTimer !== undefined) clearTimeout(this.holdTimer);
    if (this.holdTick !== undefined) clearInterval(this.holdTick);
    this.holdTimer = undefined;
    this.holdTick = undefined;
    this.heldSide.set(null);
  }

  /** Enter and Space step once; the key repeat of the platform does the rest. */
  protected onTongueKey(event: KeyboardEvent, side: PanSide): void {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    this.pan(side);
  }

  protected readonly panSides: readonly PanSide[] = ['left', 'right', 'up', 'down'];
  protected readonly panLabel: Record<PanSide, TranslationKey> = {
    left: 'admin.flow.panLeft',
    right: 'admin.flow.panRight',
    up: 'admin.flow.panUp',
    down: 'admin.flow.panDown',
  };

  /** The meta of the header: the active version, once known. */
  protected readonly versionMeta = computed(() => {
    const v = this.currentVersion();
    return v === null ? null : this.i18n.translate('admin.flow.versionActive', { n: v });
  });

  /** The ⋮ menu of the header on a phone: "Versionen". */
  protected readonly headerMenu = computed<RowMenuSection[]>(() => [
    {
      items: [
        {
          id: 'versions',
          label: this.i18n.translate('admin.flow.versions'),
          icon: 'history',
          checked: this.showVersions(),
        },
      ],
    },
  ]);

  protected onHeaderMenu(item: RowMenuItem): void {
    if (item.id === 'versions') this.toggleVersions();
  }

  /** Show the version history in the inspector, or go back to the selection. */
  protected toggleVersions(): void {
    this.showVersions.update((v) => !v);
  }

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

  /** Incoming/outgoing transitions of the selected state as list rows. */
  protected readonly stateTransitionLists = computed<TransitionLists | null>(() => {
    const sel = this.selection();
    if (sel?.kind !== 'state') return null;
    return buildTransitionLists(this.graph(), sel.key, this.opts.labelContext());
  });

  protected label(s: StateDef): string {
    return stateDisplayLabel(s);
  }

  protected kindLabel(k: string): string {
    return this.opts.kindLabel(k);
  }

  protected readonly kindOptionsSel: SelectOption[] = this.opts.kindOptions(this.stateKinds);

  /** Valid result branches per source-state kind: vote → pass/fail, else none. */
  protected branchesFor(fromKey: string): string[] {
    return this.stateByKey(fromKey)?.kind === 'vote' ? ['pass', 'fail'] : [];
  }

  protected branchOptionsSel(fromKey: string): SelectOption[] {
    return this.branchesFor(fromKey).map((b) => ({ value: b, label: b }));
  }

  protected stateOptions(): SelectOption[] {
    return this.graph().states.map((s) => ({ value: s.key, label: `${this.label(s)} (${s.key})` }));
  }

  protected guardOpOptions(automatic: boolean | undefined): SelectOption[] {
    return this.opts.guardOpOptions(automatic);
  }

  protected compareOpOptions(): SelectOption[] {
    return this.compareOps.map((op) => ({ value: op, label: op }));
  }

  protected recipientKindOptions(): SelectOption[] {
    return this.opts.recipientKindOptions();
  }

  protected actionOptions(): SelectOption[] {
    return this.opts.actionOptions();
  }

  protected actionLabel(type: string): string {
    return this.opts.actionLabel(type);
  }

  protected actionDesc(type: string): string {
    return this.opts.actionDesc(type);
  }

  protected guardValueKind(op: string): 'none' | 'role' | 'committee' | 'compare' | 'text' {
    return guardValueKind(op);
  }

  protected guardValueHint(op: string): string {
    return this.opts.guardValueHint(op);
  }

  protected guardGroupsFor(fromKey: string): GuardGroup[] {
    return groupsOf(this.graph().transitions ?? [], fromKey);
  }

  /** Rows for the priority stack of the state inspector. Labels resolve here. */
  protected guardGroupRows(fromKey: string): GuardPriorityRow[] {
    return this.guardGroupsFor(fromKey).map((g) => ({
      sig: g.sig,
      label: this.guardGroupLabel(g),
    }));
  }

  protected guardGroupLabel(g: GuardGroup): string {
    return guardGroupLabel(g, this.opts.labelContext());
  }

  protected transitionGuardLabel(t: TransitionDef): string {
    return transitionGuardLabel(t, this.opts.labelContext());
  }

  protected moveGuardUp(fromKey: string, sig: string): void {
    this.reorderGuard(fromKey, sig, -1);
  }

  protected moveGuardDown(fromKey: string, sig: string): void {
    this.reorderGuard(fromKey, sig, 1);
  }

  protected moveGuard(fromKey: string, ev: { sig: string; dir: -1 | 1 }): void {
    this.reorderGuard(fromKey, ev.sig, ev.dir);
  }

  private reorderGuard(fromKey: string, sig: string, dir: -1 | 1): void {
    this.graph.update((g) => ops.reorderGuardGroup(g, fromKey, sig, dir));
  }

  protected addState(): void {
    const key = ops.uniqueStateKey('state', this.graph().states);
    const ctx = this.currentGroupId();
    this.graph.update((g) => ops.addState(g, key, ctx));
    this.selection.set({ kind: 'state', key });
  }

  protected removeSelectedState(): void {
    const sel = this.selection();
    if (sel?.kind !== 'state') return;
    this.graph.update((g) => ops.removeState(g, sel.key));
    this.selection.set(null);
    this.multiSel.set(new Set());
  }

  protected setInitial(key: string): void {
    this.graph.update((g) => ops.setInitial(g, key));
  }

  protected setStateKey(oldKey: string, newKey: string): void {
    const key = newKey.trim();
    this.graph.update((g) => ops.renameState(g, oldKey, key));
    this.selection.set({ kind: 'state', key });
  }

  protected setStateLabel(key: string, lang: 'de' | 'en', value: string): void {
    this.graph.update((g) => ops.setStateLabel(g, key, lang, value));
  }

  protected setStateColor(key: string, color: string): void {
    this.graph.update((g) => ops.setStateColor(g, key, color));
  }

  protected setStateEditAllowed(key: string, on: boolean): void {
    this.graph.update((g) => ops.setStateEditAllowed(g, key, on));
  }

  protected setStateTerminal(key: string, on: boolean): void {
    this.graph.update((g) => ops.setStateTerminal(g, key, on));
  }

  protected setStateKind(key: string, kind: string): void {
    this.graph.update((g) => ops.setStateKind(g, key, kind));
  }

  protected setStateGremium(key: string, gremiumId: string): void {
    this.graph.update((g) => ops.setStateGremium(g, key, gremiumId));
  }

  protected setStateGremiumSource(key: string, source: 'fixed' | 'budget'): void {
    this.graph.update((g) => ops.setStateGremiumSource(g, key, source));
  }

  /** The state takes its gremium from the cost center (a dynamic vote state). */
  protected targetIsBudgetVote(key: string): boolean {
    const s = this.stateByKey(key);
    return s?.kind === 'vote' && s.config?.gremiumSource === 'budget';
  }

  private stateByKey(key: string): StateDef | undefined {
    return this.graph().states.find((s) => s.key === key);
  }

  protected removeSelectedTransition(): void {
    const sel = this.selection();
    if (sel?.kind !== 'transition') return;
    this.graph.update((g) => ops.removeTransition(g, sel.index));
    this.selection.set(null);
  }

  protected setTransitionEndpoint(index: number, end: 'from' | 'to', key: string): void {
    this.graph.update((g) => ops.setTransitionEndpoint(g, index, end, key));
  }

  protected setTransitionLabel(index: number, lang: 'de' | 'en', value: string): void {
    this.graph.update((g) => ops.setTransitionLabel(g, index, lang, value));
  }

  protected setTransitionColor(index: number, color: string): void {
    this.graph.update((g) => ops.setTransitionColor(g, index, color));
  }

  protected setTransitionAutomatic(index: number, on: boolean): void {
    this.graph.update((g) => ops.setTransitionAutomatic(g, index, on));
  }

  protected setTransitionRequiresAction(index: number, on: boolean): void {
    this.graph.update((g) => ops.setTransitionRequiresAction(g, index, on));
  }

  protected setTransitionBranch(index: number, branch: string): void {
    this.graph.update((g) => ops.setTransitionBranch(g, index, branch));
  }

  protected setGuard(index: number, guard: Guard | null): void {
    this.graph.update((g) => ops.setGuard(g, index, guard));
  }

  protected setGuardOp(index: number, op: string): void {
    this.graph.update((g) => ops.setGuardOp(g, index, op));
  }

  protected setGuardValue(index: number, value: string): void {
    this.graph.update((g) => ops.setGuardValue(g, index, value));
  }

  protected setGuardBool(index: number, on: boolean): void {
    this.graph.update((g) => ops.setGuardBool(g, index, on));
  }

  protected guardOp(t: TransitionDef): string {
    return guardOpOf(t);
  }

  protected guardValue(t: TransitionDef): string {
    return guardValueOf(t);
  }

  protected guardBool(t: TransitionDef): boolean {
    return guardBoolOf(t);
  }

  protected compareField(t: TransitionDef): string {
    return String(compareSpecOf(t).field ?? '');
  }

  protected compareOp(t: TransitionDef): string {
    return String(compareSpecOf(t).op ?? '==');
  }

  protected compareValue(t: TransitionDef): string {
    const v = compareSpecOf(t).value;
    return v == null ? '' : Array.isArray(v) ? v.join(', ') : String(v);
  }

  protected setCompare(
    index: number,
    patch: { field?: string; op?: string; value?: string },
  ): void {
    this.graph.update((g) => ops.setCompare(g, index, patch));
  }

  protected addAction(index: number, type: string): void {
    if (!type) return;
    this.graph.update((g) => ops.addAction(g, index, type));
  }

  protected removeAction(index: number, ai: number): void {
    this.graph.update((g) => ops.removeAction(g, index, ai));
  }

  protected setActionParam(index: number, ai: number, key: string, value: string): void {
    this.graph.update((g) => ops.setActionParam(g, index, ai, key, value));
  }

  protected setActionMap(index: number, ai: number, map: Record<string, string>): void {
    this.graph.update((g) => ops.setActionMap(g, index, ai, map));
  }

  protected actionParam(act: ActionDef, key: string): string {
    return actionParamOf(act, key);
  }

  protected recipientsOf(act: ActionDef): NotifyRecipient[] {
    return recipientsOf(act);
  }

  protected addRecipient(index: number, ai: number): void {
    this.graph.update((g) => ops.addRecipient(g, index, ai));
  }

  protected removeRecipient(index: number, ai: number, ri: number): void {
    this.graph.update((g) => ops.removeRecipient(g, index, ai, ri));
  }

  protected setRecipientKind(index: number, ai: number, ri: number, kind: string): void {
    this.graph.update((g) => ops.setRecipientKind(g, index, ai, ri, kind));
  }

  protected setRecipientRef(index: number, ai: number, ri: number, ref: string): void {
    this.graph.update((g) => ops.setRecipientRef(g, index, ai, ri, ref));
  }

  protected recipientNeedsRef(kind: string): boolean {
    return recipientNeedsRef(kind);
  }

  protected createGroupFromSelection(): void {
    const stateKeys = [...this.multiSel()];
    const groupIds = [...this.multiSelGroups()];
    if (stateKeys.length + groupIds.length < 2) return;
    const { id, n } = ops.freshGroupId(this.groups());
    const name = `${this.i18n.translate('admin.flow.group.defaultName')} ${n}`;
    const ctx = this.currentGroupId();
    this.graph.update((g) => ops.createGroup(g, id, name, stateKeys, groupIds, ctx));
    this.multiSel.set(new Set());
    this.multiSelGroups.set(new Set());
  }

  protected renameGroup(id: string, name: string): void {
    this.graph.update((g) => ops.renameGroup(g, id, name));
  }

  protected setGroupColor(id: string, color: string): void {
    this.graph.update((g) => ops.setGroupColor(g, id, color));
  }

  protected dissolveCurrentGroup(): void {
    const id = this.currentGroupId();
    if (!id) return;
    const parent = this.vm.parentGroupId().get(id) ?? null;
    this.graph.update((g) => ops.dissolveGroup(g, id, parent));
    this.navigateTo(parent);
  }

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

  /** Proxy click: jump to the external target. Open the group, or switch to the
   *  level of the state and select it. */
  protected onProxyClick(pid: string): void {
    if (pid.startsWith('group:')) {
      this.navigateTo(pid.slice('group:'.length));
      return;
    }
    const key = pid.slice('state:'.length);
    this.navigateTo(this.vm.stateOwnerId().get(key) ?? null);
    this.selection.set({ kind: 'state', key });
  }

  protected undo(): void {
    const prev = this.history.undo(this.graph());
    if (prev === undefined) return;
    this.applyingHistory = true;
    this.graph.set(prev);
    this.selection.set(null);
  }

  protected redo(): void {
    const next = this.history.redo(this.graph());
    if (next === undefined) return;
    this.applyingHistory = true;
    this.graph.set(next);
    this.selection.set(null);
  }

  protected deleteSelected(): void {
    const sel = this.selection();
    if (sel?.kind === 'state') this.removeSelectedState();
    else if (sel?.kind === 'transition') this.removeSelectedTransition();
  }

  /**
   * Shortcuts: Del or Backspace deletes the selection, Insert adds a state, Ctrl+Z
   * undoes, Ctrl+Y or Ctrl+Shift+Z redoes. The handler stays inactive while the user
   * types in an input or works a select (a native one or the app-select combobox and its
   * listbox), with undo and redo as the exception. Normal text editing stays
   * untouched.
   */
  @HostListener('document:keydown', ['$event'])
  protected onKeydown(event: KeyboardEvent): void {
    const target = event.target as HTMLElement | null;
    const tag = target?.tagName;
    const typing =
      tag === 'INPUT' ||
      tag === 'TEXTAREA' ||
      tag === 'SELECT' ||
      !!target?.isContentEditable ||
      !!target?.closest?.('[role="combobox"], [role="listbox"]');
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

  protected onNodePointerDown(event: PointerEvent, key: string): void {
    this.pointer.nodePointerDown(event, key);
  }

  protected onGroupPointerDown(event: PointerEvent, id: string): void {
    this.pointer.groupPointerDown(event, id);
  }

  protected onConnectPointerDown(
    event: PointerEvent,
    key: string,
    branch: string | null = null,
    guard: TransitionDef['guard'] | null = null,
  ): void {
    this.pointer.connectPointerDown(event, key, branch, guard);
  }

  protected onCanvasPointerMove(event: PointerEvent): void {
    this.pointer.pointerMove(event);
  }

  protected onCanvasPointerUp(event: PointerEvent): void {
    this.pointer.pointerUp(event);
  }

  protected onCanvasPointerDown(event: PointerEvent): void {
    this.pointer.canvasPointerDown(event);
  }

  protected selectEdge(index: number): void {
    this.selection.set({ kind: 'transition', index });
  }

  /**
   * A new selection on the canvas (or in a list) brings the inspector back from the
   * versions, and the inspector starts at its top.
   */
  private readonly onSelect = effect(() => {
    if (this.selection() === null) return;
    this.showVersions.set(false);
    const panel = this.panel()?.nativeElement;
    if (panel) panel.scrollTop = 0;
  });

  protected clearSelection(): void {
    this.pointer.clearSelection();
  }

  protected onWheel(event: WheelEvent): void {
    this.pointer.wheel(event);
  }

  protected zoomIn(): void {
    this.pointer.zoomIn();
  }

  protected zoomOut(): void {
    this.pointer.zoomOut();
  }

  protected resetView(): void {
    this.pointer.resetView();
  }

  /** Guards against double-click (two flow versions from one click). */
  protected readonly saving = signal(false);

  protected save(): void {
    if (this.saving()) return;
    const v = this.validation();
    if (!v.valid) {
      this.toast.error(this.validationMessages()[0] ?? this.i18n.translate('admin.common.invalid'));
      return;
    }
    const graph = normalizeFlowGraph(autoLayout(this.graph()));
    const json = this.json();
    this.saving.set(true);
    this.api.createGlobalFlowVersion(graph).subscribe({
      next: () => {
        this.saving.set(false);
        this.savedJson.set(json);
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.versionHistory()?.reload();
      },
      error: (err: { error?: { detail?: string } }) => {
        this.saving.set(false);
        this.toast.error(err?.error?.detail ?? this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  /** Reload the active global flow (after a version restore from the sidebar). */
  protected reloadFlow(): void {
    this.api.getGlobalFlow().subscribe({
      next: (graph) => {
        if (graph && graph.states?.length) {
          this.applyingHistory = true;
          this.graph.set(autoLayout(normalizeFlowGraph(graph)));
        }
        this.savedJson.set(this.json());
      },
      error: () => this.toast.error(this.i18n.translate('admin.flow.loadFailed')),
    });
  }
}
