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
  const api = { getGlobalFlow, createGlobalFlowVersion, listApplicationTypes, listGremienOptions, listGremiumRoles, listRoles };
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

  it('exposes the guard control only for an automatic transition', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    buildValid(c);
    c.selectEdge(0);
    fixture.detectChanges();
    expect(screen.queryByRole('combobox', { name: 'Bedingung (Guard)' })).not.toBeInTheDocument();
    c.setTransitionAutomatic(0, true);
    fixture.detectChanges();
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
    c.setStateCategory('a', 'open');
    c.setStateCategory('a', '');
    c.setStateLabel('a', 'de', 'Entwurf');
    c.setStateLabel('a', 'en', 'Draft');
    c.setStateEditAllowed('a', false);

    c.selectEdge(0);
    c.setGuard(0, 'roleIs', 'x');
    expect(c.guardOp(c.graph().transitions[0])).toBe('roleIs');
    expect(c.guardValue(c.graph().transitions[0])).toBe('x');
    c.setGuard(0, 'manual', 'true');
    c.setGuard(0, '', '');
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

  it('saves nothing and warns when the graph is invalid', async () => {
    const { fixture, createGlobalFlowVersion } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.save();
    expect(createGlobalFlowVersion).not.toHaveBeenCalled();
  });
});
