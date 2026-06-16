import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { ToastService } from '@shared/ui';
import type { FlowGraph } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { BudgetTreeApi } from '../../budget/budget-tree.api';
import { FlowEditorComponent } from './flow-editor.component';

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
  listDeadlinePolicies?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  listGremienOptions?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  tree?: any;
}

const BUDGET_TREE = [
  {
    id: 'b1', parentId: null, gremiumId: null, key: 'VS-800', pathKey: 'VS-800', name: 'Verwaltung',
    currency: 'EUR', active: true, color: null, acceptedStateKeys: [], deniedStateKeys: [],
    fullyBound: false, hiddenInBudget: false, viewGremiumId: null, fiscalStartMonth: 1,
    fiscalStartDay: 1, byFiscalYear: [],
    children: [
      {
        id: 'b2', parentId: 'b1', gremiumId: null, key: 'VS-800-40', pathKey: 'VS-800-40', name: 'IT',
        currency: 'EUR', active: true, color: null, acceptedStateKeys: [], deniedStateKeys: [],
        fullyBound: false, hiddenInBudget: false, viewGremiumId: null, fiscalStartMonth: 1,
        fiscalStartDay: 1, byFiscalYear: [], children: [],
      },
    ],
  },
];

async function setup(over: Overrides = {}) {
  // Globaler Flow (#28): laden + speichern statt per-Typ.
  const getGlobalFlow = over.getGlobalFlow ?? jest.fn(() => of(null));
  const createGlobalFlowVersion = over.createGlobalFlowVersion ?? jest.fn(() => of({ id: 'gfv1' }));
  const listApplicationTypes = jest.fn(() => of([{ id: 't1', name: 'Finanzantrag' }]));
  // vote/approval-State-Config (#28): Gremien + Gremium-Rollen + globale Rollen.
  const listGremienOptions = over.listGremienOptions ?? jest.fn(() => of([{ id: 'g1', name: 'StuPa', slug: 'stupa', cdVariant: 'stupa', defaultLang: 'de' }]));
  const listGremiumRoles = jest.fn(() => of([{ id: 'gr1', key: 'vorsitz', name: { de: 'Vorsitz' } }]));
  const listRoles = over.listRoles ?? jest.fn(() => of([{ id: 'r1', key: 'finance', label: { de: 'Finanzen' }, permissions: [] }]));
  const listDeadlinePolicies = over.listDeadlinePolicies ?? jest.fn(() => of([{ id: 'dp1', key: 'semester', label: { de: 'Semesterfrist' }, kind: 'absolute' }]));
  const listWebhooks = over.listWebhooks ?? jest.fn(() => of([{ id: 'w1', name: 'Buchhaltung', url: 'https://h.test', events: [], active: true }]));
  const api = { getGlobalFlow, createGlobalFlowVersion, listApplicationTypes, listGremienOptions, listGremiumRoles, listRoles, listDeadlinePolicies, listWebhooks };
  // Kostenstellen (#7): Namen für `budgetIs`-Guard-Labels.
  const budgetApi = { tree: over.tree ?? jest.fn(() => of([])) };
  const toast = { success: jest.fn(), error: jest.fn(), info: jest.fn() };
  const view = await render(FlowEditorComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: BudgetTreeApi, useValue: budgetApi },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, createGlobalFlowVersion, getGlobalFlow, toast };
}

/** Mounts a fake SVG so `toSvg`/`getScreenCTM` returns identity coords. */
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
    clientX, clientY, pointerId: 1, shiftKey: false,
    stopPropagation: () => {}, preventDefault: () => {},
    target: { setPointerCapture: () => {} },
    currentTarget: { setPointerCapture: () => {} },
    ...extra,
  } as unknown as PointerEvent;
}

/** Baut über die Komponenten-API einen gültigen Graphen (a initial → b). */
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

  it('reports an empty graph as invalid and disables save', async () => {
    await setup();
    expect(screen.getByText('flow graph has no states')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled();
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

  it('renders one canvas node per state', async () => {
    const { container, fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    buildValid(fixture.componentInstance as any);
    fixture.detectChanges();
    expect(container.querySelectorAll('.fe__node-text')).toHaveLength(2);
  });

  it('exposes the guard control for a selected transition (auto + manual)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.selectEdge(0);
    fixture.detectChanges();
    // Guard-Editor (Bedingung) erscheint in der Pane unter dem Graphen (#28).
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

    c.relayout();
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

  it('groups outgoing transitions per distinct guard and reorders priority', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    // Zwei guarded + ein guard-loser Übergang von a → unterschiedliche Guards.
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'b', guard: { roleIs: 'x' }, automatic: true, actions: [] },
        { from: 'a', to: 'b', guard: { roleIs: 'y' }, automatic: true, actions: [] },
        { from: 'a', to: 'b', actions: [] },
      ],
    }));

    // Drei unterschiedliche Guards (x, y, kein Guard) → drei Gruppen.
    const groups = c.guardGroupsFor('a');
    expect(groups.map((gp: { value: string }) => gp.value)).toEqual(['x', 'y', '']);
    // Default-Knoten zeigt einen Ausgangs-Punkt je Gruppe.
    const nodeA = c.nodes().find((n: { key: string }) => n.key === 'a');
    expect(nodeA.dots).toHaveLength(3);

    // Priorität: y vor x schieben → Reihenfolge dreht sich.
    c.moveGuardUp('a', JSON.stringify({ roleIs: 'y' }));
    const after = c.guardGroupsFor('a');
    expect(after.map((gp: { value: string }) => gp.value)).toEqual(['y', 'x', '']);
    // order-Felder spiegeln die Array-Reihenfolge (Auswertungspriorität).
    expect(c.graph().transitions.map((t: { order?: number }) => t.order)).toEqual([0, 1, 2]);
  });

  it('undoes and redoes structural edits', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    fixture.detectChanges(); // Historie erfasst den Bau
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
    c.onKeydown({ key: 'Delete', target: input, preventDefault: () => {} } as unknown as KeyboardEvent);
    expect(c.graph().states).toHaveLength(1); // nicht gelöscht
  });

  it('saves nothing and warns when the graph is invalid', async () => {
    const { fixture, createGlobalFlowVersion } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.save();
    expect(createGlobalFlowVersion).not.toHaveBeenCalled();
  });

  // Gruppen (#flow-groups): Kasten auf der Ebene, Drill-Down mit Proxies,
  // Auflösen hebt den Inhalt eine Ebene hoch.
  it('groups render as one box; drill-down shows members + proxies', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c); // a (initial) → b
    c.addState();
    c.setStateKey('state', 'c');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [...(g.transitions ?? []), { from: 'b', to: 'c', actions: [] }],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();

    // Oberste Ebene: nur a sichtbar + ein Gruppen-Kasten; Kante a→b endet am Kasten.
    expect(c.nodes().map((n: { key: string }) => n.key)).toEqual(['a']);
    expect(c.groupBoxes()).toHaveLength(1);
    const groupId = c.groupBoxes()[0].id as string;
    expect(c.edges()).toHaveLength(1); // b→c ist intern unsichtbar

    // Drill-Down: Member sichtbar, externer Ursprung a als Proxy links.
    c.openGroup(groupId);
    expect(c.breadcrumbs().map((g: { id: string }) => g.id)).toEqual([groupId]);
    expect(
      c.nodes().map((n: { key: string }) => n.key).sort(),
    ).toEqual(['b', 'c']);
    expect(c.proxies().left.map((p: { pid: string }) => p.pid)).toEqual(['state:a']);

    // Auflösen: Inhalt zurück auf die oberste Ebene.
    c.dissolveCurrentGroup();
    expect(c.currentGroupId()).toBeNull();
    expect(c.groupBoxes()).toHaveLength(0);
    expect(c.nodes()).toHaveLength(3);
  });

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

    // Oberste Ebene: alles steckt in EINER (äußeren) Gruppe.
    expect(c.nodes()).toHaveLength(0);
    expect(c.groupBoxes()).toHaveLength(1);
    const outer = c.groupBoxes()[0].id as string;
    expect(outer).not.toBe(inner);
    expect(c.groupBoxes()[0].count).toBe(3); // a + b + c (transitiv)

    // In der äußeren Ebene: a als Node + innere Gruppe als Kasten.
    c.openGroup(outer);
    expect(c.nodes().map((n: { key: string }) => n.key)).toEqual(['a']);
    expect(c.groupBoxes().map((b: { id: string }) => b.id)).toEqual([inner]);
    c.openGroup(inner);
    expect(c.breadcrumbs().map((g: { id: string }) => g.id)).toEqual([outer, inner]);
  });

  // --- Constructor: data-loading subscriptions (next + error branches) -------
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
    const { toast } = await setup({ getGlobalFlow: jest.fn(() => throwError(() => new Error('boom'))) });
    expect(toast.error).toHaveBeenCalled();
  });

  it('swallows errors from option/role/webhook/policy/budget loads', async () => {
    const err = jest.fn(() => throwError(() => new Error('x')));
    const { fixture } = await setup({
      listRoles: err, listWebhooks: err, listDeadlinePolicies: err,
      listGremienOptions: err, tree: err,
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.gremiumOptions()).toEqual([]);
    expect(c.globalRoleOptions()).toEqual([]);
    expect(c.webhookOptions()).toEqual([]);
    expect(c.deadlinePolicyOptions()).toEqual([]);
  });

  it('populates option lists and resolves a budget tree (id → "name (key)")', async () => {
    const { fixture } = await setup({ tree: jest.fn(() => of(BUDGET_TREE)) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.globalRoleOptions()).toEqual([{ value: 'finance', label: 'Finanzen (finance)' }]);
    expect(c.webhookOptions()).toEqual([{ value: 'w1', label: 'Buchhaltung' }]);
    expect(c.deadlinePolicyOptions()[0].label).toContain('Semesterfrist');
    // budget guard label resolves the nested UUID to its name
    expect(c.guardGroupLabel({ sig: 'x', guard: { budgetIs: 'b2' }, op: 'budgetIs', value: 'b2', indices: [] }))
      .toContain('IT (VS-800-40)');
  });

  // --- guard labels / value resolution --------------------------------------
  it('renders human-readable guard-group labels for every operator family', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // catch-all (empty signature)
    expect(c.guardGroupLabel({ sig: '', guard: null, op: '', value: '', indices: [] })).toBeTruthy();
    // combinator with children → "(n)"
    expect(c.guardGroupLabel({ sig: 's', guard: { and: [{ roleIs: 'a' }, { roleIs: 'b' }] }, op: 'and', value: '', indices: [] }))
      .toContain('(2)');
    // combinator with non-array child counts as 1
    expect(c.guardGroupLabel({ sig: 's', guard: { not: { roleIs: 'a' } }, op: 'not', value: '', indices: [] }))
      .toContain('(1)');
    // compare with a scalar value
    expect(c.guardGroupLabel({ sig: 's', guard: { compare: { field: 'amount', op: '>', value: 100 } }, op: 'compare', value: '', indices: [] }))
      .toBe('amount > 100');
    // compare with a list value
    expect(c.guardGroupLabel({ sig: 's', guard: { compare: { field: 'k', op: 'in', value: ['x', 'y'] } }, op: 'compare', value: '', indices: [] }))
      .toBe('k in x, y');
    // compare missing the object → falls back to the op label
    expect(c.guardGroupLabel({ sig: 's', guard: { compare: 'nope' }, op: 'compare', value: '', indices: [] })).toBeTruthy();
    // role op resolves the value to a role name
    expect(c.guardGroupLabel({ sig: 's', guard: { roleIs: 'finance' }, op: 'roleIs', value: 'finance', indices: [] }))
      .toContain('Finanzen (finance)');
    // committee op resolves via gremium options
    expect(c.guardGroupLabel({ sig: 's', guard: { isInCommittee: 'g1' }, op: 'isInCommittee', value: 'g1', indices: [] }))
      .toContain('StuPa');
    // text op with empty value → just the op label
    expect(c.guardGroupLabel({ sig: 's', guard: { hasField: '' }, op: 'hasField', value: '', indices: [] })).toBeTruthy();
  });

  it('transitionGuardLabel handles guarded and guard-less transitions', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.transitionGuardLabel({ from: 'a', to: 'b' })).toBeTruthy(); // default
    expect(c.transitionGuardLabel({ from: 'a', to: 'b', guard: { roleIs: 'finance' } })).toContain('Finanzen');
    // object/compare value → blanked op-value path
    expect(c.transitionGuardLabel({ from: 'a', to: 'b', guard: { compare: { field: 'f', op: '==', value: 1 } } })).toBe('f == 1');
  });

  it('lists incoming/outgoing transitions for the selected state and nothing otherwise', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    // no selection → null
    c.selection.set(null);
    expect(c.stateTransitionLists()).toBeNull();
    // transition selection → still null (only state selections produce lists)
    c.selection.set({ kind: 'transition', index: 0 });
    expect(c.stateTransitionLists()).toBeNull();
    c.selection.set({ kind: 'state', key: 'b' });
    const lists = c.stateTransitionLists();
    expect(lists.incoming).toHaveLength(1);
    expect(lists.incoming[0].from).toBe('a');
    expect(lists.outgoing).toHaveLength(0);
  });

  // --- state kind + config (#28) --------------------------------------------
  it('switches a state to vote, sets the committee, and resets config on normal', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    const key = c.graph().states[0].key;
    c.setStateDeadlinePolicy(key, 'semester');
    c.setStateKind(key, 'vote');
    // deadline policy is preserved across the kind switch, gremium is reset
    expect(c.graph().states[0].kind).toBe('vote');
    expect(c.graph().states[0].config.deadlinePolicyKey).toBe('semester');
    c.setStateGremium(key, 'g1');
    expect(c.graph().states[0].config.gremiumId).toBe('g1');
    c.setStateGremium(key, ''); // clearing → undefined
    expect(c.graph().states[0].config.gremiumId).toBeUndefined();
    c.setStateDeadlinePolicy(key, ''); // clearing the policy
    expect(c.graph().states[0].config.deadlinePolicyKey).toBeUndefined();
    c.setStateKind(key, ''); // back to normal → kind null, config emptied
    expect(c.graph().states[0].kind).toBeNull();
    expect(c.graph().states[0].config).toEqual({});
    c.setStateTerminal(key, true);
    expect(c.graph().states[0].isTerminal).toBe(true);
    expect(c.branchesFor(key)).toEqual([]);
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

  // --- guard editors on transitions -----------------------------------------
  it('drives guard bool/compare/value setters and reads them back', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    // boolean op
    c.setGuardOp(0, 'deadlinePassed');
    expect(c.guardBool(c.graph().transitions[0])).toBe(true);
    c.setGuardBool(0, false);
    expect(c.graph().transitions[0].guard).toEqual({ deadlinePassed: false });
    // setGuardBool/Value are no-ops when there is no operator
    c.setGuardOp(0, '');
    c.setGuardBool(0, true);
    c.setGuardValue(0, 'x');
    expect(c.graph().transitions[0].guard).toBeUndefined();
    // full guard tree via setGuard
    c.setGuard(0, { or: [{ roleIs: 'finance' }] });
    expect(c.graph().transitions[0].guard).toEqual({ or: [{ roleIs: 'finance' }] });
    c.setGuard(0, null);
    expect(c.graph().transitions[0].guard).toBeUndefined();
    // compare with `in` splits a comma list
    c.setGuardOp(0, 'compare');
    c.setCompare(0, { op: 'in', value: 'x, y ,z' });
    expect(c.compareValue(c.graph().transitions[0])).toBe('x, y, z');
    expect(c.compareOp(c.graph().transitions[0])).toBe('in');
    // budgetFitsApplication default
    c.setGuardOp(0, 'budgetFitsApplication');
    expect(c.graph().transitions[0].guard).toEqual({ budgetFitsApplication: true });
  });

  it('guardValueKind maps every operator', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.guardValueKind('')).toBe('none');
    expect(c.guardValueKind('deadlinePassed')).toBe('none');
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
    expect(c.recipientKindOptions().length).toBe(4);
    expect(c.actionOptions().length).toBe(4);
    expect(c.actionLabel('notify')).toBeTruthy();
    expect(c.actionDesc('notify')).toBeTruthy();
    expect(c.kindLabel('vote')).toBeTruthy();
    expect(c.guardValueHint('roleIs')).toBeTruthy();
    expect(c.recipientNeedsRef('gremium')).toBe(true);
    expect(c.recipientNeedsRef('applicant')).toBe(false);
  });

  // --- actions: params + notify recipients ----------------------------------
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
    expect(c.recipientsOf(c.graph().transitions[0].actions[ai])[0]).toEqual({ kind: 'gremium', ref: 'g1' });
    // switching back to applicant drops the ref
    c.setRecipientKind(0, ai, 0, 'applicant');
    expect(c.recipientsOf(c.graph().transitions[0].actions[ai])[0].ref).toBeUndefined();
    c.removeRecipient(0, ai, 0);
    expect(c.recipientsOf(c.graph().transitions[0].actions[ai])).toHaveLength(0);
    // recipientsOf on a non-notify action → []
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
    c.setTransitionRequiresAction(0, true); // default → field removed
    expect(c.graph().transitions[0].requiresAction).toBeUndefined();
  });

  it('clears an empty transition label down to null', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.setTransitionLabel(0, 'de', 'go');
    expect(c.graph().transitions[0].label).toEqual({ de: 'go' });
    c.setTransitionLabel(0, 'de', ''); // last language cleared → label null
    expect(c.graph().transitions[0].label).toBeNull();
  });

  // --- group operations: rename/color/dissolve at top level -----------------
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
    c.setGroupColor(gid, ''); // clear color → null
    expect(c.groups()[0].color).toBeNull();
    // dissolve from inside the group lifts members to top level
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
    // proxy click on a state navigates to its owner level + selects it
    c.onProxyClick('state:a');
    expect(c.selection()).toEqual({ kind: 'state', key: 'a' });
    // proxy click on a group navigates into it
    c.onProxyClick(`group:${gid}`);
    expect(c.currentGroupId()).toBe(gid);
  });

  // --- canvas pointer interaction (drag / connect / group drag / pan) -------
  it('drags a node, then a click without movement selects it', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.selection.set(null);
    const before = { ...c.graph().layout.positions.a };
    // drag with movement updates the position
    c.onNodePointerDown(ptr(0, 0), 'a');
    c.onCanvasPointerMove(ptr(120, 80));
    expect(c.graph().layout.positions.a).not.toEqual(before);
    c.onCanvasPointerUp(ptr(120, 80));
    expect(c.selection()).toBeNull(); // moved → not selected

    // click without movement selects
    c.onNodePointerDown(ptr(0, 0), 'b');
    c.onCanvasPointerUp(ptr(0, 0));
    expect(c.selection()).toEqual({ kind: 'state', key: 'b' });
  });

  it('shift-click toggles multi-selection of a node', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.onNodePointerDown(ptr(0, 0, { shiftKey: true }), 'a');
    expect([...c.multiSel()]).toEqual(['a']);
    c.onNodePointerDown(ptr(0, 0, { shiftKey: true }), 'a'); // toggle off
    expect([...c.multiSel()]).toEqual([]);
  });

  it('connects a new transition by dragging from a node onto another', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    // position b so nodeAt(...) hits it
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { positions: { a: { x: 0, y: 0 }, b: { x: 300, y: 0 } } },
    }));
    c.onConnectPointerDown(ptr(150, 26), 'a', 'pass', { roleIs: 'finance' });
    c.onCanvasPointerMove(ptr(320, 26)); // updates tempEdge
    expect(c.tempEdge()).not.toBeNull();
    c.onCanvasPointerUp(ptr(320, 26)); // drop on b
    const created = c.graph().transitions[c.graph().transitions.length - 1];
    expect(created).toMatchObject({ from: 'a', to: 'b', branch: 'pass', guard: { roleIs: 'finance' } });
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

  it('group pointer: drag moves members, click opens; shift toggles multi-select', async () => {
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

    // shift toggles the group into the multi-select
    c.onGroupPointerDown(ptr(0, 0, { shiftKey: true }), gid);
    expect([...c.multiSelGroups()]).toEqual([gid]);
    c.onGroupPointerDown(ptr(0, 0, { shiftKey: true }), gid);
    expect([...c.multiSelGroups()]).toEqual([]);

    // drag moves all member positions
    const beforeB = { ...c.graph().layout.positions.b };
    c.onGroupPointerDown(ptr(0, 0), gid);
    c.onCanvasPointerMove(ptr(50, 30));
    c.onCanvasPointerUp(ptr(50, 30));
    expect(c.graph().layout.positions.b.x).not.toBe(beforeB.x);

    // click without movement opens the group
    c.onGroupPointerDown(ptr(0, 0), gid);
    c.onCanvasPointerUp(ptr(0, 0));
    expect(c.currentGroupId()).toBe(gid);
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
    c.onCanvasPointerMove(ptr(40, 20)); // pan moves the view
    expect(c.view()).not.toBeNull();
    c.onCanvasPointerUp(ptr(40, 20));
  });

  it('toSvg falls back to client coords without a canvas/CTM', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    // force the no-canvas fallback path of toSvg (client coords used verbatim)
    c.canvas = () => undefined;
    c.onNodePointerDown(ptr(12, 34), 'a');
    c.onCanvasPointerMove(ptr(60, 50));
    // moved with fallback coords; position updated (rounded, clamped at 0)
    expect(c.graph().layout.positions.a).toBeDefined();
    c.onCanvasPointerUp(ptr(60, 50));
  });

  // --- zoom & view ----------------------------------------------------------
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
    c.onWheel({ deltaY: -10, clientX: 5, clientY: 5, preventDefault: () => {} } as unknown as WheelEvent);
    c.onWheel({ deltaY: 10, clientX: 5, clientY: 5, preventDefault: () => {} } as unknown as WheelEvent);
    // viewBox reflects the active view; reset → content bounds
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
    for (let i = 0; i < 30; i++) c.zoomIn(); // keep zooming → clamp at min width
    const minW = c.view()!.w;
    for (let i = 0; i < 60; i++) c.zoomOut(); // → clamp at max width
    expect(c.view()!.w).toBeGreaterThan(minW);
  });

  // --- moveGuardDown + branch dot geometry ----------------------------------
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
    // moving a non-existent / out-of-range group is a no-op
    c.moveGuardUp('v', 'no-such-sig');
    c.moveGuardDown('v', JSON.stringify({ roleIs: 'x' })); // x already last
    expect(c.guardGroupsFor('v').map((gp: { value: string }) => gp.value)).toEqual(['y', 'x']);
    // vote node draws pass+fail branch dots plus the two guard dots
    const node = c.nodes().find((n: { key: string }) => n.key === 'v');
    expect(node.dots.length).toBeGreaterThanOrEqual(4);
  });

  // --- save error path ------------------------------------------------------
  it('shows the server error detail when saving fails', async () => {
    const createGlobalFlowVersion = jest.fn(() => throwError(() => ({ error: { detail: 'nope' } })));
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
    c.saving.set(true); // pretend a save is running
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
    c.onKeydown(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true })); // undo
    fixture.detectChanges();
    expect(c.graph().states).toHaveLength(1);
    c.onKeydown(new KeyboardEvent('keydown', { key: 'Z', ctrlKey: true, shiftKey: true })); // redo
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

  it('relayout arranges the current level including a child group block', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [...(g.transitions ?? []), { from: 'a', to: 'c', actions: [] }],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    c.relayout();
    // every visible state still has a position
    expect(c.graph().layout.positions.a).toBeDefined();
    expect(c.graph().layout.positions.b).toBeDefined();
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
    c.addState(); // created inside the group
    const newKey = c.selection().key;
    expect(c.groups().find((g: { id: string }) => g.id === gid).stateKeys).toContain(newKey);
  });

  it('clearSelection is suppressed while a drag/connect is active', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.selection.set({ kind: 'state', key: 'a' });
    c.onNodePointerDown(ptr(0, 0), 'a'); // start a drag
    c.clearSelection(); // suppressed because drag is active
    expect(c.selection()).toEqual({ kind: 'state', key: 'a' });
    c.onCanvasPointerUp(ptr(0, 0));
  });

  it('deleteSelected removes the selected transition', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.selection.set({ kind: 'transition', index: 0 });
    c.deleteSelected();
    expect(c.graph().transitions).toHaveLength(0);
    // deleteSelected with no selection is a no-op
    c.selection.set(null);
    c.deleteSelected();
    expect(c.graph().states).toHaveLength(2);
  });

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
    // remove b → still a group with c
    c.selection.set({ kind: 'state', key: 'b' });
    c.removeSelectedState();
    expect(c.groups()[0].stateKeys).toEqual(['c']);
    // remove c → the now-empty group disappears
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

  it('dissolving a nested child group lifts its members into the parent', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    // inner group {b,c}
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const inner = c.groupBoxes()[0].id;
    // outer group {a, inner}
    c.multiSel.set(new Set(['a']));
    c.multiSelGroups.set(new Set([inner]));
    c.createGroupFromSelection();
    const outer = c.groupBoxes()[0].id;
    // drill into the inner group and dissolve it → b,c move up into outer
    c.openGroup(outer);
    c.openGroup(inner);
    c.dissolveCurrentGroup();
    // back at the outer level; the outer group now directly owns a, b, c
    expect(c.currentGroupId()).toBe(outer);
    const outerGroup = c.groups().find((g: { id: string }) => g.id === outer);
    expect(outerGroup.stateKeys.sort()).toEqual(['a', 'b', 'c']);
    expect(c.groups().some((g: { id: string }) => g.id === inner)).toBe(false);
  });

  it('renders edges/boxes/proxies geometry inside a drilled-down group', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // a (initial) → b → c → d ; group {b,c}; a→b enters, c→d leaves the group
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

    // Top level: the group box has 1 outgoing border edge (c→d) → edges through a group src.
    fixture.detectChanges();
    expect(c.edges().length).toBeGreaterThan(0);
    expect(c.groupBoxes()[0].outCount).toBe(1);
    expect(c.contentBounds().w).toBeGreaterThan(0);

    // Drill in: a (external src) is a left proxy, d (external dst) is a right proxy.
    c.openGroup(gid);
    fixture.detectChanges();
    expect(c.proxies().left.map((p: { pid: string }) => p.pid)).toContain('state:a');
    expect(c.proxies().right.map((p: { pid: string }) => p.pid)).toContain('state:d');
    // edges() inside the group draws from a left proxy into b and from c to a right proxy.
    const eds = c.edges();
    expect(eds.length).toBeGreaterThanOrEqual(2);
    // contentBounds includes the proxy columns (can extend left of x=0).
    expect(c.contentBounds()).toBeDefined();
  });

  it('guardGroupLabel returns the raw value for an unresolved text/budget op', async () => {
    const { fixture } = await setup({ tree: jest.fn(() => of(BUDGET_TREE)) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // text op (hasField) with a value → "op: value" (resolveGuardValue returns value)
    expect(c.guardGroupLabel({ sig: 's', guard: { hasField: 'iban' }, op: 'hasField', value: 'iban', indices: [] }))
      .toContain('iban');
    // budgetIs with an id absent from the tree → value passed through unchanged
    expect(c.guardGroupLabel({ sig: 's', guard: { budgetIs: 'unknown' }, op: 'budgetIs', value: 'unknown', indices: [] }))
      .toContain('unknown');
  });

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
    // edges() runs outDotYFor with t.branch set, computing branch-specific y offsets
    const eds = c.edges();
    expect(eds).toHaveLength(2);
    expect(eds[0].y1).not.toBe(eds[1].y1);
  });

  it('creating a group while drilled into a group nests it (sub-group)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.addState();
    c.setStateKey('state', 'c');
    c.setStateKey('state2', 'd');
    // outer group {b,c,d}
    c.multiSel.set(new Set(['b', 'c', 'd']));
    c.createGroupFromSelection();
    const outer = c.groupBoxes()[0].id;
    // drill in, then group {c,d} → becomes a sub-group of outer (ctx path)
    c.openGroup(outer);
    c.multiSel.set(new Set(['c', 'd']));
    c.createGroupFromSelection();
    const outerGroup = c.groups().find((g: { id: string }) => g.id === outer);
    expect(outerGroup.groupIds?.length).toBe(1);
    const sub = outerGroup.groupIds[0];
    expect(c.groups().find((g: { id: string }) => g.id === sub).stateKeys.sort()).toEqual(['c', 'd']);

    // Add two more states inside outer, then group them while an existing group
    // (outer) already carries a non-empty groupIds list → exercises the
    // `gr.groupIds.filter(...)` branch during re-grouping.
    c.addState();
    c.addState();
    const ks = c.graph().states.map((s: { key: string }) => s.key);
    const e = ks[ks.length - 2];
    const f = ks[ks.length - 1];
    c.multiSel.set(new Set([e, f]));
    c.createGroupFromSelection();
    // outer keeps its sub-group; a new sibling sub-group now also exists
    const refreshed = c.groups().find((g: { id: string }) => g.id === outer);
    expect(refreshed.groupIds.length).toBeGreaterThanOrEqual(2);
  });

  it('picks a fresh group id when grpN is already taken (collision loop)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.addState();
    c.setStateKey('state', 'c');
    c.setStateKey('state2', 'd');
    // Seed a pre-existing group whose id collides with the next candidate (grp2):
    // existing.length === 1 → candidate "grp2" is taken → loop bumps to "grp3".
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { ...(g.layout ?? {}), groups: [{ id: 'grp2', name: 'X', stateKeys: ['c'] }] },
    }));
    c.multiSel.set(new Set(['a', 'b']));
    c.createGroupFromSelection();
    const ids = c.groups().map((g: { id: string }) => g.id).sort();
    expect(ids).toContain('grp2');
    expect(ids).toContain('grp3'); // collision bumped the new id past grp2
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('positions proxies relative to both nodes and group boxes on a level', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // states: x (initial, external) → a ; inner group {b,c}; outer group {a, inner}
    c.addState(); // x
    c.addState(); // a
    c.addState(); // b
    c.addState(); // c
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
    // inner = {b,c}
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const inner = c.groupBoxes()[0].id;
    // outer = {a, inner}
    c.multiSel.set(new Set(['a']));
    c.multiSelGroups.set(new Set([inner]));
    c.createGroupFromSelection();
    const outer = c.groupBoxes()[0].id;
    // Drill into outer: a is a node, inner is a group box, x is an external left proxy.
    c.openGroup(outer);
    fixture.detectChanges();
    expect(c.nodes().map((n: { key: string }) => n.key)).toEqual(['a']);
    expect(c.groupBoxes().map((b: { id: string }) => b.id)).toEqual([inner]);
    expect(c.proxies().left.map((p: { pid: string }) => p.pid)).toContain('state:x');
    // contentBounds + edges run with proxies AND a group box present
    expect(c.contentBounds().w).toBeGreaterThan(0);
    expect(c.edges().length).toBeGreaterThan(0);
  });

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
    // group1 = {a,b}, group2 = {c,d}
    c.multiSel.set(new Set(['a', 'b']));
    c.createGroupFromSelection();
    const g1 = c.groupBoxes()[0].id;
    c.multiSel.set(new Set(['c', 'd']));
    c.createGroupFromSelection();
    fixture.detectChanges();
    // two group boxes, one edge between them (group→group)
    expect(c.groupBoxes()).toHaveLength(2);
    expect(c.edges()).toHaveLength(1);
    // drill into g1: c resolves to its group → right proxy is the sibling group
    c.openGroup(g1);
    fixture.detectChanges();
    const rightPids = c.proxies().right.map((p: { pid: string }) => p.pid);
    expect(rightPids.some((p: string) => p.startsWith('group:'))).toBe(true);
  });
});
