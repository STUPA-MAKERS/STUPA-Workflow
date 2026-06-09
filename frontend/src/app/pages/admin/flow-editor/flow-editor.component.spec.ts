import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import type { FlowGraph } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { FlowEditorComponent } from './flow-editor.component';

async function setup() {
  // Globaler Flow (#28): laden + speichern statt per-Typ.
  const getGlobalFlow = jest.fn(() => of(null));
  const createGlobalFlowVersion = jest.fn(() => of({ id: 'gfv1' }));
  const listApplicationTypes = jest.fn(() => of([{ id: 't1', name: 'Finanzantrag' }]));
  // vote/approval-State-Config (#28): Gremien + Gremium-Rollen + globale Rollen.
  const listGremienOptions = jest.fn(() => of([{ id: 'g1', name: 'StuPa', slug: 'stupa', cdVariant: 'stupa', defaultLang: 'de' }]));
  const listGremiumRoles = jest.fn(() => of([{ id: 'gr1', key: 'vorsitz', name: { de: 'Vorsitz' } }]));
  const listRoles = jest.fn(() => of([{ id: 'r1', key: 'finance', label: { de: 'Finanzen' }, permissions: [] }]));
  const listDeadlinePolicies = jest.fn(() => of([{ id: 'dp1', key: 'semester', label: { de: 'Semesterfrist' }, kind: 'absolute' }]));
  const listWebhooks = jest.fn(() => of([{ id: 'w1', name: 'Buchhaltung', url: 'https://h.test', events: [], active: true }]));
  const api = { getGlobalFlow, createGlobalFlowVersion, listApplicationTypes, listGremienOptions, listGremiumRoles, listRoles, listDeadlinePolicies, listWebhooks };
  const view = await render(FlowEditorComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
  });
  return { ...view, createGlobalFlowVersion };
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
    expect(screen.getByRole('button', { name: 'Als Flow-Version speichern' })).toBeDisabled();
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
    // Guard ist auf manuellen und automatischen Übergängen verfügbar (#28).
    expect(screen.getByRole('combobox', { name: 'Bedingung (Guard)' })).toBeInTheDocument();
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
});
