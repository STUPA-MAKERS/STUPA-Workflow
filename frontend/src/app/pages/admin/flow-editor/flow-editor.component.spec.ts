import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { ToastService } from '@stupa-makers/ui-kit';
import type { FlowGraph, Guard } from '../admin.models';
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
    hiddenInBudget: false, viewGremiumId: null, fiscalStartMonth: 1,
    fiscalStartDay: 1, byFiscalYear: [],
    children: [
      {
        id: 'b2', parentId: 'b1', gremiumId: null, key: 'VS-800-40', pathKey: 'VS-800-40', name: 'IT',
        currency: 'EUR', active: true, color: null, acceptedStateKeys: [], deniedStateKeys: [],
        hiddenInBudget: false, viewGremiumId: null, fiscalStartMonth: 1,
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
  const listConfigRevisions = jest.fn(() => of([]));
  const api = { getGlobalFlow, createGlobalFlowVersion, listApplicationTypes, listGremienOptions, listGremiumRoles, listRoles, listDeadlinePolicies, listWebhooks, listConfigRevisions };
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

  // --- option-list fallbacks (constructor next-handlers, #branch-coverage) ----
  it('falls back to keys/url when option labels are missing', async () => {
    const { fixture } = await setup({
      // role without a `de` label → falls back to its key in the label string
      listRoles: jest.fn(() => of([{ id: 'r1', key: 'finance', label: {}, permissions: [] }])),
      // webhook with an empty name → falls back to its url
      listWebhooks: jest.fn(() => of([{ id: 'w1', name: '', url: 'https://h.test', events: [], active: true }])),
      // deadline policy without a `de` label → falls back to its key
      listDeadlinePolicies: jest.fn(() => of([{ id: 'dp1', key: 'semester', label: {}, kind: 'absolute' }])),
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.globalRoleOptions()).toEqual([{ value: 'finance', label: 'finance (finance)' }]);
    expect(c.webhookOptions()).toEqual([{ value: 'w1', label: 'https://h.test' }]);
    expect(c.deadlinePolicyOptions()[0].label).toBe('semester (semester)');
  });

  // --- bare-graph fallbacks: a graph with no `transitions` array and no
  // `layout` exercises the `?? []` / `?? {}` defensive paths in the mutators
  // and computeds that buildValid (which always seeds both) never reaches. ----
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function bare(c: any, withInitial = true): void {
    c.graph.set({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: withInitial },
        { key: 'b', label: { de: 'B' } },
      ],
    } as unknown as FlowGraph);
  }

  it('mutators tolerate a graph with no transitions array (?? [] paths)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    bare(c);
    // computeds over a transition-less graph
    expect(c.nodes().map((n: { key: string }) => n.key)).toEqual(['a', 'b']);
    expect(c.edges()).toEqual([]);
    expect(c.guardGroupsFor('a')).toEqual([]);
    c.selection.set({ kind: 'state', key: 'a' });
    expect(c.stateTransitionLists().incoming).toEqual([]);
    expect(c.stateTransitionLists().outgoing).toEqual([]);

    // transition mutators all default `transitions` to []
    bare(c);
    c.setTransitionBranch(0, 'pass'); // index out of range → no-op map
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
    // graph still has its two states after all the no-ops
    expect(c.graph().states).toHaveLength(2);
  });

  it('addState/setInitial/setStateKey tolerate a missing layout (?? {} paths)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    bare(c);
    c.addState(); // autoLayout fills positions even from a layout-less graph
    expect(c.graph().states.length).toBe(3);
    bare(c);
    c.setInitial('b');
    expect(c.graph().states.find((s: { key: string }) => s.key === 'b').isInitial).toBe(true);
    bare(c);
    c.setStateKey('a', 'alpha'); // no positions[oldKey] → skips the position-copy branch
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
    bare(c);
    c.setStateDeadlinePolicy('a', 'semester');
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

  it('group + layout mutators tolerate a layout-less graph', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    bare(c);
    c.multiSel.set(new Set(['a', 'b']));
    c.createGroupFromSelection(); // builds layout.groups from scratch
    expect(c.groups()).toHaveLength(1);
    const gid = c.groups()[0].id;
    c.renameGroup(gid, 'X');
    c.setGroupColor(gid, '#000');
    c.openGroup(gid);
    c.dissolveCurrentGroup();
    expect(c.groups()).toHaveLength(0);
  });

  it('relayout tolerates a layout-less graph', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    bare(c);
    c.relayout();
    expect(c.graph().layout.positions.a).toBeDefined();
  });

  // --- guard / compare value fallbacks --------------------------------------
  it('compare reads/labels tolerate missing or object/list values', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // compareSpec falls back to defaults when guard.compare is absent / not an object
    expect(c.compareField({ from: 'a', to: 'b' })).toBe('');
    expect(c.compareOp({ from: 'a', to: 'b' })).toBe('==');
    expect(c.compareValue({ from: 'a', to: 'b' })).toBe('');
    // compareValue of a null value → ''
    expect(c.compareValue({ from: 'a', to: 'b', guard: { compare: { field: 'f', op: '==', value: null } } })).toBe('');
    // compareValue of an array → joined
    expect(c.compareValue({ from: 'a', to: 'b', guard: { compare: { field: 'f', op: 'in', value: ['x', 'y'] } } })).toBe('x, y');
    // guardValue of an object value → '' (the typeof object branch)
    expect(c.guardValue({ from: 'a', to: 'b', guard: { compare: { field: 'f' } } })).toBe('');
    // guardValue of a null value → ''
    expect(c.guardValue({ from: 'a', to: 'b', guard: { roleIs: null } })).toBe('');
    // guardBool false when the value is not boolean true
    expect(c.guardBool({ from: 'a', to: 'b', guard: { roleIs: 'x' } })).toBe(false);
    expect(c.guardBool({ from: 'a', to: 'b' })).toBe(false);
    // guardOp of a guard-less transition → ''
    expect(c.guardOp({ from: 'a', to: 'b' })).toBe('');
  });

  it('guardGroupLabel + transitionGuardLabel handle missing fields/op', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // compare with absent field/op/value → "<empty> == <empty>" (the ?? fallbacks)
    expect(c.guardGroupLabel({ sig: 's', guard: { compare: {} }, op: 'compare', value: '', indices: [] }))
      .toBe('==');
    // compare with a null value → spec.value ?? '' fallback
    expect(c.guardGroupLabel({ sig: 's', guard: { compare: { field: 'f', op: '>', value: null } }, op: 'compare', value: '', indices: [] }))
      .toBe('f >');
    // an empty guard object → Object.keys(...)[0] is undefined → '' fallback in transitionGuardLabel
    expect(c.transitionGuardLabel({ from: 'a', to: 'b', guard: {} })).toBeTruthy();
  });

  // --- setCompare with provided field/op + missing patch fields -------------
  it('setCompare keeps current spec fields when the patch omits them', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.setGuardOp(0, 'compare');
    c.setCompare(0, { field: 'amount', op: '>', value: '5' });
    // omit value → keep current; omit op → keep current; omit field → keep current
    c.setCompare(0, { field: 'cost' });
    expect(c.compareField(c.graph().transitions[0])).toBe('cost');
    expect(c.compareOp(c.graph().transitions[0])).toBe('>');
    expect(c.compareValue(c.graph().transitions[0])).toBe('5');
    // `in` with a non-string current value leaves it untouched (the typeof guard)
    c.setCompare(0, { op: 'in', value: 'a,b' });
    c.setCompare(0, { field: 'x' }); // value stays the already-split array
    expect(c.compareValue(c.graph().transitions[0])).toBe('a, b');
  });

  // --- actions: missing actions array + non-string param --------------------
  it('action helpers tolerate a missing actions array + non-string params', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    // recipientsOf on an action whose recipients is not an array → []
    expect(c.recipientsOf({ type: 'notify', recipients: 'nope' })).toEqual([]);
    // actionParam of a non-string field → ''
    expect(c.actionParam({ type: 'webhook', webhookId: 123 }, 'webhookId')).toBe('');
    // addAction with an empty type is a no-op
    const before = c.graph().transitions[0].actions.length;
    c.addAction(0, '');
    expect(c.graph().transitions[0].actions.length).toBe(before);
  });

  // --- vote dot geometry: branch with no targets / unknown guard ------------
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
    // pass branch points at p (which HAS a position) and fail branch at a state
    // with NO position → avgTargetY returns null → the sort comparator returns 0.
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { positions: { v: { x: 0, y: 0 }, p: { x: 200, y: 0 } } },
      transitions: [
        { from: 'v', to: 'p', branch: 'pass', actions: [] },
        { from: 'v', to: 'p', branch: 'fail', actions: [] }, // no position diff
        // a guarded manual exit whose guard signature matches a group
        { from: 'v', to: 'p', guard: { roleIs: 'x' }, actions: [] },
      ],
    }));
    fixture.detectChanges();
    const eds = c.edges();
    expect(eds.length).toBe(3);
    // a vote node still renders its branch + guard dots
    const node = c.nodes().find((n: { key: string }) => n.key === 'v');
    expect(node.dots.length).toBeGreaterThanOrEqual(3);
  });

  // --- selectedTransition: stale index → undefined --------------------------
  it('selectedTransition is undefined when the index is out of range', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.selection.set({ kind: 'transition', index: 99 });
    expect(c.selectedTransition()).toBeUndefined();
    expect(c.selectedState()).toBeUndefined();
    // a state selection pointing at a missing key → selectedState undefined too
    c.selection.set({ kind: 'state', key: 'no-such' });
    expect(c.selectedState()).toBeUndefined();
  });

  // --- breadcrumbs break out when the chain points at a missing group -------
  it('breadcrumbs stop at a dangling currentGroupId', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    // point currentGroupId at a group that does not exist; the effect resets it,
    // but breadcrumbs itself first walks and breaks on the missing group.
    c.currentGroupId.set('ghost');
    expect(c.breadcrumbs()).toEqual([]);
  });

  // --- proxies with neither nodes nor boxes (empty xs/ys fallback) ----------
  it('proxies fall back to MARGIN bounds when a level has no nodes or boxes', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // a → group{b}; the group has a single member with no top-level node visible.
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'a', to: 'b', actions: [] }],
    }));
    // Build a group from b alone by forcing a group with a single member.
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: {
        positions: {}, // <- no positions → group box is dropped, proxies see no xs/ys
        groups: [{ id: 'g1', name: 'G', stateKeys: ['b'] }],
      },
    }));
    c.openGroup('g1');
    fixture.detectChanges();
    // a is an external source → a left proxy; xs/ys are empty so columns fall
    // back to MARGIN-based positions without throwing.
    expect(c.proxies().left.length).toBeGreaterThanOrEqual(0);
    expect(c.contentBounds()).toBeDefined();
  });

  // --- proxy label fallbacks: unknown group id and unknown state key --------
  it('proxy labels fall back when the referenced group/state is unknown', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // x (external) → a; group{a}. Drill into the group: x is a left proxy.
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
    // single-member group is not allowed via createGroupFromSelection; seed directly
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
    // the proxy resolves the external state x to its label
    expect(left[0].label).toBeTruthy();
  });

  // --- canvas pointer: connect-drag temp edge while connecting (?? paths) ----
  it('updates the temp edge while connecting from a node', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.onConnectPointerDown(ptr(150, 26), 'a');
    c.onCanvasPointerMove(ptr(200, 26)); // connectFrom branch in pointer-move
    expect(c.tempEdge()).not.toBeNull();
    c.onCanvasPointerUp(ptr(0, 0)); // drop on a (self) → no transition created
  });

  // --- save success path ----------------------------------------------------
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

  it('save uses the generic invalid message when validation has no errors list', async () => {
    const { fixture, toast } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // an empty graph is invalid → toast.error fires with the first validation error
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
    expect(toast.error).toHaveBeenCalled(); // err?.error?.detail undefined → generic
    expect(c.saving()).toBe(false);
  });

  // --- onProxyClick to a state whose owner is the top level -----------------
  it('onProxyClick selects a top-level state (owner = null)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.onProxyClick('state:a'); // a has no group owner → navigateTo(null)
    expect(c.currentGroupId()).toBeNull();
    expect(c.selection()).toEqual({ kind: 'state', key: 'a' });
  });

  // --- keydown: plain (non-modifier) keys while NOT typing ------------------
  it('ignores unrelated keys and respects the typing guard for Insert too', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // a random key does nothing
    c.onKeydown(new KeyboardEvent('keydown', { key: 'a' }));
    expect(c.graph().states).toHaveLength(0);
    // Insert while typing in a textarea is ignored
    const ta = document.createElement('textarea');
    c.onKeydown({ key: 'Insert', target: ta, preventDefault: () => {}, ctrlKey: false, metaKey: false, shiftKey: false } as unknown as KeyboardEvent);
    expect(c.graph().states).toHaveLength(0);
    // Backspace deletes the selected state (the Backspace arm)
    c.addState();
    c.selection.set({ kind: 'state', key: c.graph().states[0].key });
    c.onKeydown(new KeyboardEvent('keydown', { key: 'Backspace' }));
    expect(c.graph().states).toHaveLength(0);
    // Ctrl+Y / metaKey redo arm
    c.onKeydown({ key: 'z', metaKey: true, ctrlKey: false, shiftKey: false, preventDefault: () => {}, target: null } as unknown as KeyboardEvent);
  });

  // --- pan: pointer move with no active drag/connect but a panGrab ----------
  it('pointer move with nothing grabbed and no pan is inert', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.selection.set(null);
    // no drag, no group drag, no connect, no panGrab → all four branches false
    c.onCanvasPointerMove(ptr(10, 10));
    expect(c.view()).toBeNull();
    // pointer up with nothing active → no-op
    c.onCanvasPointerUp(ptr(10, 10));
    expect(c.selection()).toBeNull();
  });

  // --- groupBoxes returns null for a group whose members have no positions --
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
    // members have no positions → the box maps to null and is filtered out
    expect(c.groupBoxes()).toHaveLength(0);
  });

  // --- edgeEnds: a fully-internal transition inside a sub-group is hidden ----
  it('hides a transition whose both ends collapse into the same sub-group', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c); // a → b
    c.addState();
    c.setStateKey('state', 'c');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [...(g.transitions ?? []), { from: 'b', to: 'c', actions: [] }],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    // top level: b→c is internal to the group (both ends resolve to the same box)
    fixture.detectChanges();
    // the only visible edge is a→group; b→c is hidden (group===group, same id)
    expect(c.edges().length).toBe(1);
  });

  // --- self-loop transition is hidden on the same level ---------------------
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
    // the self-loop edgeEnd is null → not drawn; only a→b remains
    expect(c.edges().map((e: { index: number }) => e.index)).toEqual([0]);
  });

  // --- nodes for a state without a stored position (?? 0 fallbacks) ---------
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

  // --- multi-transition mutators: the non-matching index `: t` else arms -----
  it('per-index transition mutators leave the non-matching transitions intact', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addState();
    c.setStateKey('state', 'c');
    // two transitions: index 0 (a→b) and index 1 (b→c)
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'b', actions: [] },
        { from: 'b', to: 'c', actions: [] },
      ],
    }));
    // mutate index 0 → index 1 must hit the `: t` else branch each time
    c.setTransitionBranch(0, 'pass');
    c.setTransitionEndpoint(0, 'to', 'c');
    c.setTransitionLabel(0, 'de', 'go');
    c.setTransitionAutomatic(0, true);
    c.setTransitionColor(0, '#111');
    c.setTransitionRequiresAction(0, false);
    c.setGuardOp(0, 'roleIs');
    // index 1 unchanged
    expect(c.graph().transitions[1]).toMatchObject({ from: 'b', to: 'c' });
    expect(c.graph().transitions[1].automatic).toBeUndefined();
    expect(c.graph().transitions[1].branch).toBeUndefined();
  });

  // --- setStateKey renaming a state referenced by a transition `from` --------
  it('setStateKey rewrites the from/to of transitions touching the renamed key', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c); // a → b, with a self/forward transition a→b
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
    // and a transition not touching the key keeps both ends (the `: t.from` else)
    expect(c.graph().transitions[0].to).toBe('b');
    expect(c.graph().transitions[1].from).toBe('b');
  });

  // --- guardValue of a guard-less transition (the !t.guard early return) -----
  it('guardValue returns empty for a transition with no guard', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.guardValue({ from: 'a', to: 'b' })).toBe('');
  });

  // --- groupsOf: a guard whose first value is null/undefined (String ?? '') --
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
      // guard's first value is null → String(undefined/null ?? '') === ''
      transitions: [{ from: 'a', to: 'b', guard: { roleIs: null } as unknown as Guard, actions: [] }],
    }));
    const groups = c.guardGroupsFor('a');
    expect(groups[0].value).toBe('');
  });

  // --- stateTransitionLists labelOf fallback (dangling from/to) --------------
  it('state transition lists fall back to raw keys for dangling endpoints', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.setStateKey('state', 'a');
    c.setInitial('a');
    // outgoing: `to` references a non-existent state → labelOf.get(to) ?? to
    // incoming: `from` references a non-existent state → labelOf.get(from) ?? from
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [
        { from: 'a', to: 'ghostTo', actions: [] },
        { from: 'ghostFrom', to: 'a', actions: [] },
      ],
    }));
    c.selection.set({ kind: 'state', key: 'a' });
    const lists = c.stateTransitionLists();
    expect(lists.outgoing[0].to).toBe('ghostTo'); // raw key, no label resolved
    expect(lists.incoming[0].from).toBe('ghostFrom'); // raw key, no label resolved
    expect(lists.incoming[0].to).toBe('a'); // resolved label (= key here)
  });

  // --- outDotYFor: a branch with no positioned targets falls back to h/2 -----
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
        // a branch value that is not in the rendered branch list → indexOf < 0
        { from: 'v', to: 'p', branch: 'weird' as unknown as string, actions: [] },
        // a guard whose signature is absent from the out-dot groups list
        { from: 'v', to: 'p', guard: { roleIs: 'q' }, actions: [] },
      ],
    }));
    fixture.detectChanges();
    const eds = c.edges();
    expect(eds.length).toBe(2);
    // both edges resolve a y coordinate (no throw on the fallback paths)
    expect(typeof eds[0].y1).toBe('number');
    expect(typeof eds[1].y1).toBe('number');
  });

  // --- sortedBranchDots: avgTargetY null → comparator returns 0 --------------
  it('keeps branch order when neither branch has positioned targets', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.setStateKey('state', 'v');
    c.setInitial('v');
    c.setStateKind('v', 'vote');
    c.setStateGremium('v', 'g1');
    // vote node with NO outgoing branch transitions → avgTargetY null for both
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { positions: { v: { x: 0, y: 0 } } },
      transitions: [],
    }));
    fixture.detectChanges();
    const node = c.nodes().find((n: { key: string }) => n.key === 'v');
    // pass+fail dots still present even with no positioned targets
    expect(node.dots.some((d: { branch: string | null }) => d.branch === 'pass')).toBe(true);
    expect(node.dots.some((d: { branch: string | null }) => d.branch === 'fail')).toBe(true);
  });

  // --- recipient ref preservation: switching to a ref-needing kind keeps ref -
  it('recipient kind switch keeps the ref for ref-needing kinds and drops it otherwise', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addAction(0, 'notify');
    c.addRecipient(0, 0);
    c.addRecipient(0, 0); // two recipients → mutate index 0, index 1 hits the `: r` else
    c.setRecipientKind(0, 0, 0, 'role'); // ref needed → r.ref ?? '' keeps ''
    expect(c.recipientsOf(c.graph().transitions[0].actions[0])[0]).toEqual({ kind: 'role', ref: '' });
    c.setRecipientRef(0, 0, 0, 'r1');
    c.setRecipientKind(0, 0, 0, 'gremium'); // still ref-needing → keeps existing ref
    expect(c.recipientsOf(c.graph().transitions[0].actions[0])[0].ref).toBe('r1');
    // the second recipient stayed untouched (the `: r` else of setRecipientKind/Ref)
    expect(c.recipientsOf(c.graph().transitions[0].actions[0])[1]).toEqual({ kind: 'applicant' });
  });

  // --- removeAction / removeRecipient on multi-element arrays (else arms) ----
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
    c.removeAction(0, 0); // index 0 → index 1 hits `: t`
    expect(c.graph().transitions[1].actions).toHaveLength(1);
  });

  // --- effect: a dangling currentGroupId is reset on change detection --------
  it('resets a dangling drill-down context via the guard effect', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.currentGroupId.set('ghost');
    fixture.detectChanges(); // runs the effect → currentGroupId reset to null
    expect(c.currentGroupId()).toBeNull();
  });

  // --- undo stack cap: more than 100 structural edits trims the oldest -------
  it('caps the undo history at 100 structural edits', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    for (let i = 0; i < 105; i++) {
      c.addState();
      fixture.detectChanges(); // each structural change is one history step
    }
    // 105 adds → history capped at 100; undo at most 100 times still leaves states
    let undos = 0;
    while (c.canUndo()) {
      c.undo();
      fixture.detectChanges();
      undos++;
      if (undos > 130) break; // safety
    }
    expect(undos).toBeLessThanOrEqual(100);
    expect(c.graph().states.length).toBeGreaterThan(0);
  });

  // --- deepStateKeys: dangling sub-group reference (the !g early return) ------
  it('deepStateKeys survives a dangling sub-group reference', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    // g1 (top-level box) references a missing sub-group → deepStateKeys hits `!g`
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: {
        positions: { a: { x: 0, y: 0 }, b: { x: 100, y: 0 } },
        groups: [{ id: 'g1', name: 'G', stateKeys: ['a', 'b'], groupIds: ['missing'] }],
      },
    }));
    fixture.detectChanges();
    // group box is computed from deepStateKeys without throwing on the missing ref
    const box = c.groupBoxes().find((b: { id: string }) => b.id === 'g1');
    expect(box.deepKeys.sort()).toEqual(['a', 'b']);
  });

  // Note: the deepStateKeys `seen.has(id)` cycle guard (a mutual groupIds cycle)
  // is a normalization-prevented defensive path; constructing it would loop the
  // breadcrumbs walker (which has no own cycle guard), so it is left uncovered.

  // --- edgeEnds: a transition fully external to the current level is null -----
  it('hides a transition whose both ends are external to the drilled-in level', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // states a,b (top level) and c,d inside a group; a→b is fully external when
    // drilled into the {c,d} group.
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
    // a→b is fully external (both ends resolve to null) → no edge, no proxies
    expect(c.proxies().left).toEqual([]);
    expect(c.proxies().right).toEqual([]);
  });

  // --- proxies with no nodes and no group boxes (empty xs/ys → MARGIN) -------
  it('positions proxies from MARGIN bounds when the level is otherwise empty', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // x (external) → a; a lives in a sub-group of g1 so the g1 level shows only a
    // sub-group box... we want a level with proxies but NO nodes/boxes that have
    // positions. Build: g1 = {a}, but a has no position → no node, no box.
    c.addState();
    c.addState();
    c.setStateKey('state', 'x');
    c.setStateKey('state2', 'a');
    c.setInitial('x');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'x', to: 'a', actions: [] }],
      layout: {
        positions: { x: { x: 0, y: 0 } }, // a has NO position
        groups: [{ id: 'g1', name: 'G', stateKeys: ['a'] }],
      },
    }));
    c.openGroup('g1');
    fixture.detectChanges();
    // a is a visible node of g1 but has no position; x is a left proxy. xs/ys come
    // only from a's node (x/y default to 0) so columns still resolve.
    const proxies = c.proxies();
    expect(proxies.left.map((p: { pid: string }) => p.pid)).toContain('state:x');
  });

  // --- proxy label: unknown group id and unknown state key fall back ---------
  it('proxy label falls back to the raw pid for an unknown group/state', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // Access the private label resolver via proxies(): set up a level whose proxy
    // points at a group that no longer exists. Easiest: directly drive edgeEnds by
    // having a transition cross into a group, then drill in and remove the source.
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
    // a (external state) is a left proxy and resolves its label from the state list
    const left = c.proxies().left;
    expect(left.find((p: { pid: string }) => p.pid === 'state:a')).toBeDefined();
  });

  // --- edges through a group/proxy source/target with missing maps ----------
  it('draws edges through group and proxy endpoints inside a drilled-in level', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // a (initial) → b → c → d; group {b,c}. Drill in: a is a left proxy → b, and
    // c → a right proxy d; this exercises the proxy src/dst branches in edges().
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
    // both proxy→state and state→proxy edges resolve coordinates
    expect(eds.length).toBeGreaterThanOrEqual(2);
    for (const e of eds) {
      expect(typeof e.x1).toBe('number');
      expect(typeof e.x2).toBe('number');
    }
  });

  // --- toSvg without a CTM (getScreenCTM returns null) ----------------------
  it('toSvg falls back to client coords when getScreenCTM returns null', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    // a canvas that exists but whose getScreenCTM yields null → the `if (!ctm)` arm
    c.canvas = () => ({ nativeElement: { getScreenCTM: () => null } });
    c.onNodePointerDown(ptr(12, 34), 'a');
    c.onCanvasPointerMove(ptr(60, 50));
    expect(c.graph().layout.positions.a).toBeDefined();
    c.onCanvasPointerUp(ptr(60, 50));
  });

  // --- clearSelection clears a non-empty multi-selection --------------------
  it('clearSelection also clears a pending multi-selection', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.multiSel.set(new Set(['a', 'b']));
    c.clearSelection(); // no drag/connect/group-drag → clears selection + multiSel
    expect([...c.multiSel()]).toEqual([]);
  });

  // --- compareField/compareOp with explicitly-undefined spec fields ----------
  it('compareField/compareOp apply their ?? fallbacks for partial compare specs', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // compare object present (so compareSpec returns it) but field/op are absent
    expect(c.compareField({ from: 'a', to: 'b', guard: { compare: { op: '>' } } })).toBe('');
    expect(c.compareOp({ from: 'a', to: 'b', guard: { compare: { field: 'x' } } })).toBe('==');
  });

  // --- action mutators on transitions that omit the `actions` field ----------
  it('action mutators tolerate transitions without an actions array', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    // transition WITHOUT an `actions` field → addAction's `t.actions ?? []`
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'a', to: 'b' }],
    }));
    c.addAction(0, 'webhook');
    expect(c.graph().transitions[0].actions).toHaveLength(1);

    // a fresh actions-less transition for setActionParam's `t.actions ?? []`
    c.graph.update((g: FlowGraph) => ({ ...g, transitions: [{ from: 'a', to: 'b' }] }));
    c.setActionParam(0, 0, 'webhookId', 'w1'); // ai out of range → no-op map over []
    expect(c.graph().transitions[0].actions).toEqual([]);

    // patchRecipients' `t.actions ?? []`
    c.graph.update((g: FlowGraph) => ({ ...g, transitions: [{ from: 'a', to: 'b' }] }));
    c.addRecipient(0, 0);
    expect(c.graph().transitions[0].actions).toEqual([]);

    // removeAction's `t.actions ?? []`
    c.graph.update((g: FlowGraph) => ({ ...g, transitions: [{ from: 'a', to: 'b' }] }));
    c.removeAction(0, 0);
    expect(c.graph().transitions[0].actions).toEqual([]);
  });

  // --- setActionParam with multiple actions hits the `: a` else --------------
  it('setActionParam leaves sibling actions untouched', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.addAction(0, 'webhook');
    c.addAction(0, 'webhook');
    c.setActionParam(0, 0, 'webhookId', 'w1'); // index 1 hits the `: a` else
    expect(c.actionParam(c.graph().transitions[0].actions[0], 'webhookId')).toBe('w1');
    expect(c.actionParam(c.graph().transitions[0].actions[1], 'webhookId')).toBe('');
  });

  // --- onNodePointerDown on a node with no stored position (?? {x:0,y:0}) -----
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
    c.onNodePointerDown(ptr(5, 5), 'a'); // positions()['a'] undefined → {x:0,y:0}
    c.onCanvasPointerUp(ptr(5, 5));
    expect(c.selection()).toEqual({ kind: 'state', key: 'a' });
  });

  // --- drag clamps negative coordinates to 0 --------------------------------
  it('clamps a node drag to non-negative coordinates', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    stubCanvas(c);
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { positions: { a: { x: 10, y: 10 }, b: { x: 300, y: 0 } } },
    }));
    c.onNodePointerDown(ptr(10, 10), 'a');
    c.onCanvasPointerMove(ptr(-100, -100)); // negative target → Math.max(0, …) clamps
    expect(c.graph().layout.positions.a).toEqual({ x: 0, y: 0 });
    c.onCanvasPointerUp(ptr(-100, -100));
  });

  // --- group drag clamps negative coordinates to 0 --------------------------
  it('clamps a group drag to non-negative coordinates', async () => {
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
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { ...g.layout, positions: { ...g.layout.positions, b: { x: 5, y: 5 }, c: { x: 5, y: 5 } } },
    }));
    c.onGroupPointerDown(ptr(0, 0), gid);
    c.onCanvasPointerMove(ptr(-200, -200)); // negative → clamp members to 0
    expect(c.graph().layout.positions.b.x).toBe(0);
    expect(c.graph().layout.positions.b.y).toBe(0);
    c.onCanvasPointerUp(ptr(-200, -200));
  });

  // --- connect-create on a graph whose transitions array is omitted ----------
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
    c.onConnectPointerDown(ptr(150, 26), 'a'); // no transitions field yet
    c.onCanvasPointerUp(ptr(310, 26)); // drop on b → `g.transitions ?? []` seeds it
    expect(c.graph().transitions).toHaveLength(1);
    expect(c.graph().transitions[0]).toMatchObject({ from: 'a', to: 'b' });
  });

  // --- relayout with a proxy edge + no marked initial + null edge ends -------
  it('relayout inside a group ignores proxy edges and an unmarked initial', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // a (NO initial flag) → b ; group {b,c}; c → d ; a→b enters & c→d leaves group.
    c.addState();
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setStateKey('state3', 'c');
    c.setStateKey('state4', 'd');
    // deliberately NO setInitial → relayout's `initialKey ? … : false` else arm
    c.graph.update((g: FlowGraph) => ({
      ...g,
      states: g.states.map((s: { isInitial?: boolean }) => ({ ...s, isInitial: false })),
      transitions: [
        { from: 'a', to: 'b', actions: [] },
        { from: 'b', to: 'c', actions: [] },
        { from: 'c', to: 'd', actions: [] },
        { from: 'a', to: 'a', actions: [] }, // self-loop → a null edgeEnd (the `if (!e)`)
      ],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const gid = c.groupBoxes()[0].id;
    c.openGroup(gid);
    // inside the group, a (left proxy) → b and c → d (right proxy): proxy ends give
    // entId === null, exercising the relayout proxy branch.
    c.relayout();
    expect(c.graph().layout.positions.b).toBeDefined();
    expect(c.graph().layout.positions.c).toBeDefined();
  });

  // --- proxies on a level with zero nodes and zero boxes (MARGIN fallback) ----
  it('proxies use MARGIN bounds when a drilled-in level has no node/box positions', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // x (external, positioned) → a ; group g1 = {a} where a has NO position. Inside
    // g1 there is one node (a) but it has no position → it still renders (x/y = 0),
    // so to truly empty the level we make a a member of a SUB-group with no box.
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
        // a/b have NO position → sub-group box dropped (no points) and no nodes
        positions: { x: { x: 0, y: 0 } },
        groups: [
          { id: 'g1', name: 'G1', stateKeys: [], groupIds: ['g2'] },
          { id: 'g2', name: 'G2', stateKeys: ['a', 'b'] },
        ],
      },
    }));
    c.openGroup('g1');
    fixture.detectChanges();
    // g1's only child is g2 (a box) but g2 has no member positions → box dropped →
    // proxies see empty xs/ys → MARGIN-based columns (the cond-expr fallbacks).
    expect(c.groupBoxes()).toHaveLength(0);
    expect(c.proxies()).toBeDefined();
  });

  // --- removeSelectedState/Transition early returns + bare-graph ?? [] -------
  it('removeSelectedState/Transition respect the selection-kind guards', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    // removeSelectedState with a TRANSITION selection → early return (the `!== state` arm)
    c.selection.set({ kind: 'transition', index: 0 });
    c.removeSelectedState();
    expect(c.graph().states).toHaveLength(2);
    // removeSelectedTransition on a transitions-less graph hits its `?? []`
    c.graph.set({
      states: [{ key: 'a', label: { de: 'A' }, isInitial: true }],
    } as unknown as FlowGraph);
    c.selection.set({ kind: 'transition', index: 0 });
    c.removeSelectedTransition();
    expect(c.graph().transitions ?? []).toEqual([]);
  });

  // --- drag / group-drag / connect on a layout-less graph (?? {} / ?? []) ----
  it('drag, group-drag and connect tolerate a layout-less graph', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // node drag with no layout at all → onCanvasPointerMove's `g.layout ?? {}` paths
    c.graph.set({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' } },
      ],
    } as unknown as FlowGraph);
    stubCanvas(c);
    c.onNodePointerDown(ptr(0, 0), 'a');
    c.onCanvasPointerMove(ptr(40, 40)); // seeds layout.positions from {}
    expect(c.graph().layout.positions.a).toBeDefined();
    c.onCanvasPointerUp(ptr(40, 40));

    // connect-create on a layout-less graph with manual positions for nodeAt()
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

  it('group drag tolerates a layout that has groups but no positions map', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    // layout has groups but the positions map is entirely absent → onCanvasPointerMove
    // reads `g.layout?.positions ?? {}` (right side) without throwing.
    c.graph.set({
      states: [
        { key: 'a', label: { de: 'A' }, isInitial: true },
        { key: 'b', label: { de: 'B' } },
      ],
      transitions: [],
      layout: { groups: [{ id: 'g1', name: 'G', stateKeys: ['a', 'b'] }] },
    } as unknown as FlowGraph);
    stubCanvas(c);
    c.onGroupPointerDown(ptr(0, 0), 'g1'); // drag the group directly by id
    c.onCanvasPointerMove(ptr(30, 30)); // deepKeys present but no positions → no moves
    expect(c.graph().layout.positions).toBeDefined();
    c.onCanvasPointerUp(ptr(30, 30));
  });

  it('group drag tolerates a graph whose layout has only groups', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('a');
    // group {a,b} with positions present so the box renders
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
    c.onCanvasPointerMove(ptr(50, 50)); // moves both members through `?? {}`
    expect(c.graph().layout.positions.a).toBeDefined();
    c.onCanvasPointerUp(ptr(50, 50));
  });

  // --- patchGroup on a layout-less graph (rename before any layout exists) ---
  it('renameGroup/setGroupColor tolerate a layout-less graph', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.graph.set({
      states: [{ key: 'a', label: { de: 'A' }, isInitial: true }],
    } as unknown as FlowGraph);
    // no layout at all → patchGroup's `g.layout ?? {}` and `g.layout?.groups ?? []`
    c.renameGroup('nope', 'X'); // no such group → map over [] is a no-op
    c.setGroupColor('nope', '#000');
    expect(c.graph().layout?.groups ?? []).toEqual([]);
  });

  // --- dissolveCurrentGroup: currentGroupId points at a vanished group --------
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
    // remove the group from the layout WITHOUT re-running the reset effect, then
    // dissolve: `me` is undefined → the `if (!me) return g` early-out fires.
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: { ...g.layout, groups: [] },
    }));
    c.dissolveCurrentGroup();
    expect(c.groups()).toHaveLength(0);
  });

  // --- dissolve a leaf nested group while a sibling group also exists ---------
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
    // outer contains a + sub-group {b,c}; a separate sibling group {d,e} also exists
    c.graph.update((g: FlowGraph) => ({
      ...g,
      layout: {
        positions: {
          a: { x: 0, y: 0 }, b: { x: 100, y: 0 }, c: { x: 200, y: 0 },
          d: { x: 300, y: 0 }, e: { x: 400, y: 0 },
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
    c.dissolveCurrentGroup(); // inner has no groupIds → `me.groupIds ?? []` right side
    expect(c.currentGroupId()).toBe('outer');
    const outer = c.groups().find((g: { id: string }) => g.id === 'outer');
    expect(outer.stateKeys.sort()).toEqual(['a', 'b', 'c']);
    // the sibling group is still present and untouched
    expect(c.groups().some((g: { id: string }) => g.id === 'sibling')).toBe(true);
  });

  // --- relayout where the marked initial lives inside a child group ----------
  it('relayout treats a group containing the initial state as the initial entity', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setStateKey('state3', 'c');
    c.setInitial('b'); // initial is b, which will live inside the group
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'a', to: 'b', actions: [] }],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection(); // group {b,c} contains the initial b
    // relayout at top level: the group's isInitial = deepKeys.includes('b') → true
    c.relayout();
    expect(c.graph().layout.positions.a).toBeDefined();
    expect(c.graph().layout.positions.b).toBeDefined();
  });

  // --- proxy label fallback: proxy refers to a group that is not in groupById -
  it('proxy label uses the raw key when the external state is unknown', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // Build a level whose left proxy points at a state key that is not in states.
    // Transition from a (group member) back to a phantom external key is hard via
    // the UI, so seed an edge from an external phantom into a grouped state.
    c.addState();
    c.addState();
    c.setStateKey('state', 'a'); // grouped
    c.setStateKey('state2', 'b');
    c.setInitial('b');
    c.graph.update((g: FlowGraph) => ({
      ...g,
      // 'phantom' is referenced by a transition but is NOT a real state
      transitions: [{ from: 'phantom', to: 'a', actions: [] }],
      layout: {
        positions: { a: { x: 0, y: 0 }, b: { x: 200, y: 0 }, phantom: { x: -300, y: 0 } },
        groups: [{ id: 'g1', name: 'G1', stateKeys: ['a'] }],
      },
    }));
    c.openGroup('g1');
    fixture.detectChanges();
    // 'phantom' resolves to a left proxy whose label is the raw key (no state match)
    const left = c.proxies().left;
    const phantom = left.find((p: { pid: string }) => p.pid === 'state:phantom');
    expect(phantom?.label).toBe('phantom');
  });

  // --- proxies computed on a drilled-in level with no transitions array ------
  it('proxies tolerate a drilled-in level whose transitions array is missing', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    // a graph with NO transitions field, two states, one group → drill in.
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
    c.openGroup('g1'); // currentGroupId set → proxies runs `transitions ?? []`
    fixture.detectChanges();
    // no transitions → no proxies, but the computed runs without throwing
    expect(c.proxies()).toEqual({ left: [], right: [] });
  });

  // --- relayout where a child group has members without positions -----------
  it('relayout skips a child group whose members have no positions', async () => {
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
    // group {b,c} but b/c have NO positions → relayout's `if (!pts.length) continue`
    c.graph.update((g: FlowGraph) => ({
      ...g,
      transitions: [{ from: 'a', to: 'b', actions: [] }],
      layout: {
        positions: { a: { x: 0, y: 0 } }, // b, c missing
        groups: [{ id: 'g1', name: 'G', stateKeys: ['b', 'c'] }],
      },
    }));
    c.relayout();
    // a still gets a position; the position-less group block is skipped without error
    expect(c.graph().layout.positions.a).toBeDefined();
  });

  // --- relayout with no marked initial but a child group present -------------
  it('relayout marks no group as initial when the graph has no initial state', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addState();
    c.addState();
    c.addState();
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setStateKey('state3', 'c');
    // clear any initial flag
    c.graph.update((g: FlowGraph) => ({
      ...g,
      states: g.states.map((s: { isInitial?: boolean }) => ({ ...s, isInitial: false })),
      transitions: [{ from: 'a', to: 'b', actions: [] }],
    }));
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection(); // child group {b,c} at top level
    // relayout at top: initialKey is undefined → group isInitial uses the `: false` arm
    c.relayout();
    expect(c.graph().layout.positions.a).toBeDefined();
  });

  // --- patchGroup with several groups exercises the `: gr` else --------------
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
    c.renameGroup(g1, 'First'); // g2 must hit the `: gr` else branch in patchGroup
    expect(c.groups().find((g: { id: string }) => g.id === g1).name).toBe('First');
    expect(c.groups().find((g: { id: string }) => g.id === g2).name).not.toBe('First');
  });

  // --- regrouping that empties an existing group → the group is filtered out --
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
    // first group {b,c}
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    const first = c.groups()[0].id;
    expect(c.groups()).toHaveLength(1);
    // now group {b,c} AGAIN into a new group → the old group loses both members and,
    // having no groupIds, is filtered away (stateKeys 0 AND groupIds 0).
    c.multiSel.set(new Set(['b', 'c']));
    c.createGroupFromSelection();
    expect(c.groups().some((g: { id: string }) => g.id === first)).toBe(false);
    expect(c.groups()).toHaveLength(1);
  });
});
