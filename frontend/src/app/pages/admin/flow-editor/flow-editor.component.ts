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
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, ToastService, type SelectOption } from '@stupa-makers/ui-kit';
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
import { VersionHistoryComponent } from '../version-history/version-history.component';
import { FlowCanvasInteraction, type TempEdge } from './flow-canvas-interaction';
import { createFlowCanvasView } from './flow-canvas-view';
import { FlowEditorOptionsService } from './flow-editor-options.service';
import {
  NODE_W,
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

/**
 * Flow editor as a visual drag-and-drop canvas.
 *
 * The user moves the states freely as nodes. Node positions persist in `layout`.
 * To draw a transition, the user drags from a connector dot onto a target node.
 * A click on a node or an edge opens the inspector. A save creates a flow version.
 * Client validation mirrors the server function `validate_flow_graph`. It accepts
 * only whitelisted operators and no free-text eval.
 */
@Component({
  selector: 'app-flow-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [FlowEditorOptionsService],
  imports: [
    TranslatePipe,
    ButtonComponent,
    VersionHistoryComponent,
    StateInspectorComponent,
    TransitionInspectorComponent,
    GroupInspectorComponent,
    TransitionListsComponent,
    TransitionDetailComponent,
    PageHeaderComponent,
  ],
  templateUrl: './flow-editor.component.html',
  styleUrl: './flow-editor.component.scss',
})
export class FlowEditorComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  private readonly opts = inject(FlowEditorOptionsService);

  protected readonly canvas = viewChild<ElementRef<SVGSVGElement>>('canvas');
  /** Version sidebar. The editor reloads it after each save. */
  protected readonly versionHistory = viewChild(VersionHistoryComponent);

  protected readonly compareOps = COMPARE_OPS;
  protected readonly stateKinds: StateKind[] = ['normal', 'vote'];

  protected readonly gremiumOptions = this.opts.gremiumOptions;
  protected readonly globalRoleOptions = this.opts.globalRoleOptions;
  protected readonly webhookOptions = this.opts.webhookOptions;
  protected readonly deadlinePolicyOptions = this.opts.deadlinePolicyOptions;

  protected readonly graph = signal<FlowGraph>(autoLayout(emptyFlowGraph()));
  /**
   * False until the first load settles, either with a flow or without one.
   *
   * The graph starts empty, and an empty graph fails validation with "no states". Shown
   * before the answer arrives that alert is not a finding about the flow, it is a finding
   * about the request being in flight.
   */
  protected readonly loaded = signal(false);

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

  protected readonly NODE_W = NODE_W;

  private readonly vm = createFlowCanvasView({
    graph: this.graph,
    currentGroupId: this.currentGroupId,
    selection: this.selection,
    multiSel: this.multiSel,
    multiSelGroups: this.multiSelGroups,
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

  private readonly pointer = new FlowCanvasInteraction({
    svg: () => this.canvas()?.nativeElement,
    graph: () => this.graph(),
    updateGraph: (fn) => this.graph.update(fn),
    positions: () => this.vm.positions(),
    nodes: () => this.vm.nodes(),
    contentBounds: () => this.vm.contentBounds(),
    deepKeys: (id) => this.vm.deepKeys(id),
    openGroup: (id) => this.openGroup(id),
    selection: this.selection,
    multiSel: this.multiSel,
    multiSelGroups: this.multiSelGroups,
    tempEdge: this.tempEdge,
    view: this.view,
  });

  constructor() {
    // Load the active global flow. Keep the empty graph when there is none.
    this.api
      .getGlobalFlow()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (graph) => {
          if (graph && graph.states?.length) {
            // The initial load is not an undo step.
            this.applyingHistory = true;
            this.graph.set(autoLayout(normalizeFlowGraph(graph)));
          }
          this.loaded.set(true);
        },
        // Core editor data: surface the failure instead of an empty canvas. The
        // validation stays hidden: there is no flow to have findings about.
        error: () => this.toast.error(this.i18n.translate('admin.flow.loadFailed')),
      });

    // The drill-down context must never point at a deleted group. Undo, redo or a
    // dissolve from another path can delete it. Fall back to the top level.
    effect(() => {
      const id = this.currentGroupId();
      if (id && !this.vm.groupById().has(id)) this.currentGroupId.set(null);
    });

    // Record structural graph changes as undo steps. Structural means states and
    // transitions, not positions. Node moves must not flood the history.
    effect(() => {
      const g = this.graph();
      if (this.applyingHistory) {
        this.applyingHistory = false;
        this.lastGraph = g;
        return;
      }
      if (g === this.lastGraph) return;
      if (structuralKey(g) !== structuralKey(this.lastGraph)) this.history.record(this.lastGraph);
      this.lastGraph = g; // Follow layout-only changes too.
    });
  }


  protected readonly multiCount = computed(
    () => this.multiSel().size + this.multiSelGroups().size,
  );

  protected readonly validation = computed(() => validateFlowGraph(this.graph()));
  protected readonly json = computed(() => serializeFlowGraph(this.graph()));

  protected readonly viewBox = computed(() => {
    const v = this.view();
    const b = this.contentBounds();
    return v ? `${v.x} ${v.y} ${v.w} ${v.h}` : `${b.x} ${b.y} ${b.w} ${b.h}`;
  });

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
    return this.guardGroupsFor(fromKey).map((g) => ({ sig: g.sig, label: this.guardGroupLabel(g) }));
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

  protected setStateDeadlinePolicy(key: string, policyKey: string): void {
    this.graph.update((g) => ops.setStateDeadlinePolicy(g, key, policyKey));
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

  protected setCompare(index: number, patch: { field?: string; op?: string; value?: string }): void {
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


  protected relayout(): void {
    const ctx = this.currentGroupId();
    this.graph.update((g) => ops.relayoutLevel(g, ctx));
    this.resetView();
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
   * types in an input, with undo and redo as the exception. Normal text editing stays
   * untouched.
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
      this.toast.error(v.errors[0] ?? this.i18n.translate('admin.common.invalid'));
      return;
    }
    const graph = normalizeFlowGraph(autoLayout(this.graph()));
    this.saving.set(true);
    this.api.createGlobalFlowVersion(graph).subscribe({
      next: () => {
        this.saving.set(false);
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
      },
      error: () => this.toast.error(this.i18n.translate('admin.flow.loadFailed')),
    });
  }
}
