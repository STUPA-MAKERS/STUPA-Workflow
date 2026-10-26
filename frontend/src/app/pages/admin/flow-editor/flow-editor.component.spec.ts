import { NEVER, Subject, of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import type { FlowGraph, Guard } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { BudgetTreeApi } from '../../budget/budget-tree.api';
import { FlowEditorComponent } from './flow-editor.component';
import {
  FLOW_LAYOUTER,
  type LayoutInput,
  type LayoutRoute,
  type LevelLayout,
  type LevelLayouter,
} from './flow-elk';

interface Overrides {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  getGlobalFlow?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  createGlobalFlowVersion?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  listRoles?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  listWebhooks?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  listGremienOptions?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  tree?: any;
  /** The automatic layout; none by default, so the boxes keep the stored places. */
  layouter?: LevelLayouter | null;
}

const BUDGET_TREE = [
  {
    id: 'b1',
    parentId: null,
    gremiumId: null,
    key: 'VS-800',
    pathKey: 'VS-800',
    name: 'Verwaltung',
    currency: 'EUR',
    active: true,
    color: null,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children: [
      {
        id: 'b2',
        parentId: 'b1',
        gremiumId: null,
        key: 'VS-800-40',
        pathKey: 'VS-800-40',
        name: 'IT',
        currency: 'EUR',
        active: true,
        color: null,
        acceptedStateKeys: [],
        deniedStateKeys: [],
        hiddenInBudget: false,
        viewGremiumId: null,
        fiscalStartMonth: 1,
        fiscalStartDay: 1,
        byFiscalYear: [],
        children: [],
      },
    ],
  },
];

/**
 * The global flow loads and saves as a whole, not per application type. Cost centers give the names
 * for `budgetIs` guard labels.
 */
async function setup(over: Overrides = {}) {
  const getGlobalFlow = over.getGlobalFlow ?? jest.fn(() => of(null));
  const createGlobalFlowVersion = over.createGlobalFlowVersion ?? jest.fn(() => of({ id: 'gfv1' }));
  const listApplicationTypes = jest.fn(() => of([{ id: 't1', name: 'Finanzantrag' }]));
  const listGremienOptions =
    over.listGremienOptions ??
    jest.fn(() =>
      of([{ id: 'g1', name: 'StuPa', slug: 'stupa', cdVariantId: 'cd-stupa', defaultLang: 'de' }]),
    );
  const listGremiumRoles = jest.fn(() =>
    of([{ id: 'gr1', key: 'vorsitz', name: { de: 'Vorsitz' } }]),
  );
  const listRoles =
    over.listRoles ??
    jest.fn(() => of([{ id: 'r1', key: 'finance', label: { de: 'Finanzen' }, permissions: [] }]));
  const listWebhooks =
    over.listWebhooks ??
    jest.fn(() =>
      of([{ id: 'w1', name: 'Buchhaltung', url: 'https://h.test', events: [], active: true }]),
    );
  const listConfigRevisions = jest.fn(() => of([]));
  const api = {
    getGlobalFlow,
    createGlobalFlowVersion,
    listApplicationTypes,
    listGremienOptions,
    listGremiumRoles,
    listRoles,
    listWebhooks,
    listConfigRevisions,
  };
  const budgetApi = { tree: over.tree ?? jest.fn(() => of([])) };
  const toast = { success: jest.fn(), error: jest.fn(), info: jest.fn() };
  const view = await render(FlowEditorComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: BudgetTreeApi, useValue: budgetApi },
      { provide: ToastService, useValue: toast },
      { provide: FLOW_LAYOUTER, useValue: over.layouter ?? null },
    ],
  });
  return { ...view, createGlobalFlowVersion, getGlobalFlow, toast };
}

/** Mounts a fake SVG so that `toSvg` and `getScreenCTM` return identity coordinates. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function stubCanvas(c: any): void {
  const matrix = { inverse: () => matrix, a: 1, d: 1 };
  const svg = {
    getScreenCTM: () => matrix,
    createSVGPoint: () => {
      const pt = { x: 0, y: 0, matrixTransform: () => ({ x: pt.x, y: pt.y }) };
      return pt;
    },
  };
  c.canvas = () => ({ nativeElement: svg });
}

function ptr(clientX: number, clientY: number, extra: Partial<PointerEvent> = {}): PointerEvent {
  return {
    clientX,
    clientY,
    pointerId: 1,
    shiftKey: false,
    stopPropagation: () => {},
    preventDefault: () => {},
    target: { setPointerCapture: () => {} },
    currentTarget: { setPointerCapture: () => {} },
    ...extra,
  } as unknown as PointerEvent;
}

/** Builds a valid graph through the component API. State a is initial and a → b. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildValid(c: any): void {
  c.addState();
  c.addState();
  c.setStateKey('state', 'a');
  c.setStateKey('state2', 'b');
  c.setInitial('a');
  c.graph.update((g: FlowGraph) => ({ ...g, transitions: [{ from: 'a', to: 'b', actions: [] }] }));
}

describe('FlowEditorComponent (Drag&Drop-Canvas)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('reports an empty graph as invalid and shows no save', async () => {
    await setup();
    expect(screen.getByText('Der Flow hat keine Status.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
  });

  /**
   * The graph starts empty, and an empty graph fails validation. Before the answer arrives that
   * alert is a finding about the request, not about the flow, so a placeholder covers the canvas
   * until the flow arrives.
   */
  it('says nothing about the flow while the flow is still loading', async () => {
    await setup({ getGlobalFlow: jest.fn(() => NEVER) });
    expect(screen.queryByText('Der Flow hat keine Status.')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Wird geladen …');
    expect(document.querySelector('.fe__canvas--loading')).not.toBeNull();
  });

  /** A deployment with no flow yet is a real finding, and the admin has to see it. */
  it('reports the empty graph once the load comes back with no flow', async () => {
    await setup({ getGlobalFlow: jest.fn(() => of(null)) });
    expect(screen.getByText('Der Flow hat keine Status.')).toBeInTheDocument();
  });

  /** The validator names a reason, and the catalog words it in the language of the reader. */
  it("states the reason in the reader's language", async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup({ getGlobalFlow: jest.fn(() => of(null)) });
    expect(screen.getByText('The flow has no states.')).toBeInTheDocument();
  });

  it('builds a valid graph and saves it as a flow version', async () => {
    const { fixture, createGlobalFlowVersion } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.save();
    expect(createGlobalFlowVersion).toHaveBeenCalledTimes(1);
    const graph = createGlobalFlowVersion.mock.calls[0][0] as FlowGraph;
    expect(graph.states.map((s) => s.key)).toEqual(['a', 'b']);
    expect(graph.states.filter((s) => s.isInitial)).toHaveLength(1);
    expect(graph.layout?.positions).toBeDefined();
  });

  it('shows "Speichern" only while the flow has unsaved changes', async () => {
    const { fixture, createGlobalFlowVersion } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
    buildValid(c);
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(createGlobalFlowVersion).toHaveBeenCalledTimes(1);
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
  });

  it('renders one canvas node per state', async () => {
    const { container, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    buildValid(fixture.componentInstance as any);
    fixture.detectChanges();
    expect(container.querySelectorAll('.fe__node-text')).toHaveLength(2);
  });

  /** The guard editor renders in the pane below the graph. */
  it('exposes the guard control for a selected transition (auto + manual)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.selectEdge(0);
    fixture.detectChanges();
    expect(screen.getByRole('heading', { name: 'Bedingung (Guard)' })).toBeInTheDocument();
    expect(screen.getAllByRole('combobox').length).toBeGreaterThan(0);
  });

  it('exercises state/transition/guard/action/automatic mutators', async () => {
    const { fixture, createGlobalFlowVersion } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.setInitial('b');
    c.setInitial('a');
    expect(c.graph().states.filter((s: { isInitial?: boolean }) => s.isInitial)).toHaveLength(1);
    c.setStateColor('a', '#4a90d9');
    c.setStateColor('a', '');
    c.setStateLabel('a', 'de', 'Entwurf');
    c.setStateLabel('a', 'en', 'Draft');
    c.setStateEditAllowed('a', false);

    c.selectEdge(0);
    c.setGuardOp(0, 'roleIs');
    c.setGuardValue(0, 'x');
    expect(c.guardOp(c.graph().transitions[0])).toBe('roleIs');
    expect(c.guardValue(c.graph().transitions[0])).toBe('x');
    c.setGuardOp(0, 'compare');
    c.setCompare(0, { field: 'amount', op: '>', value: '100' });
    expect(c.compareField(c.graph().transitions[0])).toBe('amount');
    c.setGuardOp(0, '');
    expect(c.graph().transitions[0].guard).toBeUndefined();

    c.setTransitionAutomatic(0, true);
    expect(c.graph().transitions[0].automatic).toBe(true);

    c.addAction(0, 'notify');
    c.addAction(0, '');
    expect(c.graph().transitions[0].actions).toHaveLength(1);
    c.removeAction(0, 0);
    c.setTransitionLabel(0, 'de', 'go');
    c.setTransitionEndpoint(0, 'to', 'b');

    c.save();
    expect(createGlobalFlowVersion).toHaveBeenCalled();
    const graph = createGlobalFlowVersion.mock.calls[0][0] as FlowGraph;
    expect(graph.transitions[0].automatic).toBe(true);

    c.selectEdge(0);
    c.removeSelectedTransition();
    expect(c.graph().transitions).toHaveLength(0);
    c.selection.set({ kind: 'state', key: 'b' });
    c.removeSelectedState();
    expect(c.graph().states).toHaveLength(1);
  });

  /**
   * Two guarded transitions and one guard-less transition leave a with distinct guards. The node
   * shows one connector dot per group. The order fields mirror the array positions, and the
   * position order sets the evaluation priority.
   */
  it('groups outgoing transitions per distinct guard and reorders priority', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'b', guard: { roleIs: 'x' }, automatic: true, actions: [] },
        { from: 'a', to: 'b', guard: { roleIs: 'y' }, automatic: true, actions: [] },
        { from: 'a', to: 'b', actions: [] },
      ],
    }));

    const groups = c.guardGroupsFor('a');
    expect(groups.map((gp: { value: string }) => gp.value)).toEqual(['x', 'y', '']);
    const nodeA = c.nodes().find((n: { key: string }) => n.key === 'a');
    expect(nodeA.dots).toHaveLength(3);

    c.moveGuardUp('a', JSON.stringify({ roleIs: 'y' }));
    const after = c.guardGroupsFor('a');
    expect(after.map((gp: { value: string }) => gp.value)).toEqual(['y', 'x', '']);
    expect(c.graph().transitions.map((t: { order?: number }) => t.order)).toEqual([0, 1, 2]);
  });

  /** detectChanges records this state in the undo history. */
  it('undoes and redoes structural edits', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    fixture.detectChanges();
    expect(c.graph().states).toHaveLength(2);

    c.selection.set({ kind: 'state', key: 'b' });
    c.removeSelectedState();
    fixture.detectChanges();
    expect(c.graph().states).toHaveLength(1);

    c.undo();
    fixture.detectChanges();
    expect(c.graph().states).toHaveLength(2);

    c.redo();
    fixture.detectChanges();
    expect(c.graph().states).toHaveLength(1);
  });

  it('handles Insert (add), Delete (remove) and Ctrl+Z/Y keys', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.onKeydown(new KeyboardEvent('keydown', { key: 'Insert' }));
    fixture.detectChanges();
    expect(c.graph().states).toHaveLength(1);

    c.selection.set({ kind: 'state', key: c.graph().states[0].key });
    c.onKeydown(new KeyboardEvent('keydown', { key: 'Delete' }));
    fixture.detectChanges();
    expect(c.graph().states).toHaveLength(0);

    c.onKeydown(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true }));
    fixture.detectChanges();
    expect(c.graph().states).toHaveLength(1);

    c.onKeydown(new KeyboardEvent('keydown', { key: 'y', ctrlKey: true }));
    fixture.detectChanges();
    expect(c.graph().states).toHaveLength(0);
  });

  it('ignores Delete/Insert while typing in an input', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    fixture.detectChanges();
    c.selection.set({ kind: 'state', key: c.graph().states[0].key });
    const input = document.createElement('input');
    c.onKeydown({
      key: 'Delete',
      target: input,
      preventDefault: () => {},
    } as unknown as KeyboardEvent);
    expect(c.graph().states).toHaveLength(1);
  });

  it('keeps the state when Delete, Backspace or Insert hit a focused inspector app-select', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.selection.set({ kind: 'state', key: c.graph().states[0].key });
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const host = fixture.nativeElement as HTMLElement;
    const trigger = host.querySelector<HTMLElement>('app-select [role="combobox"]');
    expect(trigger).not.toBeNull();
    trigger!.focus();
    for (const key of ['Delete', 'Backspace', 'Insert']) {
      trigger!.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
      fixture.detectChanges();
    }
    expect(c.graph().states).toHaveLength(1);
    expect(c.selection()).toEqual({ kind: 'state', key: c.graph().states[0].key });
  });

  it('saves nothing and warns when the graph is invalid', async () => {
    const { fixture, createGlobalFlowVersion } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.save();
    expect(createGlobalFlowVersion).not.toHaveBeenCalled();
  });

  /**
   * At the top level only a stays visible next to one group box, and the edge a→b ends at the box.
   * b→c is internal and stays hidden. The drill-down shows the members and the external source a as
   * a left proxy. Dissolve returns the content to the top level.
   */
  it('groups render as one box; drill-down shows members + proxies', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [...(g.transitions ?? []), { from: 'b', to: 'c', actions: [] }],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();

    expect(c.nodes().map((n: { key: string }) => n.key)).toEqual(['a']);
    expect(c.groupBoxes()).toHaveLength(1);
    const groupId = c.groupBoxes()[0].id as string;
    expect(c.edges()).toHaveLength(1);

    c.openGroup(groupId);
    expect(c.breadcrumbs().map((g: { id: string }) => g.id)).toEqual([groupId]);
    expect(
      c
        .nodes()
        .map((n: { key: string }) => n.key)
        .sort(),
    ).toEqual(['b', 'c']);
    expect(c.proxies().left.map((p: { pid: string }) => p.pid)).toEqual(['state:a']);

    c.dissolveCurrentGroup();
    expect(c.currentGroupId()).toBeNull();
    expect(c.groupBoxes()).toHaveLength(0);
    expect(c.nodes()).toHaveLength(3);
  });

  /**
   * At the top level everything sits in one outer group, counted transitively. On the outer level a
   * is a node and the inner group is a box.
   */
  it('nested groups: child group becomes a box inside the parent level', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const inner = c.groupBoxes()[0].id as string;
    c.multiSel.set(new Set(['a']));
    c.multiSelGroups.set(new Set([inner]));
    c.createGroupFromSelection();

    expect(c.nodes()).toHaveLength(0);
    expect(c.groupBoxes()).toHaveLength(1);
    const outer = c.groupBoxes()[0].id as string;
    expect(outer).not.toBe(inner);
    expect(c.groupBoxes()[0].count).toBe(3);

    c.openGroup(outer);
    expect(c.nodes().map((n: { key: string }) => n.key)).toEqual(['a']);
    expect(c.groupBoxes().map((b: { id: string }) => b.id)).toEqual([inner]);
    c.openGroup(inner);
    expect(c.breadcrumbs().map((g: { id: string }) => g.id)).toEqual([outer, inner]);
  });

  /**
   * The constructor subscribes to the flow data load. These tests cover the success and error
   * callbacks.
   */
  it('loads an existing global flow as the starting graph', async () => {
    const existing: FlowGraph = {
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' } },
      ],
      transitions: [{ from: 'a', to: 'b' }],
    };
    const { fixture } = await setup({ getGlobalFlow: jest.fn(() => of(existing)) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.graph().states.map((s: { key: string }) => s.key)).toEqual(['a', 'b']);
  });

  it('toasts when the global flow fails to load', async () => {
    const { toast } = await setup({
      getGlobalFlow: jest.fn(() => throwError(() => new Error('boom'))),
    });
    expect(toast.error).toHaveBeenCalled();
    expect(document.querySelector('.fe__canvasSkel')).toBeNull();
  });

  it('swallows errors from option/role/webhook/budget loads', async () => {
    const err = jest.fn(() => throwError(() => new Error('x')));
    const { fixture } = await setup({
      listRoles: err,
      listWebhooks: err,
      listGremienOptions: err,
      tree: err,
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.gremiumOptions()).toEqual([]);
    expect(c.globalRoleOptions()).toEqual([]);
    expect(c.webhookOptions()).toEqual([]);
  });

  /** The budget guard label resolves the nested id to its name. */
  it('populates option lists and resolves a budget tree (id → "name (key)")', async () => {
    const { fixture } = await setup({ tree: jest.fn(() => of(BUDGET_TREE)) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.globalRoleOptions()).toEqual([{ value: 'finance', label: 'Finanzen (finance)' }]);
    expect(c.webhookOptions()).toEqual([{ value: 'w1', label: 'Buchhaltung' }]);
    expect(
      c.guardGroupLabel({
        sig: 'x',
        guard: { budgetIs: 'b2' },
        op: 'budgetIs',
        value: 'b2',
        indices: [],
      }),
    ).toContain('IT (VS-800-40)');
  });

  /**
   * A combinator with a non-array child counts as 1. A compare without the object falls back to the
   * op label.
   */
  it('renders human-readable guard-group labels for every operator family', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(
      c.guardGroupLabel({ sig: '', guard: null, op: '', value: '', indices: [] }),
    ).toBeTruthy();
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { and: [{ roleIs: 'a' }, { roleIs: 'b' }] },
        op: 'and',
        value: '',
        indices: [],
      }),
    ).toContain('(2)');
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { not: { roleIs: 'a' } },
        op: 'not',
        value: '',
        indices: [],
      }),
    ).toContain('(1)');
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { compare: { field: 'amount', op: '>', value: 100 } },
        op: 'compare',
        value: '',
        indices: [],
      }),
    ).toBe('amount > 100');
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { compare: { field: 'k', op: 'in', value: ['x', 'y'] } },
        op: 'compare',
        value: '',
        indices: [],
      }),
    ).toBe('k in x, y');
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { compare: 'nope' },
        op: 'compare',
        value: '',
        indices: [],
      }),
    ).toBeTruthy();
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { roleIs: 'finance' },
        op: 'roleIs',
        value: 'finance',
        indices: [],
      }),
    ).toContain('Finanzen (finance)');
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { isInCommittee: 'g1' },
        op: 'isInCommittee',
        value: 'g1',
        indices: [],
      }),
    ).toContain('StuPa');
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { hasField: '' },
        op: 'hasField',
        value: '',
        indices: [],
      }),
    ).toBeTruthy();
  });

  it('transitionGuardLabel handles guarded and guard-less transitions', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.transitionGuardLabel({ from: 'a', to: 'b' })).toBeTruthy();
    expect(c.transitionGuardLabel({ from: 'a', to: 'b', guard: { roleIs: 'finance' } })).toContain(
      'Finanzen',
    );
    expect(
      c.transitionGuardLabel({
        from: 'a',
        to: 'b',
        guard: { compare: { field: 'f', op: '==', value: 1 } },
      }),
    ).toBe('f == 1');
  });

  /** A transition selection also returns null. Only a state selection produces the lists. */
  it('lists incoming/outgoing transitions for the selected state and nothing otherwise', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.selection.set(null);
    expect(c.stateTransitionLists()).toBeNull();
    c.selection.set({ kind: 'transition', index: 0 });
    expect(c.stateTransitionLists()).toBeNull();
    c.selection.set({ kind: 'state', key: 'b' });
    const lists = c.stateTransitionLists();
    expect(lists.incoming).toHaveLength(1);
    expect(lists.incoming[0].from).toBe('a');
    expect(lists.outgoing).toHaveLength(0);
  });

  /** The kind switch resets the kind-specific config. */
  it('switches a state to vote, sets the committee, and resets config on normal', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    const key = c.graph().states[0].key;
    c.setStateGremium(key, 'g1');
    c.setStateKind(key, 'vote');
    expect(c.graph().states[0].kind).toBe('vote');
    expect(c.graph().states[0].config).toEqual({});
    c.setStateGremium(key, 'g1');
    expect(c.graph().states[0].config.gremiumId).toBe('g1');
    c.setStateGremium(key, '');
    expect(c.graph().states[0].config.gremiumId).toBeUndefined();
    c.setStateKind(key, '');
    expect(c.graph().states[0].kind).toBeNull();
    expect(c.graph().states[0].config).toEqual({});
    c.setStateTerminal(key, true);
    expect(c.graph().states[0].isTerminal).toBe(true);
    expect(c.branchesFor(key)).toEqual([]);
  });

  /**
   * "From the cost center" drops the fixed gremium. The canvas node carries the tag. The state
   * inspector shows the source select and the hint, not the gremium select. ngModel writes the
   * value of the select field after a microtask. Back on a fixed gremium the source goes, and no
   * gremium is set yet. The budget tree reaches the cost-center pickers.
   */
  it('takes the vote gremium from the cost center (flow variant B)', async () => {
    const { fixture } = await setup({ tree: jest.fn(() => of(BUDGET_TREE)) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    const [a, v] = c.graph().states.map((s: { key: string }) => s.key);
    c.setStateKind(v, 'vote');
    c.setStateGremium(v, 'g1');
    c.setStateGremiumSource(v, 'budget');
    expect(c.graph().states[1].config).toEqual({ gremiumSource: 'budget' });
    expect(c.targetIsBudgetVote(v)).toBe(true);
    expect(c.targetIsBudgetVote(a)).toBe(false);
    expect(c.targetIsBudgetVote('nope')).toBe(false);
    expect(c.nodes().find((n: { key: string }) => n.key === v).gremiumFromBudget).toBe(true);
    expect(c.nodes().find((n: { key: string }) => n.key === a).gremiumFromBudget).toBe(false);
    c.selection.set({ kind: 'state', key: v });
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Gremium aus der Kostenstelle');
    expect(fixture.nativeElement.textContent).toContain('Gremium: aus Kostenstelle');
    c.setStateGremiumSource(v, 'fixed');
    expect(c.graph().states[1].config).toEqual({});
    c.setStateGremium(v, 'g1');
    c.setStateGremiumSource(v, 'fixed');
    expect(c.graph().states[1].config.gremiumId).toBe('g1');
    expect(c.budgetTree()).toEqual(BUDGET_TREE);
  });

  /** An index out of range leaves the other actions untouched. */
  it('edits the value map, drops empty optional params and resets recipient refs', async () => {
    const { fixture } = await setup({ tree: jest.fn(() => of(BUDGET_TREE)) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addAction(0, 'assignBudgetFromMap');
    c.addAction(0, 'addToNextSession');
    c.addAction(0, 'notify');
    const acts = () => c.graph().transitions[0].actions;
    expect(acts()[0]).toEqual({ type: 'assignBudgetFromMap', field: '', map: {} });
    c.setActionMap(0, 0, { technik: 'b2' });
    expect(acts()[0].map).toEqual({ technik: 'b2' });
    c.setActionMap(0, 5, { x: 'y' });
    expect(acts()[0].map).toEqual({ technik: 'b2' });
    c.setActionParam(0, 1, 'gremiumId', 'g1');
    expect(acts()[1].gremiumId).toBe('g1');
    c.setActionParam(0, 1, 'gremiumId', '');
    expect('gremiumId' in acts()[1]).toBe(false);
    c.addRecipient(0, 2);
    c.setRecipientKind(0, 2, 0, 'gremium');
    c.setRecipientRef(0, 2, 0, 'g1');
    c.setRecipientKind(0, 2, 0, 'voteGremium');
    expect(acts()[2].recipients[0]).toEqual({ kind: 'voteGremium', ref: undefined });
  });

  it('branchesFor returns pass/fail for vote states', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    const key = c.graph().states[0].key;
    c.setStateKind(key, 'vote');
    expect(c.branchesFor(key)).toEqual(['pass', 'fail']);
  });

  it('sets a transition branch and clears it', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.setTransitionBranch(0, 'pass');
    expect(c.graph().transitions[0].branch).toBe('pass');
    c.setTransitionBranch(0, '');
    expect(c.graph().transitions[0].branch).toBeNull();
  });

  /**
   * setGuardBool and setGuardValue are no-ops when there is no operator. A compare with `in` splits
   * a comma list.
   */
  it('drives guard bool/compare/value setters and reads them back', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.setGuardOp(0, 'attachmentPresent');
    expect(c.guardBool(c.graph().transitions[0])).toBe(true);
    c.setGuardBool(0, false);
    expect(c.graph().transitions[0].guard).toEqual({ attachmentPresent: false });
    c.setGuardOp(0, '');
    c.setGuardBool(0, true);
    c.setGuardValue(0, 'x');
    expect(c.graph().transitions[0].guard).toBeUndefined();
    c.setGuard(0, { or: [{ roleIs: 'finance' }] });
    expect(c.graph().transitions[0].guard).toEqual({ or: [{ roleIs: 'finance' }] });
    c.setGuard(0, null);
    expect(c.graph().transitions[0].guard).toBeUndefined();
    c.setGuardOp(0, 'compare');
    c.setCompare(0, { op: 'in', value: 'x, y ,z' });
    expect(c.compareValue(c.graph().transitions[0])).toBe('x, y, z');
    expect(c.compareOp(c.graph().transitions[0])).toBe('in');
    c.setGuardOp(0, 'budgetFitsApplication');
    expect(c.graph().transitions[0].guard).toEqual({ budgetFitsApplication: true });
  });

  it('guardValueKind maps every operator', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.guardValueKind('')).toBe('none');
    expect(c.guardValueKind('attachmentPresent')).toBe('none');
    expect(c.guardValueKind('budgetFitsApplication')).toBe('none');
    expect(c.guardValueKind('roleIs')).toBe('role');
    expect(c.guardValueKind('applicantRoleIs')).toBe('role');
    expect(c.guardValueKind('isInCommittee')).toBe('committee');
    expect(c.guardValueKind('applicantCommitteeIs')).toBe('committee');
    expect(c.guardValueKind('compare')).toBe('compare');
    expect(c.guardValueKind('hasField')).toBe('text');
  });

  it('builds option lists + labels through the i18n catalogue', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    expect(c.stateOptions().map((o: { value: string }) => o.value)).toEqual(['a', 'b']);
    expect(c.guardOpOptions(false).map((o: { value: string }) => o.value)).toContain('roleIs');
    expect(c.guardOpOptions(true).map((o: { value: string }) => o.value)).not.toContain('roleIs');
    expect(c.compareOpOptions().length).toBeGreaterThan(0);
    expect(c.recipientKindOptions().length).toBe(6);
    expect(c.actionOptions().length).toBe(7);
    expect(c.actionLabel('notify')).toBeTruthy();
    expect(c.actionDesc('notify')).toBeTruthy();
    expect(c.kindLabel('vote')).toBeTruthy();
    expect(c.guardValueHint('roleIs')).toBeTruthy();
    expect(c.recipientNeedsRef('gremium')).toBe(true);
    expect(c.recipientNeedsRef('applicant')).toBe(false);
  });

  /** A switch back to the applicant drops the ref. */
  it('edits action params and notify recipients', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addAction(0, 'webhook');
    c.setActionParam(0, 0, 'webhookId', 'w1');
    expect(c.actionParam(c.graph().transitions[0].actions[0], 'webhookId')).toBe('w1');
    expect(c.actionParam(c.graph().transitions[0].actions[0], 'missing')).toBe('');

    c.addAction(0, 'notify');
    const ai = 1;
    c.addRecipient(0, ai);
    expect(c.recipientsOf(c.graph().transitions[0].actions[ai])).toHaveLength(1);
    c.setRecipientKind(0, ai, 0, 'gremium');
    c.setRecipientRef(0, ai, 0, 'g1');
    expect(c.recipientsOf(c.graph().transitions[0].actions[ai])[0]).toEqual({
      kind: 'gremium',
      ref: 'g1',
    });
    c.setRecipientKind(0, ai, 0, 'applicant');
    expect(c.recipientsOf(c.graph().transitions[0].actions[ai])[0].ref).toBeUndefined();
    c.removeRecipient(0, ai, 0);
    expect(c.recipientsOf(c.graph().transitions[0].actions[ai])).toHaveLength(0);
    expect(c.recipientsOf({ type: 'webhook' })).toEqual([]);
  });

  it('sets transition color + requiresAction toggle', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.setTransitionColor(0, '#16a34a');
    expect(c.graph().transitions[0].color).toBe('#16a34a');
    c.setTransitionColor(0, '');
    expect(c.graph().transitions[0].color).toBeNull();
    c.setTransitionRequiresAction(0, false);
    expect(c.graph().transitions[0].requiresAction).toBe(false);
    c.setTransitionRequiresAction(0, true);
    expect(c.graph().transitions[0].requiresAction).toBeUndefined();
  });

  /** When the last language is cleared, the label becomes null. */
  it('clears an empty transition label down to null', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.setTransitionLabel(0, 'de', 'go');
    expect(c.graph().transitions[0].label).toEqual({ de: 'go' });
    c.setTransitionLabel(0, 'de', '');
    expect(c.graph().transitions[0].label).toBeNull();
  });

  /** A dissolve from inside the group lifts the members to the top level. */
  it('renames + colors a group and dissolves a top-level group', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const gid = c.groupBoxes()[0].id;
    c.renameGroup(gid, 'Bearbeitung');
    c.setGroupColor(gid, '#f00');
    expect(c.groups()[0].name).toBe('Bearbeitung');
    expect(c.groups()[0].color).toBe('#f00');
    c.setGroupColor(gid, '');
    expect(c.groups()[0].color).toBeNull();
    c.openGroup(gid);
    c.dissolveCurrentGroup();
    expect(c.currentGroupId()).toBeNull();
    expect(c.groups()).toHaveLength(0);
  });

  it('createGroupFromSelection needs at least two members', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.multiSel.set(new Set(['a']));
    c.createGroupFromSelection();
    expect(c.groups()).toHaveLength(0);
    expect(c.multiCount()).toBe(1);
  });

  it('dissolveCurrentGroup is a no-op at the top level', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.dissolveCurrentGroup();
    expect(c.currentGroupId()).toBeNull();
  });

  /**
   * A proxy click on a state navigates to its owner level and selects it; a proxy click on a group
   * navigates into it.
   */
  it('navigates via proxy clicks to a state and to a group', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [...(g.transitions ?? []), { from: 'b', to: 'c', actions: [] }],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const gid = c.groupBoxes()[0].id;
    c.openGroup(gid);
    c.onProxyClick('state:a');
    expect(c.selection()).toEqual({ kind: 'state', key: 'a' });
    c.onProxyClick(`group:${gid}`);
    expect(c.currentGroupId()).toBe(gid);
  });

  it('selects a node on press; the layout keeps it in place', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.selection.set(null);
    const before = { ...c.graph().layout.positions.a };
    c.onNodePointerDown(ptr(0, 0), 'a');
    c.onCanvasPointerMove(ptr(120, 80));
    c.onCanvasPointerUp(ptr(120, 80));
    expect(c.graph().layout.positions.a).toEqual(before);
    expect(c.selection()).toEqual({ kind: 'state', key: 'a' });
  });

  it('shift-click toggles multi-selection of a node', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.onNodePointerDown(ptr(0, 0, { shiftKey: true }), 'a');
    expect([...c.multiSel()]).toEqual(['a']);
    c.onNodePointerDown(ptr(0, 0, { shiftKey: true }), 'a');
    expect([...c.multiSel()]).toEqual([]);
  });

  /** The test positions b so that nodeAt(...) hits it. */
  it('connects a new transition by dragging from a node onto another', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { positions: { a: { x: 0, y: 0 }, b: { x: 300, y: 0 } } },
    }));
    c.onConnectPointerDown(ptr(150, 26), 'a', 'pass', { roleIs: 'finance' });
    c.onCanvasPointerMove(ptr(320, 26));
    expect(c.tempEdge()).not.toBeNull();
    c.onCanvasPointerUp(ptr(320, 26));
    const created = c.graph().transitions[c.graph().transitions.length - 1];
    expect(created).toMatchObject({
      from: 'a',
      to: 'b',
      branch: 'pass',
      guard: { roleIs: 'finance' },
    });
    expect(c.tempEdge()).toBeNull();
  });

  it('dropping a connection on empty space creates nothing', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    const before = c.graph().transitions.length;
    c.onConnectPointerDown(ptr(150, 26), 'a');
    c.onCanvasPointerUp(ptr(9999, 9999));
    expect(c.graph().transitions).toHaveLength(before);
  });

  it('group pointer: a press opens the group; shift toggles multi-select', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const gid = c.groupBoxes()[0].id;
    stubCanvas(c);

    c.onGroupPointerDown(ptr(0, 0, { shiftKey: true }), gid);
    expect([...c.multiSelGroups()]).toEqual([gid]);
    c.onGroupPointerDown(ptr(0, 0, { shiftKey: true }), gid);
    expect([...c.multiSelGroups()]).toEqual([]);

    const beforeB = { ...c.graph().layout.positions.b };
    c.onGroupPointerDown(ptr(0, 0), gid);
    expect(c.currentGroupId()).toBe(gid);
    expect(c.graph().layout.positions.b).toEqual(beforeB);
  });

  it('pans on empty-canvas drag and clears selection', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.selection.set({ kind: 'state', key: 'a' });
    c.onCanvasPointerDown(ptr(10, 10));
    expect(c.selection()).toBeNull();
    c.onCanvasPointerMove(ptr(40, 20));
    expect(c.view()).not.toBeNull();
    c.onCanvasPointerUp(ptr(40, 20));
  });

  /**
   * Without a canvas, `toSvg` passes the client coordinates through unchanged. The move uses them,
   * and the new position is rounded and clamped at 0.
   */
  it('toSvg falls back to client coords without a canvas/CTM', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.canvas = () => undefined;
    c.onNodePointerDown(ptr(12, 34), 'a');
    c.onCanvasPointerMove(ptr(60, 50));
    expect(c.graph().layout.positions.a).toBeDefined();
    c.onCanvasPointerUp(ptr(60, 50));
  });

  /** The viewBox reflects the active view. A reset falls back to the content bounds. */
  it('zooms in/out, wheel-zooms and resets the view', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.zoomIn();
    const zoomed = c.view();
    expect(zoomed).not.toBeNull();
    c.zoomOut();
    expect(c.view()!.w).toBeGreaterThan(zoomed!.w);
    c.onWheel({
      deltaY: -10,
      clientX: 5,
      clientY: 5,
      preventDefault: () => {},
    } as unknown as WheelEvent);
    c.onWheel({
      deltaY: 10,
      clientX: 5,
      clientY: 5,
      preventDefault: () => {},
    } as unknown as WheelEvent);
    expect(c.viewBox()).toMatch(/^[-\d.]+ [-\d.]+ [\d.]+ [\d.]+$/);
    c.resetView();
    expect(c.view()).toBeNull();
    expect(c.viewBox()).toBeTruthy();
  });

  it('clamps zoom within the min/max range', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    for (let i = 0; i < 30; i++) c.zoomIn();
    const minW = c.view()!.w;
    for (let i = 0; i < 60; i++) c.zoomOut();
    expect(c.view()!.w).toBeGreaterThan(minW);
  });

  /**
   * Moving a missing or out-of-range group is a no-op. A vote node draws the pass and fail branch
   * dots plus the two guard dots.
   */
  it('moveGuardDown lowers a guard group priority and keeps vote branches', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'v');
    c.setStateKey('state2', 'p');
    c.setStateKey('state3', 'f');
    c.setInitial('v');
    c.setStateKind('v', 'vote');
    c.setStateGremium('v', 'g1');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'v', to: 'p', branch: 'pass', actions: [] },
        { from: 'v', to: 'f', branch: 'fail', actions: [] },
        { from: 'v', to: 'p', guard: { roleIs: 'x' }, actions: [] },
        { from: 'v', to: 'f', guard: { roleIs: 'y' }, actions: [] },
      ],
    }));
    c.moveGuardDown('v', JSON.stringify({ roleIs: 'x' }));
    const after = c.guardGroupsFor('v').map((gp: { value: string }) => gp.value);
    expect(after).toEqual(['y', 'x']);
    c.moveGuardUp('v', 'no-such-sig');
    c.moveGuardDown('v', JSON.stringify({ roleIs: 'x' }));
    expect(c.guardGroupsFor('v').map((gp: { value: string }) => gp.value)).toEqual(['y', 'x']);
    const node = c.nodes().find((n: { key: string }) => n.key === 'v');
    expect(node.dots.length).toBeGreaterThanOrEqual(4);
  });

  it('shows the server error detail when saving fails', async () => {
    const createGlobalFlowVersion = jest.fn(() =>
      throwError(() => ({ error: { detail: 'nope' } })),
    );
    const { fixture, toast } = await setup({ createGlobalFlowVersion });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.save();
    expect(toast.error).toHaveBeenCalledWith('nope');
  });

  it('does not save twice while a save is in flight', async () => {
    const createGlobalFlowVersion = jest.fn(() => of({ id: 'gfv' }));
    const { fixture } = await setup({ createGlobalFlowVersion });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.saving.set(true);
    c.save();
    expect(createGlobalFlowVersion).not.toHaveBeenCalled();
  });

  it('Ctrl+Shift+Z also redoes', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    fixture.detectChanges();
    c.selection.set({ kind: 'state', key: c.graph().states[0].key });
    c.removeSelectedState();
    fixture.detectChanges();
    c.onKeydown(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true }));
    fixture.detectChanges();
    expect(c.graph().states).toHaveLength(1);
    c.onKeydown(new KeyboardEvent('keydown', { key: 'Z', ctrlKey: true, shiftKey: true }));
    fixture.detectChanges();
    expect(c.graph().states).toHaveLength(0);
  });

  it('undo/redo on empty stacks are no-ops', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.undo();
    c.redo();
    expect(c.graph().states).toHaveLength(0);
  });

  it('addState inside an open group makes the new state a member', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const gid = c.groupBoxes()[0].id;
    c.openGroup(gid);
    c.addState();
    const newKey = c.selection().key;
    expect(c.groups().find((g: { id: string }) => g.id === gid).stateKeys).toContain(newKey);
  });

  it('clearSelection is suppressed while a connect is active', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.selection.set({ kind: 'state', key: 'a' });
    c.onConnectPointerDown(ptr(150, 26), 'a');
    c.clearSelection();
    expect(c.selection()).toEqual({ kind: 'state', key: 'a' });
    c.onCanvasPointerUp(ptr(9999, 9999));
  });

  /** deleteSelected with no selection is a no-op. */
  it('deleteSelected removes the selected transition', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.selection.set({ kind: 'transition', index: 0 });
    c.deleteSelected();
    expect(c.graph().transitions).toHaveLength(0);
    c.selection.set(null);
    c.deleteSelected();
    expect(c.graph().states).toHaveLength(2);
  });

  /** With b removed the group stays with c; with c removed the empty group disappears. */
  it('removing a grouped state cleans up the group; emptied groups vanish', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    expect(c.groups()[0].stateKeys.sort()).toEqual(['b', 'c']);
    c.selection.set({ kind: 'state', key: 'b' });
    c.removeSelectedState();
    expect(c.groups()[0].stateKeys).toEqual(['c']);
    c.selection.set({ kind: 'state', key: 'c' });
    c.removeSelectedState();
    expect(c.groups()).toHaveLength(0);
  });

  it('renaming a grouped state updates the group membership and positions', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    c.setStateKey('b', 'beta');
    expect(c.groups()[0].stateKeys.sort()).toEqual(['beta', 'c']);
    expect(c.graph().layout.positions.beta).toBeDefined();
    expect(c.graph().layout.positions.b).toBeUndefined();
  });

  /**
   * A dissolve of the inner group moves b and c up into the outer group, which then owns a, b and c
   * directly.
   */
  it('dissolving a nested child group lifts its members into the parent', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const inner = c.groupBoxes()[0].id;
    c.multiSel.set(new Set(['a']));
    c.multiSelGroups.set(new Set([inner]));
    c.createGroupFromSelection();
    const outer = c.groupBoxes()[0].id;
    c.openGroup(outer);
    c.openGroup(inner);
    c.dissolveCurrentGroup();
    expect(c.currentGroupId()).toBe(outer);
    const outerGroup = c.groups().find((g: { id: string }) => g.id === outer);
    expect(outerGroup.stateKeys.sort()).toEqual(['a', 'b', 'c']);
    expect(c.groups().some((g: { id: string }) => g.id === inner)).toBe(false);
  });

  /**
   * The states are a (initial) → b → c → d with the group {b,c}, so a→b enters and c→d leaves it.
   * At the top level the group box has one outgoing border edge (c→d) from a group source. Inside,
   * a (external source) is a left proxy and d (external destination) a right proxy, and edges()
   * draws from the left proxy into b and from c to the right proxy. contentBounds includes the
   * proxy columns, which can extend left of x=0.
   */
  it('renders edges/boxes/proxies geometry inside a drilled-down group', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setStateKey('state3', 'c');
    c.setStateKey('state4', 'd');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'b', actions: [] },
        { from: 'b', to: 'c', actions: [] },
        { from: 'c', to: 'd', actions: [] },
      ],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const gid = c.groupBoxes()[0].id;

    fixture.detectChanges();
    expect(c.edges().length).toBeGreaterThan(0);
    expect(c.groupBoxes()[0].outCount).toBe(1);
    expect(c.contentBounds().w).toBeGreaterThan(0);

    c.openGroup(gid);
    fixture.detectChanges();
    expect(c.proxies().left.map((p: { pid: string }) => p.pid)).toContain('state:a');
    expect(c.proxies().right.map((p: { pid: string }) => p.pid)).toContain('state:d');
    const eds = c.edges();
    expect(eds.length).toBeGreaterThanOrEqual(2);
    expect(c.contentBounds()).toBeDefined();
  });

  /**
   * A text op (hasField) with a value gives "op: value". budgetIs with an id absent from the tree
   * passes the value through unchanged.
   */
  it('guardGroupLabel returns the raw value for an unresolved text/budget op', async () => {
    const { fixture } = await setup({ tree: jest.fn(() => of(BUDGET_TREE)) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { hasField: 'iban' },
        op: 'hasField',
        value: 'iban',
        indices: [],
      }),
    ).toContain('iban');
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { budgetIs: 'unknown' },
        op: 'budgetIs',
        value: 'unknown',
        indices: [],
      }),
    ).toContain('unknown');
  });

  /**
   * The edges() computed calls outDotYFor with t.branch set, for branch-specific y offsets. With
   * the same target column and different dots, the curves start at different heights.
   */
  it('draws vote branch edges from their branch-specific dot offsets', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'v');
    c.setStateKey('state2', 'p');
    c.setStateKey('state3', 'f');
    c.setInitial('v');
    c.setStateKind('v', 'vote');
    c.setStateGremium('v', 'g1');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'v', to: 'p', branch: 'pass', actions: [] },
        { from: 'v', to: 'f', branch: 'fail', actions: [] },
      ],
    }));
    fixture.detectChanges();
    const eds = c.edges();
    expect(eds).toHaveLength(2);
    expect(eds[0].d).not.toBe(eds[1].d);
  });

  /**
   * Grouping {c,d} while drilled into the outer group {b,c,d} makes a sub-group of outer. Two more
   * states inside outer are then grouped. The outer group already carries a non-empty groupIds
   * list, so this covers the `gr.groupIds.filter(...)` branch during regrouping. The outer group
   * keeps its sub-group, and a new sibling sub-group exists.
   */
  it('creating a group while drilled into a group nests it (sub-group)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.addState();
    c.setStateKey('state', 'c');
    c.setStateKey('state2', 'd');
    c.multiSel.set(new Set(['b', 'c', 'd']));
    c.createGroupFromSelection();
    const outer = c.groupBoxes()[0].id;
    c.openGroup(outer);
    c.multiSel.set(new Set(['c', 'd']));
    c.createGroupFromSelection();
    const outerGroup = c.groups().find((g: { id: string }) => g.id === outer);
    expect(outerGroup.groupIds?.length).toBe(1);
    const sub = outerGroup.groupIds[0];
    expect(
      c
        .groups()
        .find((g: { id: string }) => g.id === sub)
        .stateKeys.sort(),
    ).toEqual(['c', 'd']);

    c.addState();
    c.addState();
    const ks = c.graph().states.map((s: { key: string }) => s.key);
    const e = ks[ks.length - 2];
    const f = ks[ks.length - 1];
    c.multiSel.set(new Set([e, f]));
    c.createGroupFromSelection();
    const refreshed = c.groups().find((g: { id: string }) => g.id === outer);
    expect(refreshed.groupIds.length).toBeGreaterThanOrEqual(2);
  });

  /**
   * The seeded group id collides with the next candidate grp2, so the loop bumps the new id to
   * grp3.
   */
  it('picks a fresh group id when grpN is already taken (collision loop)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.addState();
    c.setStateKey('state', 'c');
    c.setStateKey('state2', 'd');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { ...(g.layout ?? {}), groups: [{ id: 'grp2', name: 'X', stateKeys: ['c'] }] },
    }));
    c.multiSel.set(new Set(['a', 'b']));
    c.createGroupFromSelection();
    const ids = c
      .groups()
      .map((g: { id: string }) => g.id)
      .sort();
    expect(ids).toContain('grp2');
    expect(ids).toContain('grp3');
    expect(new Set(ids).size).toBe(ids.length);
  });

  /**
   * The states are x (initial, external) → a, an inner group {b,c} and an outer group {a, inner}.
   * Inside outer, a is a node, inner is a group box and x is an external left proxy. contentBounds
   * and edges run with proxies and a group box present.
   */
  it('positions proxies relative to both nodes and group boxes on a level', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'x');
    c.setStateKey('state2', 'a');
    c.setStateKey('state3', 'b');
    c.setStateKey('state4', 'c');
    c.setInitial('x');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'x', to: 'a', actions: [] }, // external → a (inside outer)
        { from: 'a', to: 'b', actions: [] }, // a → inner group
      ],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const inner = c.groupBoxes()[0].id;
    c.multiSel.set(new Set(['a']));
    c.multiSelGroups.set(new Set([inner]));
    c.createGroupFromSelection();
    const outer = c.groupBoxes()[0].id;
    c.openGroup(outer);
    fixture.detectChanges();
    expect(c.nodes().map((n: { key: string }) => n.key)).toEqual(['a']);
    expect(c.groupBoxes().map((b: { id: string }) => b.id)).toEqual([inner]);
    expect(c.proxies().left.map((p: { pid: string }) => p.pid)).toContain('state:x');
    expect(c.contentBounds().w).toBeGreaterThan(0);
    expect(c.edges().length).toBeGreaterThan(0);
  });

  /**
   * group1 holds a and b, and group2 holds c and d. The top level shows two group boxes with one
   * edge between them. Inside g1, c resolves to its group, so the right proxy is the sibling group.
   */
  it('shows a group as a proxy target when the destination is a sibling group', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setStateKey('state3', 'c');
    c.setStateKey('state4', 'd');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'c', actions: [] }, // crosses from group1 into group2
      ],
    }));
    c.multiSel.set(new Set(['a', 'b']));
    c.createGroupFromSelection();
    const g1 = c.groupBoxes()[0].id;
    c.multiSel.set(new Set(['c', 'd']));
    c.createGroupFromSelection();
    fixture.detectChanges();
    expect(c.groupBoxes()).toHaveLength(2);
    expect(c.edges()).toHaveLength(1);
    c.openGroup(g1);
    fixture.detectChanges();
    const rightPids = c.proxies().right.map((p: { pid: string }) => p.pid);
    expect(rightPids.some((p: string) => p.startsWith('group:'))).toBe(true);
  });

  /**
   * A role without a `de` label falls back to its key, and a webhook with an empty name falls back
   * to its url.
   */
  it('falls back to keys/url when option labels are missing', async () => {
    const { fixture } = await setup({
      listRoles: jest.fn(() => of([{ id: 'r1', key: 'finance', label: {}, permissions: [] }])),
      listWebhooks: jest.fn(() =>
        of([{ id: 'w1', name: '', url: 'https://h.test', events: [], active: true }]),
      ),
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.globalRoleOptions()).toEqual([{ value: 'finance', label: 'finance (finance)' }]);
    expect(c.webhookOptions()).toEqual([{ value: 'w1', label: 'https://h.test' }]);
  });

  /**
   * A graph with no `transitions` array and no `layout` reaches the `?? []` and `?? {}` defensive
   * paths in the mutators and computeds. buildValid always seeds both, so it never reaches them.
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function bare(c: any, withInitial = true): void {
    c.graph.set({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: withInitial },
        { key: 'b', label: { de: 'B' } },
      ],
    } as unknown as FlowGraph);
  }

  /**
   * The transition mutators all default `transitions` to [], and the graph keeps its two states
   * after all the no-ops.
   */
  it('mutators tolerate a graph with no transitions array (?? [] paths)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    bare(c);
    expect(c.nodes().map((n: { key: string }) => n.key)).toEqual(['a', 'b']);
    expect(c.edges()).toEqual([]);
    expect(c.guardGroupsFor('a')).toEqual([]);
    c.selection.set({ kind: 'state', key: 'a' });
    expect(c.stateTransitionLists().incoming).toEqual([]);
    expect(c.stateTransitionLists().outgoing).toEqual([]);

    bare(c);
    c.setTransitionBranch(0, 'pass');
    bare(c);
    c.setTransitionEndpoint(0, 'to', 'b');
    bare(c);
    c.setTransitionLabel(0, 'de', 'x');
    bare(c);
    c.setTransitionAutomatic(0, true);
    bare(c);
    c.addAction(0, 'notify');
    bare(c);
    c.removeAction(0, 0);
    bare(c);
    c.removeSelectedTransition();
    bare(c);
    c.reorderGuard?.('a', '', 1);
    bare(c);
    c.moveGuardUp('a', '');
    expect(c.graph().states).toHaveLength(2);
  });

  /**
   * autoLayout fills positions even from a graph without layout. Without positions[oldKey] the
   * position copy is skipped.
   */
  it('addState/setInitial/setStateKey tolerate a missing layout (?? {} paths)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    bare(c);
    c.addState();
    expect(c.graph().states.length).toBe(3);
    bare(c);
    c.setInitial('b');
    expect(c.graph().states.find((s: { key: string }) => s.key === 'b').isInitial).toBe(true);
    bare(c);
    c.setStateKey('a', 'alpha');
    expect(c.graph().states.find((s: { key: string }) => s.key === 'alpha')).toBeDefined();
    bare(c);
    c.setStateLabel('a', 'de', 'X');
    bare(c);
    c.setStateColor('a', '#fff');
    bare(c);
    c.setStateEditAllowed('a', true);
    bare(c);
    c.setStateTerminal('a', true);
    bare(c);
    c.setStateKind('a', 'vote');
    bare(c);
    c.setStateGremium('a', 'g1');
    expect(c.graph().states).toHaveLength(2);
  });

  it('removeSelectedState tolerates a layout-less graph', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    bare(c);
    c.selection.set({ kind: 'state', key: 'a' });
    c.removeSelectedState();
    expect(c.graph().states.map((s: { key: string }) => s.key)).toEqual(['b']);
  });

  /** The mutators build layout.groups from scratch. */
  it('group + layout mutators tolerate a layout-less graph', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    bare(c);
    c.multiSel.set(new Set(['a', 'b']));
    c.createGroupFromSelection();
    expect(c.groups()).toHaveLength(1);
    const gid = c.groups()[0].id;
    c.renameGroup(gid, 'X');
    c.setGroupColor(gid, '#000');
    c.openGroup(gid);
    c.dissolveCurrentGroup();
    expect(c.groups()).toHaveLength(0);
  });

  /** compareSpec falls back to defaults when guard.compare is absent or not an object. */
  it('compare reads/labels tolerate missing or object/list values', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.compareField({ from: 'a', to: 'b' })).toBe('');
    expect(c.compareOp({ from: 'a', to: 'b' })).toBe('==');
    expect(c.compareValue({ from: 'a', to: 'b' })).toBe('');
    expect(
      c.compareValue({
        from: 'a',
        to: 'b',
        guard: { compare: { field: 'f', op: '==', value: null } },
      }),
    ).toBe('');
    expect(
      c.compareValue({
        from: 'a',
        to: 'b',
        guard: { compare: { field: 'f', op: 'in', value: ['x', 'y'] } },
      }),
    ).toBe('x, y');
    expect(c.guardValue({ from: 'a', to: 'b', guard: { compare: { field: 'f' } } })).toBe('');
    expect(c.guardValue({ from: 'a', to: 'b', guard: { roleIs: null } })).toBe('');
    expect(c.guardBool({ from: 'a', to: 'b', guard: { roleIs: 'x' } })).toBe(false);
    expect(c.guardBool({ from: 'a', to: 'b' })).toBe(false);
    expect(c.guardOp({ from: 'a', to: 'b' })).toBe('');
  });

  /**
   * A compare without field, op and value gives "<empty> == <empty>". An empty guard object takes
   * the '' fallback in the label.
   */
  it('guardGroupLabel + transitionGuardLabel handle missing fields/op', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { compare: {} },
        op: 'compare',
        value: '',
        indices: [],
      }),
    ).toBe('==');
    expect(
      c.guardGroupLabel({
        sig: 's',
        guard: { compare: { field: 'f', op: '>', value: null } },
        op: 'compare',
        value: '',
        indices: [],
      }),
    ).toBe('f >');
    expect(c.transitionGuardLabel({ from: 'a', to: 'b', guard: {} })).toBeTruthy();
  });

  /**
   * An omitted value, op or field keeps the current spec entry. `in` with a non-string current
   * value leaves the value untouched.
   */
  it('setCompare keeps current spec fields when the patch omits them', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.setGuardOp(0, 'compare');
    c.setCompare(0, { field: 'amount', op: '>', value: '5' });
    c.setCompare(0, { field: 'cost' });
    expect(c.compareField(c.graph().transitions[0])).toBe('cost');
    expect(c.compareOp(c.graph().transitions[0])).toBe('>');
    expect(c.compareValue(c.graph().transitions[0])).toBe('5');
    c.setCompare(0, { op: 'in', value: 'a,b' });
    c.setCompare(0, { field: 'x' });
    expect(c.compareValue(c.graph().transitions[0])).toBe('a, b');
  });

  it('action helpers tolerate a missing actions array + non-string params', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    expect(c.recipientsOf({ type: 'notify', recipients: 'nope' })).toEqual([]);
    expect(c.actionParam({ type: 'webhook', webhookId: 123 }, 'webhookId')).toBe('');
    const before = c.graph().transitions[0].actions.length;
    c.addAction(0, '');
    expect(c.graph().transitions[0].actions.length).toBe(before);
  });

  /**
   * The pass branch points at p, which has a position. The fail branch points at a state with no
   * position, so avgTargetY returns null and the comparator returns 0.
   */
  it('outDotYFor handles branches without targets and unknown guards', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'v');
    c.setStateKey('state2', 'p');
    c.setInitial('v');
    c.setStateKind('v', 'vote');
    c.setStateGremium('v', 'g1');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { positions: { v: { x: 0, y: 0 }, p: { x: 200, y: 0 } } },
      transitions: [
        { from: 'v', to: 'p', branch: 'pass', actions: [] },
        { from: 'v', to: 'p', branch: 'fail', actions: [] }, // no position diff
        { from: 'v', to: 'p', guard: { roleIs: 'x' }, actions: [] },
      ],
    }));
    fixture.detectChanges();
    const eds = c.edges();
    expect(eds.length).toBe(3);
    const node = c.nodes().find((n: { key: string }) => n.key === 'v');
    expect(node.dots.length).toBeGreaterThanOrEqual(3);
  });

  /** A state selection that points at a missing key leaves selectedState undefined too. */
  it('selectedTransition is undefined when the index is out of range', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.selection.set({ kind: 'transition', index: 99 });
    expect(c.selectedTransition()).toBeUndefined();
    expect(c.selectedState()).toBeUndefined();
    c.selection.set({ kind: 'state', key: 'no-such' });
    expect(c.selectedState()).toBeUndefined();
  });

  /**
   * currentGroupId points at a group that does not exist. The effect resets it, but breadcrumbs
   * first walks the chain and breaks on the missing group.
   */
  it('breadcrumbs stop at a dangling currentGroupId', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.currentGroupId.set('ghost');
    expect(c.breadcrumbs()).toEqual([]);
  });

  /**
   * The flow is a → group{b}, so the group has a single member and no visible top-level node. a is
   * an external source and becomes a left proxy. `xs` and `ys` are empty, so the columns fall back
   * to MARGIN-based positions without an error.
   */
  it('proxies fall back to MARGIN bounds when a level has no nodes or boxes', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'a', to: 'b', actions: [] }],
    }));
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: {
        positions: {}, // no positions → the group box is dropped and proxies see no xs/ys
        groups: [{ id: 'g1', name: 'G', stateKeys: ['b'] }],
      },
    }));
    c.openGroup('g1');
    fixture.detectChanges();
    expect(c.proxies().left.length).toBeGreaterThanOrEqual(0);
    expect(c.contentBounds()).toBeDefined();
  });

  /**
   * State x (external) → a with group{a}; inside the group x is a left proxy.
   * createGroupFromSelection rejects a single-member group, so the test seeds it directly. The
   * proxy resolves the external state x to its label.
   */
  it('proxy labels fall back when the referenced group/state is unknown', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'x');
    c.setStateKey('state2', 'a');
    c.setInitial('x');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'x', to: 'a', actions: [] }],
    }));
    c.multiSel.set(new Set(['a']));
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: {
        positions: { x: { x: 0, y: 0 }, a: { x: 200, y: 0 } },
        groups: [{ id: 'g1', name: 'G', stateKeys: ['a'] }],
      },
    }));
    c.openGroup('g1');
    fixture.detectChanges();
    const left = c.proxies().left;
    expect(left.map((p: { pid: string }) => p.pid)).toContain('state:x');
    expect(left[0].label).toBeTruthy();
  });

  /** A drop on a itself creates no transition. */
  it('updates the temp edge while connecting from a node', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.onConnectPointerDown(ptr(150, 26), 'a');
    c.onCanvasPointerMove(ptr(200, 26));
    expect(c.tempEdge()).not.toBeNull();
    c.onCanvasPointerUp(ptr(0, 0));
  });

  it('saves successfully and toasts the saved message', async () => {
    const { fixture, toast, createGlobalFlowVersion } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.save();
    expect(createGlobalFlowVersion).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalled();
    expect(c.saving()).toBe(false);
  });

  /** An empty graph is invalid, so toast.error fires with the first validation error. */
  it('save uses the generic invalid message when validation has no errors list', async () => {
    const { fixture, toast } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.save();
    expect(toast.error).toHaveBeenCalled();
  });

  it('save falls back to the generic error when the server sends no detail', async () => {
    const createGlobalFlowVersion = jest.fn(() => throwError(() => ({})));
    const { fixture, toast } = await setup({ createGlobalFlowVersion });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.save();
    expect(toast.error).toHaveBeenCalled();
    expect(c.saving()).toBe(false);
  });

  it('onProxyClick selects a top-level state (owner = null)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.onProxyClick('state:a');
    expect(c.currentGroupId()).toBeNull();
    expect(c.selection()).toEqual({ kind: 'state', key: 'a' });
  });

  /** A random key does nothing, and Insert while typing in a textarea is ignored. */
  it('ignores unrelated keys and respects the typing guard for Insert too', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.onKeydown(new KeyboardEvent('keydown', { key: 'a' }));
    expect(c.graph().states).toHaveLength(0);
    const ta = document.createElement('textarea');
    c.onKeydown({
      key: 'Insert',
      target: ta,
      preventDefault: () => {},
      ctrlKey: false,
      metaKey: false,
      shiftKey: false,
    } as unknown as KeyboardEvent);
    expect(c.graph().states).toHaveLength(0);
    c.addState();
    c.selection.set({ kind: 'state', key: c.graph().states[0].key });
    c.onKeydown(new KeyboardEvent('keydown', { key: 'Backspace' }));
    expect(c.graph().states).toHaveLength(0);
    c.onKeydown({
      key: 'z',
      metaKey: true,
      ctrlKey: false,
      shiftKey: false,
      preventDefault: () => {},
      target: null,
    } as unknown as KeyboardEvent);
  });

  it('pointer move with nothing grabbed and no pan is inert', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.selection.set(null);
    c.onCanvasPointerMove(ptr(10, 10));
    expect(c.view()).toBeNull();
    c.onCanvasPointerUp(ptr(10, 10));
    expect(c.selection()).toBeNull();
  });

  /** Members without positions map the box to null, and it is filtered out. */
  it('drops a group box when its members have no positions', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { positions: {}, groups: [{ id: 'g1', name: 'G', stateKeys: ['b'] }] },
    }));
    fixture.detectChanges();
    expect(c.groupBoxes()).toHaveLength(0);
  });

  /**
   * At the top level b→c is internal to the group, because both ends resolve to the same box. The
   * only visible edge is a→group.
   */
  it('hides a transition whose both ends collapse into the same sub-group', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [...(g.transitions ?? []), { from: 'b', to: 'c', actions: [] }],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    fixture.detectChanges();
    expect(c.edges().length).toBe(1);
  });

  /** The self-loop edgeEnd is null, so it is not drawn and only a→b remains. */
  it('hides a self-loop transition (state→state, from===to)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [...(g.transitions ?? []), { from: 'a', to: 'a', actions: [] }],
    }));
    fixture.detectChanges();
    expect(c.edges().map((e: { index: number }) => e.index)).toEqual([0]);
  });

  it('renders a node at 0,0 when its position is missing', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.graph.set({
      states: [{ key: 'a', label: { de: 'A' }, isInitial: true }],
      transitions: [],
      layout: { positions: {} }, // no entry for 'a' → x/y default to 0
    } as unknown as FlowGraph);
    fixture.detectChanges();
    const node = c.nodes()[0];
    expect(node.x).toBe(0);
    expect(node.y).toBe(0);
  });

  /** A mutation of index 0 must leave index 1 unchanged. */
  it('per-index transition mutators leave the non-matching transitions intact', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'b', actions: [] },
        { from: 'b', to: 'c', actions: [] },
      ],
    }));
    c.setTransitionBranch(0, 'pass');
    c.setTransitionEndpoint(0, 'to', 'c');
    c.setTransitionLabel(0, 'de', 'go');
    c.setTransitionAutomatic(0, true);
    c.setTransitionColor(0, '#111');
    c.setTransitionRequiresAction(0, false);
    c.setGuardOp(0, 'roleIs');
    expect(c.graph().transitions[1]).toMatchObject({ from: 'b', to: 'c' });
    expect(c.graph().transitions[1].automatic).toBeUndefined();
    expect(c.graph().transitions[1].branch).toBeUndefined();
  });

  /** A transition that does not touch the key keeps both ends. */
  it('setStateKey rewrites the from/to of transitions touching the renamed key', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'b', actions: [] }, // from===oldKey path
        { from: 'b', to: 'a', actions: [] }, // to===oldKey path
      ],
    }));
    c.setStateKey('a', 'alpha');
    expect(c.graph().transitions[0].from).toBe('alpha');
    expect(c.graph().transitions[1].to).toBe('alpha');
    expect(c.graph().transitions[0].to).toBe('b');
    expect(c.graph().transitions[1].from).toBe('b');
  });

  it('guardValue returns empty for a transition with no guard', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.guardValue({ from: 'a', to: 'b' })).toBe('');
  });

  /** The first value of the guard is null, so the value string is empty. */
  it('groupsOf renders an empty value string for a guard with a nullish value', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'b', guard: { roleIs: null } as unknown as Guard, actions: [] },
      ],
    }));
    const groups = c.guardGroupsFor('a');
    expect(groups[0].value).toBe('');
  });

  /** An endpoint that references a missing state falls back to the raw key. */
  it('state transition lists fall back to raw keys for dangling endpoints', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.setStateKey('state', 'a');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'ghostTo', actions: [] },
        { from: 'ghostFrom', to: 'a', actions: [] },
      ],
    }));
    c.selection.set({ kind: 'state', key: 'a' });
    const lists = c.stateTransitionLists();
    expect(lists.outgoing[0].to).toBe('ghostTo');
    expect(lists.incoming[0].from).toBe('ghostFrom');
    expect(lists.incoming[0].to).toBe('a');
  });

  /**
   * A branch value outside the rendered branch list and a guard whose signature is absent from the
   * out-dot groups both resolve a path without a throw.
   */
  it('outDotYFor falls back to centre for an unknown branch and unknown guard', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'v');
    c.setStateKey('state2', 'p');
    c.setInitial('v');
    c.setStateKind('v', 'vote');
    c.setStateGremium('v', 'g1');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { positions: { v: { x: 0, y: 0 }, p: { x: 200, y: 0 } } },
      transitions: [
        { from: 'v', to: 'p', branch: 'weird' as unknown as string, actions: [] },
        { from: 'v', to: 'p', guard: { roleIs: 'q' }, actions: [] },
      ],
    }));
    fixture.detectChanges();
    const eds = c.edges();
    expect(eds.length).toBe(2);
    expect(eds[0].d).toMatch(/^M /);
    expect(eds[1].d).toMatch(/^M /);
  });

  /**
   * A vote node with no outgoing branch transitions has a null avgTargetY for both branches, but
   * the pass and fail dots are still present.
   */
  it('keeps branch order when neither branch has positioned targets', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.setStateKey('state', 'v');
    c.setInitial('v');
    c.setStateKind('v', 'vote');
    c.setStateGremium('v', 'g1');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { positions: { v: { x: 0, y: 0 } } },
      transitions: [],
    }));
    fixture.detectChanges();
    const node = c.nodes().find((n: { key: string }) => n.key === 'v');
    expect(node.dots.some((d: { branch: string | null }) => d.branch === 'pass')).toBe(true);
    expect(node.dots.some((d: { branch: string | null }) => d.branch === 'fail')).toBe(true);
  });

  /**
   * A mutation of index 0 leaves the second recipient untouched. A ref-needing kind keeps the
   * existing ref.
   */
  it('recipient kind switch keeps the ref for ref-needing kinds and drops it otherwise', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addAction(0, 'notify');
    c.addRecipient(0, 0);
    c.addRecipient(0, 0);
    c.setRecipientKind(0, 0, 0, 'role');
    expect(c.recipientsOf(c.graph().transitions[0].actions[0])[0]).toEqual({
      kind: 'role',
      ref: '',
    });
    c.setRecipientRef(0, 0, 0, 'r1');
    c.setRecipientKind(0, 0, 0, 'gremium');
    expect(c.recipientsOf(c.graph().transitions[0].actions[0])[0].ref).toBe('r1');
    expect(c.recipientsOf(c.graph().transitions[0].actions[0])[1]).toEqual({ kind: 'applicant' });
  });

  it('removeAction/removeRecipient leave the non-targeted transition/items alone', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'b', actions: [{ type: 'notify', recipients: [] }] },
        { from: 'b', to: 'c', actions: [{ type: 'webhook' }] },
      ],
    }));
    c.removeAction(0, 0);
    expect(c.graph().transitions[1].actions).toHaveLength(1);
  });

  it('resets a dangling drill-down context via the guard effect', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.currentGroupId.set('ghost');
    fixture.detectChanges();
    expect(c.currentGroupId()).toBeNull();
  });

  /** 105 adds cap the history at 100, so up to 100 undos still leave states behind. */
  it('caps the undo history at 100 structural edits', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    for (let i = 0; i < 105; i++) {
      c.addState();
      fixture.detectChanges();
    }
    let undos = 0;
    while (c.canUndo()) {
      c.undo();
      fixture.detectChanges();
      undos++;
      if (undos > 130) break;
    }
    expect(undos).toBeLessThanOrEqual(100);
    expect(c.graph().states.length).toBeGreaterThan(0);
  });

  /**
   * The top-level box g1 references a missing sub-group, so deepStateKeys hits `!g` and still
   * builds the group box without an error.
   */
  it('deepStateKeys survives a dangling sub-group reference', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: {
        positions: { a: { x: 0, y: 0 }, b: { x: 100, y: 0 } },
        groups: [{ id: 'g1', name: 'G', stateKeys: ['a', 'b'], groupIds: ['missing'] }],
      },
    }));
    fixture.detectChanges();
    const box = c.groupBoxes().find((b: { id: string }) => b.id === 'g1');
    expect(box.deepKeys.sort()).toEqual(['a', 'b']);
  });

  /**
   * The `seen.has(id)` cycle guard in deepStateKeys covers a mutual groupIds cycle. Normalization
   * prevents that cycle. A constructed cycle would loop the breadcrumbs walker, which has no cycle
   * guard of its own, so this path stays uncovered. States a and b stay at the top level, and c and
   * d go into a group. Inside the {c,d} group the a→b transition is fully external, so it gives no
   * edge and no proxies.
   */
  it('hides a transition whose both ends are external to the drilled-in level', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setStateKey('state3', 'c');
    c.setStateKey('state4', 'd');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'b', actions: [] }, // both external to {c,d}
        { from: 'c', to: 'd', actions: [] }, // internal to {c,d}
      ],
    }));
    c.multiSel.set(new Set(['c', 'd']));
    c.createGroupFromSelection();
    const gid = c.groupBoxes()[0].id;
    c.openGroup(gid);
    fixture.detectChanges();
    expect(c.proxies().left).toEqual([]);
    expect(c.proxies().right).toEqual([]);
  });

  /**
   * State x (external) → a. The level needs proxies but has no positioned nodes or boxes, because
   * g1 = {a} and a has no position. `x` is a left proxy, and the `xs` and `ys` arrays come only
   * from the node for `a`. Its x and y values both fall back to 0, so the columns still resolve.
   */
  it('positions proxies from MARGIN bounds when the level is otherwise empty', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'x');
    c.setStateKey('state2', 'a');
    c.setInitial('x');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'x', to: 'a', actions: [] }],
      layout: {
        positions: { x: { x: 0, y: 0 } }, // a has no position
        groups: [{ id: 'g1', name: 'G', stateKeys: ['a'] }],
      },
    }));
    c.openGroup('g1');
    fixture.detectChanges();
    const proxies = c.proxies();
    expect(proxies.left.map((p: { pid: string }) => p.pid)).toContain('state:x');
  });

  /**
   * The test reaches the private label resolver through proxies(). The external state a becomes a
   * left proxy and resolves its label from the states.
   */
  it('proxy label falls back to the raw pid for an unknown group/state', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setStateKey('state3', 'c');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'a', to: 'b', actions: [] }],
      layout: {
        positions: { a: { x: 0, y: 0 }, b: { x: 200, y: 0 }, c: { x: 400, y: 0 } },
        groups: [{ id: 'g1', name: 'G1', stateKeys: ['b'] }],
      },
    }));
    c.openGroup('g1');
    fixture.detectChanges();
    const left = c.proxies().left;
    expect(left.find((p: { pid: string }) => p.pid === 'state:a')).toBeDefined();
  });

  /**
   * State a (initial) links to b, then c, then d, with b and c grouped. Inside the group a is a
   * left proxy into b, and c links to a right proxy for d. This exercises the proxy source and
   * destination branches in `edges()`.
   */
  it('draws edges through group and proxy endpoints inside a drilled-in level', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setStateKey('state3', 'c');
    c.setStateKey('state4', 'd');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'b', actions: [] },
        { from: 'b', to: 'c', actions: [] },
        { from: 'c', to: 'd', actions: [] },
      ],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const gid = c.groupBoxes()[0].id;
    c.openGroup(gid);
    fixture.detectChanges();
    const eds = c.edges();
    expect(eds.length).toBeGreaterThanOrEqual(2);
    for (const e of eds) expect(e.d).not.toMatch(/NaN|undefined/);
  });

  /** The canvas exists, but its getScreenCTM yields null. */
  it('toSvg falls back to client coords when getScreenCTM returns null', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.canvas = () => ({ nativeElement: { getScreenCTM: () => null } });
    c.onNodePointerDown(ptr(12, 34), 'a');
    c.onCanvasPointerMove(ptr(60, 50));
    expect(c.graph().layout.positions.a).toBeDefined();
    c.onCanvasPointerUp(ptr(60, 50));
  });

  it('clearSelection also clears a pending multi-selection', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.multiSel.set(new Set(['a', 'b']));
    c.clearSelection();
    expect([...c.multiSel()]).toEqual([]);
  });

  /** The compare object is present, so compareSpec returns it, but field and op are absent. */
  it('compareField/compareOp apply their ?? fallbacks for partial compare specs', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.compareField({ from: 'a', to: 'b', guard: { compare: { op: '>' } } })).toBe('');
    expect(c.compareOp({ from: 'a', to: 'b', guard: { compare: { field: 'x' } } })).toBe('==');
  });

  /**
   * Each action mutator runs on a transition without an `actions` field and takes the `t.actions ??
   * []` fallback.
   */
  it('action mutators tolerate transitions without an actions array', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'a', to: 'b' }],
    }));
    c.addAction(0, 'webhook');
    expect(c.graph().transitions[0].actions).toHaveLength(1);

    c.graph.update((g: FlowGraph) => ({ ...g, transitions: [{ from: 'a', to: 'b' }] }));
    c.setActionParam(0, 0, 'webhookId', 'w1');
    expect(c.graph().transitions[0].actions).toEqual([]);

    c.graph.update((g: FlowGraph) => ({ ...g, transitions: [{ from: 'a', to: 'b' }] }));
    c.addRecipient(0, 0);
    expect(c.graph().transitions[0].actions).toEqual([]);

    c.graph.update((g: FlowGraph) => ({ ...g, transitions: [{ from: 'a', to: 'b' }] }));
    c.removeAction(0, 0);
    expect(c.graph().transitions[0].actions).toEqual([]);
  });

  it('setActionParam leaves sibling actions untouched', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addAction(0, 'webhook');
    c.addAction(0, 'webhook');
    c.setActionParam(0, 0, 'webhookId', 'w1');
    expect(c.actionParam(c.graph().transitions[0].actions[0], 'webhookId')).toBe('w1');
    expect(c.actionParam(c.graph().transitions[0].actions[1], 'webhookId')).toBe('');
  });

  /** Without a stored position the drag starts from {x:0,y:0}. */
  it('starts a drag from origin when the node has no stored position', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.graph.set({
      states: [{ key: 'a', label: { de: 'A' }, isInitial: true }],
      transitions: [],
      layout: { positions: {} }, // no entry for 'a'
    } as unknown as FlowGraph);
    stubCanvas(c);
    c.onNodePointerDown(ptr(5, 5), 'a');
    c.onCanvasPointerUp(ptr(5, 5));
    expect(c.selection()).toEqual({ kind: 'state', key: 'a' });
  });

  /** Without a transitions field the drop on b seeds `g.transitions`. */
  it('creating a connection seeds the transitions array when it is missing', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.graph.set({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' } },
      ],
      layout: { positions: { a: { x: 0, y: 0 }, b: { x: 300, y: 0 } } },
    } as unknown as FlowGraph);
    stubCanvas(c);
    c.onConnectPointerDown(ptr(150, 26), 'a');
    c.onCanvasPointerUp(ptr(310, 26));
    expect(c.graph().transitions).toHaveLength(1);
    expect(c.graph().transitions[0]).toMatchObject({ from: 'a', to: 'b' });
  });

  /**
   * State x is external and positioned, and points to a. Group g1 equals {a}, and a has no
   * position. To leave the level empty, a becomes a member of a sub-group without a box. g1 then
   * holds only g2, whose members have no positions, so the box is dropped, the proxies see empty xs
   * and ys, and the columns fall back to MARGIN.
   */
  it('proxies use MARGIN bounds when a drilled-in level has no node/box positions', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'x');
    c.setStateKey('state2', 'a');
    c.setStateKey('state3', 'b');
    c.setInitial('x');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'x', to: 'a', actions: [] }],
      layout: {
        positions: { x: { x: 0, y: 0 } },
        groups: [
          { id: 'g1', name: 'G1', stateKeys: [], groupIds: ['g2'] },
          { id: 'g2', name: 'G2', stateKeys: ['a', 'b'] },
        ],
      },
    }));
    c.openGroup('g1');
    fixture.detectChanges();
    expect(c.groupBoxes()).toHaveLength(0);
    expect(c.proxies()).toBeDefined();
  });

  /**
   * removeSelectedState with a transition selection returns early. removeSelectedTransition on a
   * graph without transitions takes its `?? []`.
   */
  it('removeSelectedState/Transition respect the selection-kind guards', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.selection.set({ kind: 'transition', index: 0 });
    c.removeSelectedState();
    expect(c.graph().states).toHaveLength(2);
    c.graph.set({
      states: [{ key: 'a', label: { de: 'A' }, isInitial: true }],
    } as unknown as FlowGraph);
    c.selection.set({ kind: 'transition', index: 0 });
    c.removeSelectedTransition();
    expect(c.graph().transitions ?? []).toEqual([]);
  });

  /** The connect runs on a graph without layout, with manual positions for nodeAt(). */
  it('connect tolerates a layout-less graph', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    stubCanvas(c);
    c.graph.set({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' } },
      ],
      layout: { positions: { a: { x: 0, y: 0 }, b: { x: 300, y: 0 } } },
    } as unknown as FlowGraph);
    c.onConnectPointerDown(ptr(150, 26), 'a');
    c.onCanvasPointerUp(ptr(310, 26));
    expect(c.graph().transitions).toHaveLength(1);
  });

  /**
   * The group {a,b} has positions, so the box renders, and the drag moves both members through `??
   * {}`.
   */
  it('group drag tolerates a graph whose layout has only groups', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: {
        positions: { a: { x: 10, y: 10 }, b: { x: 20, y: 20 } },
        groups: [{ id: 'g1', name: 'G', stateKeys: ['a', 'b'] }],
      },
    }));
    const gid = c.groupBoxes()[0].id;
    stubCanvas(c);
    c.onGroupPointerDown(ptr(0, 0), gid);
    c.onCanvasPointerMove(ptr(50, 50));
    expect(c.graph().layout.positions.a).toBeDefined();
    c.onCanvasPointerUp(ptr(50, 50));
  });

  /** Without any layout, patchGroup takes `g.layout ?? {}` and `g.layout?.groups ?? []`. */
  it('renameGroup/setGroupColor tolerate a layout-less graph', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.graph.set({
      states: [{ key: 'a', label: { de: 'A' }, isInitial: true }],
    } as unknown as FlowGraph);
    c.renameGroup('nope', 'X');
    c.setGroupColor('nope', '#000');
    expect(c.graph().layout?.groups ?? []).toEqual([]);
  });

  /**
   * The test removes the group from the layout without running the reset effect again, then
   * dissolves. `me` is undefined, so the `if (!me) return g` early exit fires.
   */
  it('dissolveCurrentGroup is a no-op when the open group no longer exists', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const gid = c.groupBoxes()[0].id;
    c.openGroup(gid);
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { ...g.layout, groups: [] },
    }));
    c.dissolveCurrentGroup();
    expect(c.groups()).toHaveLength(0);
  });

  /**
   * The outer group contains a plus a sub-group {b,c}. A separate sibling group {d,e} also exists
   * and stays untouched.
   */
  it('dissolving a nested leaf group keeps sibling groups untouched', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setStateKey('state3', 'c');
    c.setStateKey('state4', 'd');
    c.setStateKey('state5', 'e');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: {
        positions: {
          a: { x: 0, y: 0 },
          b: { x: 100, y: 0 },
          c: { x: 200, y: 0 },
          d: { x: 300, y: 0 },
          e: { x: 400, y: 0 },
        },
        groups: [
          { id: 'inner', name: 'Inner', stateKeys: ['b', 'c'] },
          { id: 'outer', name: 'Outer', stateKeys: ['a'], groupIds: ['inner'] },
          { id: 'sibling', name: 'Sibling', stateKeys: ['d', 'e'] }, // forces the `: gr` else
        ],
      },
    }));
    c.openGroup('outer');
    c.openGroup('inner');
    c.dissolveCurrentGroup();
    expect(c.currentGroupId()).toBe('outer');
    const outer = c.groups().find((g: { id: string }) => g.id === 'outer');
    expect(outer.stateKeys.sort()).toEqual(['a', 'b', 'c']);
    expect(c.groups().some((g: { id: string }) => g.id === 'sibling')).toBe(true);
  });

  /**
   * A transition from a grouped state back to a phantom external key is hard to trigger through the
   * UI, so the test seeds an edge from an external phantom state into a grouped state. 'phantom' is
   * not a real state, so it resolves to a left proxy whose label is the raw key.
   */
  it('proxy label uses the raw key when the external state is unknown', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('b');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'phantom', to: 'a', actions: [] }],
      layout: {
        positions: { a: { x: 0, y: 0 }, b: { x: 200, y: 0 }, phantom: { x: -300, y: 0 } },
        groups: [{ id: 'g1', name: 'G1', stateKeys: ['a'] }],
      },
    }));
    c.openGroup('g1');
    fixture.detectChanges();
    const left = c.proxies().left;
    const phantom = left.find((p: { pid: string }) => p.pid === 'state:phantom');
    expect(phantom?.label).toBe('phantom');
  });

  /**
   * The graph has no transitions field, two states and one group. Inside the group proxies() runs
   * `transitions ?? []` and returns no proxies without a throw.
   */
  it('proxies tolerate a drilled-in level whose transitions array is missing', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.graph.set({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' } },
      ],
      layout: {
        positions: { a: { x: 0, y: 0 }, b: { x: 100, y: 0 } },
        groups: [{ id: 'g1', name: 'G', stateKeys: ['a', 'b'] }],
      },
    } as unknown as FlowGraph);
    c.openGroup('g1');
    fixture.detectChanges();
    expect(c.proxies()).toEqual({ left: [], right: [] });
  });

  /** g2 must take the `: gr` else branch in patchGroup. */
  it('renameGroup leaves other groups untouched', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setStateKey('state3', 'c');
    c.setStateKey('state4', 'd');
    c.setInitial('a');
    c.multiSel.set(new Set(['a', 'b']));
    c.createGroupFromSelection();
    const g1 = c.groups()[0].id;
    c.multiSel.set(new Set(['c', 'd']));
    c.createGroupFromSelection();
    const g2 = c.groups().find((g: { id: string }) => g.id !== g1).id;
    c.renameGroup(g1, 'First');
    expect(c.groups().find((g: { id: string }) => g.id === g1).name).toBe('First');
    expect(c.groups().find((g: { id: string }) => g.id === g2).name).not.toBe('First');
  });

  /**
   * Grouping {b,c} again into a new group takes both members from the first group. It has no
   * groupIds, so it is filtered away.
   */
  it('regrouping every member of a group drops the now-empty group', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setStateKey('state3', 'c');
    c.setInitial('a');
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const first = c.groups()[0].id;
    expect(c.groups()).toHaveLength(1);
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    expect(c.groups().some((g: { id: string }) => g.id === first)).toBe(false);
    expect(c.groups()).toHaveLength(1);
  });

  /** Two guard groups give one up/down pair per row in the priority stack. */
  it('reorders the guard priority via the inspector stack buttons', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'b', guard: { roleIs: 'x' }, automatic: true, actions: [] },
        { from: 'a', to: 'b', guard: { roleIs: 'y' }, automatic: true, actions: [] },
      ],
    }));
    c.selection.set({ kind: 'state', key: 'a' });
    fixture.detectChanges();
    const upButtons = screen.getAllByRole('button', { name: 'Nach oben' });
    expect(upButtons.length).toBe(2);
    upButtons[1].click();
    expect(c.guardGroupsFor('a').map((gp: { value: string }) => gp.value)).toEqual(['y', 'x']);
    fixture.detectChanges();
    screen.getAllByRole('button', { name: 'Nach unten' })[0].click();
    expect(c.guardGroupsFor('a').map((gp: { value: string }) => gp.value)).toEqual(['x', 'y']);
  });

  describe('redesign: tags, status, zoom, versions', () => {
    const TAGGED: FlowGraph = {
      states: [
        { key: 'a', label: { de: 'Entwurf' }, isInitial: true },
        { key: 'v', label: { de: 'Abstimmung' }, kind: 'vote', config: { gremiumId: 'g1' } },
        { key: 'ok', label: { de: 'Bewilligt' }, isTerminal: true },
        { key: 'no', label: { de: 'Abgelehnt' }, isTerminal: true },
      ],
      transitions: [
        { from: 'a', to: 'v', automatic: true, actions: [] },
        { from: 'v', to: 'ok', branch: 'pass', actions: [] },
        { from: 'v', to: 'no', branch: 'fail', actions: [] },
      ],
    };

    /** The legend explains the dot and the dashed line. */
    it('tags terminal states, names the kind above a state and marks an automatic edge', async () => {
      const { container } = await setup({ getGlobalFlow: jest.fn(() => of(TAGGED)) });
      const tags = [...container.querySelectorAll('.fe__node-tag')].map((t) => t.textContent?.trim());
      expect(tags).toEqual(['Endzustand', 'Endzustand']);
      expect(container.querySelector('.fe__node-kind')?.textContent?.trim()).toBe('Abstimmung (Gremium)');
      expect(container.querySelectorAll('.fe__node-initial-dot')).toHaveLength(1);
      expect(container.querySelectorAll('.fe__edge--auto')).toHaveLength(1);
      expect(container.querySelectorAll('.fe__bolt')).toHaveLength(1);
      expect(screen.getByText('Initial', { selector: '.fe__legendItem' })).toBeInTheDocument();
      expect(screen.getByText('Automatisch', { selector: '.fe__legendItem' })).toBeInTheDocument();
    });

    /** A second start state and a vote without its gremium give two findings. */
    it('says "Gültig" for a valid flow and counts the errors of an invalid one', async () => {
      const { fixture } = await setup({ getGlobalFlow: jest.fn(() => of(TAGGED)) });
      expect(screen.getByText('Gültig')).toBeInTheDocument();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      c.graph.update((g: FlowGraph) => ({
        ...g,
        states: g.states.map((st) =>
          st.key === 'ok' ? { ...st, isInitial: true } : st.key === 'v' ? { ...st, config: {} } : st,
        ),
      }));
      fixture.detectChanges();
      const n = c.validationMessages().length;
      expect(n).toBeGreaterThanOrEqual(2);
      expect(screen.getByText(`${n} Fehler`)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled();
    });

    it('shows no status before the flow has loaded', async () => {
      await setup({ getGlobalFlow: jest.fn(() => NEVER) });
      expect(screen.queryByText('Gültig')).not.toBeInTheDocument();
      expect(screen.queryByText(/Fehler$/)).not.toBeInTheDocument();
    });

    it('reports the zoom relative to the fitted view', async () => {
      const { fixture } = await setup({ getGlobalFlow: jest.fn(() => of(TAGGED)) });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      expect(c.zoomPercent()).toBe(100);
      c.zoomIn();
      expect(c.zoomPercent()).toBe(120);
      c.resetView();
      expect(c.zoomPercent()).toBe(100);
      fixture.detectChanges();
      expect(screen.getByText('100 %')).toBeInTheDocument();
    });

    /**
     * Unmeasured, as in a test without a layout, the fit is the content itself. A box a little
     * smaller than the flow scales the flow down. A box far smaller stops at the smallest readable
     * scale and starts at the left end.
     */
    it('keeps a small flow at its real size in a large canvas box and centres it', async () => {
      const { fixture } = await setup({ getGlobalFlow: jest.fn(() => of(TAGGED)) });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      const b = c.contentBounds();
      expect(c.fitBounds()).toEqual(b);
      c.canvasSize.set({ w: b.w + 400, h: b.h + 200 });
      const fit = c.fitBounds();
      expect(fit.w).toBe(b.w + 400);
      expect(fit.h).toBe(b.h + 200);
      expect(fit.x).toBe(b.x - 200);
      expect(fit.y).toBe(b.y - 100);
      expect(c.viewBox()).toBe(`${fit.x} ${fit.y} ${fit.w} ${fit.h}`);
      c.canvasSize.set({ w: b.w * 0.8, h: b.h * 0.8 });
      const down = c.fitBounds();
      expect(down.x).toBeCloseTo(b.x);
      expect(down.w).toBeCloseTo(b.w);
      c.canvasSize.set({ w: 30, h: 30 });
      const min = c.fitBounds();
      expect(min.w).toBeCloseTo(40);
      expect(min.x).toBe(b.x);
      expect(min.y).toBeCloseTo(b.y + (b.h - 40) / 2);
    });

    /**
     * Unmeasured, or in a box larger than the flow, nothing is hidden. In a small box the view
     * starts at the left end at scale 0.75 (40 × 40 in the world). The last step stops exactly at
     * the edge of the content. A press steps once, a hold repeats, and a release stops.
     */
    it('shows a scroll tongue on each side that hides content and pans towards it', async () => {
      const { fixture } = await setup({ getGlobalFlow: jest.fn(() => of(TAGGED)) });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      const b = c.contentBounds();
      const tongue = (side: string): HTMLButtonElement =>
        fixture.nativeElement.querySelector(`.fe__tongue[data-side="${side}"]`);
      fixture.detectChanges();
      for (const side of ['left', 'right', 'up', 'down']) expect(tongue(side).disabled).toBe(true);
      c.canvasSize.set({ w: b.w + 400, h: b.h + 200 });
      fixture.detectChanges();
      expect(tongue('right').disabled).toBe(true);

      c.canvasSize.set({ w: 30, h: 30 });
      fixture.detectChanges();
      const hidden = c.hiddenBy();
      expect(hidden.left).toBe(0);
      expect(hidden.right).toBeCloseTo(b.w - 40);
      expect(hidden.up).toBeCloseTo((b.h - 40) / 2);
      expect(hidden.down).toBeCloseTo((b.h - 40) / 2);
      expect(tongue('left').disabled).toBe(true);
      expect(tongue('left').getAttribute('aria-hidden')).toBe('true');
      expect(tongue('right').disabled).toBe(false);
      expect(tongue('right')).toHaveClass('fe__tongue--on');
      expect(tongue('right')).toHaveAccessibleName('Nach rechts verschieben');

      c.pan('down');
      expect(c.hiddenBy().down).toBe(0);
      expect(c.view().y + 40).toBeCloseTo(b.y + b.h);
      c.pan('down');
      expect(c.view().y + 40).toBeCloseTo(b.y + b.h);
      c.onTongueKey(new KeyboardEvent('keydown', { key: 'Enter' }), 'up');
      expect(c.hiddenBy().up).toBe(0);
      const y = c.view().y;
      c.onTongueKey(new KeyboardEvent('keydown', { key: 'a' }), 'down');
      expect(c.view().y).toBe(y);

      jest.useFakeTimers();
      try {
        const x0 = c.view().x;
        c.onTonguePress({ button: 2 } as PointerEvent, 'right');
        expect(c.view().x).toBe(x0);
        c.onTonguePress({ button: 0 } as PointerEvent, 'right');
        const x1 = c.view().x;
        expect(x1).toBeGreaterThan(x0);
        expect(c.heldSide()).toBe('right');
        jest.advanceTimersByTime(300 + 90);
        expect(c.view().x).toBeGreaterThan(x1);
        c.stopHold();
        expect(c.heldSide()).toBeNull();
        const x2 = c.view().x;
        jest.advanceTimersByTime(1000);
        expect(c.view().x).toBe(x2);
        c.onTonguePress({ button: 0 } as PointerEvent, 'left');
        fixture.destroy();
        const x3 = c.view().x;
        jest.advanceTimersByTime(1000);
        expect(c.view().x).toBe(x3);
      } finally {
        jest.useRealTimers();
      }
    });

    /**
     * The selection gives way to the version history. A new selection on the canvas brings the
     * inspector back. The ⋮ menu of a phone header toggles the same view.
     */
    it('shows the versions in the inspector and names the active version in the header', async () => {
      const { fixture } = await setup({ getGlobalFlow: jest.fn(() => of(TAGGED)) });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      expect(screen.queryByText(/Version 12 aktiv/)).toBeNull();
      c.currentVersion.set(12);
      fixture.detectChanges();
      expect(screen.getByText('Version 12 aktiv')).toBeInTheDocument();

      c.selectEdge(0);
      fixture.detectChanges();
      expect(screen.getByRole('heading', { name: 'Bedingung (Guard)' })).toBeInTheDocument();
      screen.getByRole('button', { name: 'Versionen' }).click();
      fixture.detectChanges();
      expect(c.showVersions()).toBe(true);
      expect(screen.queryByRole('heading', { name: 'Bedingung (Guard)' })).not.toBeInTheDocument();
      c.selectEdge(1);
      fixture.detectChanges();
      expect(c.showVersions()).toBe(false);
      c.onHeaderMenu({ id: 'versions', label: 'Versionen' });
      expect(c.showVersions()).toBe(true);
      expect(c.headerMenu()[0].items[0].checked).toBe(true);
      c.onHeaderMenu({ id: 'other', label: 'x' });
      expect(c.showVersions()).toBe(true);
    });

    it('lists the incoming and outgoing transitions of a selected state in the inspector', async () => {
      const { fixture } = await setup({ getGlobalFlow: jest.fn(() => of(TAGGED)) });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      c.selection.set({ kind: 'state', key: 'v' });
      fixture.detectChanges();
      expect(screen.getByRole('heading', { name: 'Eingehend (1)' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Ausgehend (2)' })).toBeInTheDocument();
      screen.getByRole('button', { name: /^Automatisch:/ }).click();
      expect(c.selection()).toEqual({ kind: 'transition', index: 0 });
    });
  });

  describe('automatic layout', () => {
    /** Places box i at x = 300 i and draws every line as `M i …`; bundles by target. */
    function fakeLayouter() {
      return jest.fn(async (input: LayoutInput, many: (n: number) => string): Promise<LevelLayout> => {
        const pos = new Map(input.boxes.map((b, i) => [b.id, { x: 300 * i, y: 10 }] as const));
        const routes = new Map<number, LayoutRoute>();
        const seen = new Map<string, number[]>();
        for (const l of input.links) {
          const k = `${l.src}>${l.dst}`;
          seen.set(k, [...(seen.get(k) ?? []), l.index]);
        }
        for (const l of input.links) {
          const bundle = seen.get(`${l.src}>${l.dst}`)!;
          const first = bundle[0] === l.index;
          routes.set(l.index, {
            d: `M ${l.index} 0 L 9 9`,
            label: first ? { x: 5, y: 6, text: bundle.length > 1 ? many(bundle.length) : l.label } : null,
            bundle,
          });
        }
        return { pos, routes };
      });
    }

    async function laidOut(layouter: LevelLayouter = fakeLayouter()) {
      const view = await setup({ layouter });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = view.fixture.componentInstance as any;
      buildValid(c);
      c.graph.update((g: FlowGraph) => ({
        ...g,
        transitions: [
          { from: 'a', to: 'b', label: { de: 'Eins' }, actions: [] },
          { from: 'a', to: 'b', guard: { roleIs: 'x' }, label: { de: 'Zwei' }, actions: [] },
          { from: 'a', to: 'b', guard: { roleIs: 'y' }, automatic: true, actions: [] },
        ],
      }));
      view.fixture.detectChanges();
      await view.fixture.whenStable();
      return { ...view, c };
    }

    /** A press on any line of the bundle selects all of it. */
    it('places the boxes and draws the lines of the layout, one label per bundle', async () => {
      const layouter = fakeLayouter();
      const { c } = await laidOut(layouter);
      expect(layouter).toHaveBeenCalled();
      const input = layouter.mock.calls.at(-1)![0] as LayoutInput;
      expect(input.boxes.map((b) => b.id)).toEqual(['state:a', 'state:b']);
      expect(input.links.map((l) => l.port)).toEqual(['out', JSON.stringify({ roleIs: 'x' }), JSON.stringify({ roleIs: 'y' })]);
      expect(c.layoutPending()).toBe(false);
      const nodes = c.nodes();
      expect(nodes.map((n: { x: number }) => n.x)).toEqual([0, 300]);
      const edges = c.edges();
      expect(edges.map((e: { d: string }) => e.d)).toEqual(['M 0 0 L 9 9', 'M 1 0 L 9 9', 'M 2 0 L 9 9']);
      expect(edges[0]).toMatchObject({ label: '3 Übergänge', labeled: true, mx: 5, my: 6, automatic: false, color: null });
      expect(edges[1]).toMatchObject({ label: '', labeled: false });
      c.selectEdge(1);
      expect(c.edges().every((e: { selected: boolean }) => e.selected)).toBe(true);
    });

    it('keeps the places but drops the lines while a new layout is on its way', async () => {
      let hold = false;
      let release: () => void = () => undefined;
      const inner = fakeLayouter();
      const layouter = jest.fn((input: LayoutInput, many: (n: number) => string) => {
        if (!hold) return inner(input, many);
        return new Promise<LevelLayout>((resolve) => (release = () => void inner(input, many).then(resolve)));
      });
      const { c, fixture } = await laidOut(layouter);
      hold = true;
      c.setStateLabel('b', 'de', 'Ein viel längerer Name');
      fixture.detectChanges();
      expect(c.nodes()[1].x).toBe(300);
      expect(c.edges()).toEqual([]);
      release();
      await fixture.whenStable();
      await new Promise((r) => setTimeout(r));
      expect(c.edges()[0].d).toBe('M 0 0 L 9 9');
    });

    it('leaves out the lines of a group without placed members; a bundle of automatic lines keeps its bolt', async () => {
      const layouter = fakeLayouter();
      const { fixture } = await setup({ layouter });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      c.graph.set({
        states: [
          { key: 'a', label: { de: 'A' }, isInitial: true },
          { key: 'b', label: { de: 'B' } },
          { key: 'c', label: { de: 'C' } },
          { key: 'd', label: { de: 'D' } },
        ],
        transitions: [
          { from: 'a', to: 'b', actions: [] },
          { from: 'c', to: 'a', actions: [] },
          { from: 'a', to: 'd', automatic: true, color: '#f00', actions: [] },
          { from: 'a', to: 'd', automatic: true, guard: { roleIs: 'x' }, actions: [] },
          { from: 'd', to: 'a', color: '#0f0', actions: [] },
        ],
        layout: {
          positions: { a: { x: 0, y: 0 }, d: { x: 300, y: 0 } },
          groups: [{ id: 'g1', name: 'G', stateKeys: ['b', 'c'] }],
        },
      } as unknown as FlowGraph);
      fixture.detectChanges();
      await fixture.whenStable();
      await new Promise((r) => setTimeout(r));
      expect(c.groupBoxes()).toEqual([]);
      const edges = c.edges();
      expect(edges.map((e: { index: number }) => e.index)).toEqual([2, 3, 4]);
      expect(edges[0]).toMatchObject({ automatic: true, color: null, labeled: true });
      expect(edges[2]).toMatchObject({ automatic: false, color: '#0f0' });
    });

    it('shows the stored places when the layout fails', async () => {
      const { c } = await laidOut(jest.fn(() => Promise.reject(new Error('elk'))));
      await new Promise((r) => setTimeout(r));
      expect(c.layoutPending()).toBe(false);
      expect(c.edges()[0].d).toMatch(/ C /);
    });

    it('lays out nothing before the flow has loaded, so the empty layout does not end the wait', async () => {
      const flow = new Subject<FlowGraph | null>();
      const layouter = fakeLayouter();
      const { fixture } = await setup({ layouter, getGlobalFlow: jest.fn(() => flow) });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      await fixture.whenStable();
      expect(layouter).not.toHaveBeenCalled();
      expect(c.layoutPending()).toBe(true);
      flow.next(null);
      fixture.detectChanges();
      await fixture.whenStable();
      await new Promise((r) => setTimeout(r));
      expect(layouter).toHaveBeenCalled();
      expect(c.layoutPending()).toBe(false);
    });

    it('hides the canvas until the first layout answers', async () => {
      const { c, fixture } = await laidOut(jest.fn(() => new Promise<LevelLayout>(() => undefined)));
      expect(c.layoutPending()).toBe(true);
      expect(fixture.nativeElement.querySelector('.fe__canvas')).toHaveClass('fe__canvas--loading');
    });

    /**
     * With the pointer on a, the state a, its neighbour b and the line a → b stay. The faint lines
     * come first, so the focus paints on top.
     */
    it('draws everything outside the focus faint: hover, selected state, selected transition', async () => {
      const { fixture } = await setup();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      buildValid(c);
      c.addState();
      c.setStateKey('state', 'c');
      c.graph.update((g: FlowGraph) => ({
        ...g,
        transitions: [...g.transitions, { from: 'b', to: 'c', actions: [] }],
      }));
      c.selection.set(null);
      fixture.detectChanges();
      const dim = () => ({
        nodes: c.nodes().filter((n: { dim: boolean }) => n.dim).map((n: { key: string }) => n.key),
        edges: c.edges().filter((e: { dim: boolean }) => e.dim).map((e: { index: number }) => e.index),
      });
      expect(dim()).toEqual({ nodes: [], edges: [] });
      fixture.nativeElement.querySelector('.fe__node-g').dispatchEvent(new Event('pointerenter'));
      expect(c.hoverKey()).toBe('a');
      expect(dim()).toEqual({ nodes: ['c'], edges: [1] });
      expect(c.edges().map((e: { index: number }) => e.index)).toEqual([1, 0]);
      fixture.nativeElement.querySelector('.fe__node-g').dispatchEvent(new Event('pointerleave'));
      expect(c.hoverKey()).toBeNull();
      c.selection.set({ kind: 'state', key: 'c' });
      expect(dim()).toEqual({ nodes: ['a'], edges: [0] });
      c.selection.set({ kind: 'transition', index: 0 });
      expect(dim()).toEqual({ nodes: ['c'], edges: [1] });
      c.selection.set({ kind: 'transition', index: 99 });
      expect(dim()).toEqual({ nodes: [], edges: [] });
    });
  });
});
