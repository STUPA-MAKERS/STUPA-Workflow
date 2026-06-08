import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { FlowGraph } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { FlowEditorComponent } from './flow-editor.component';

async function setup() {
  const createFlowVersion = jest.fn(() => of({ id: 'fv1' }));
  const listApplicationTypes = jest.fn(() => of([{ id: 't1', name: 'Finanzantrag' }]));
  const api = { createFlowVersion, listApplicationTypes };
  const view = await render(FlowEditorComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
  });
  return { ...view, createFlowVersion };
}

describe('FlowEditorComponent (Drag&Drop-Canvas)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('reports an empty graph as invalid and disables save', async () => {
    await setup();
    expect(screen.getByText('flow graph has no states')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Als Flow-Version speichern' })).toBeDisabled();
  });

  it('applies a preset to a valid graph and saves it', async () => {
    const { createFlowVersion } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Vorlage übernehmen' }));

    const save = screen.getByRole('button', { name: 'Als Flow-Version speichern' });
    expect(save).toBeEnabled();
    await userEvent.click(save);

    expect(createFlowVersion).toHaveBeenCalledTimes(1);
    const graph = createFlowVersion.mock.calls[0][1] as FlowGraph;
    expect(graph.states.map((s) => s.key)).toEqual(['draft', 'submitted', 'decided']);
    expect(graph.states.filter((s) => s.isInitial)).toHaveLength(1);
    expect(graph.layout?.positions).toBeDefined(); // layout persisted
  });

  it('renders one canvas node per state', async () => {
    const { container } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Vorlage übernehmen' }));
    // 3 states → 3 node-text labels in the SVG canvas
    expect(container.querySelectorAll('.fe__node-text')).toHaveLength(3);
  });

  it('exposes guard operators only for a selected transition in expert mode', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    await userEvent.click(screen.getByRole('button', { name: 'Vorlage übernehmen' }));
    // Nothing selected → no inspector guard control.
    expect(screen.queryByRole('combobox', { name: 'Bedingung (Guard)' })).not.toBeInTheDocument();

    c.selectEdge(0); // erste Transition auswählen
    c.setMode('expert');
    fixture.detectChanges();
    expect(screen.getByRole('combobox', { name: 'Bedingung (Guard)' })).toBeInTheDocument();
  });

  it('exercises state/transition/guard/action/automatic mutators', async () => {
    const { fixture, createFlowVersion } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;

    c.addState();
    c.addState();
    expect(c.graph().states).toHaveLength(2);
    c.setStateKey('state', 'a');
    c.setStateKey('state2', 'b');
    c.setInitial('b');
    c.setInitial('a'); // a is initial; toggling exercises the reset branch
    expect(c.graph().states.filter((s: { isInitial?: boolean }) => s.isInitial)).toHaveLength(1);
    c.setStateCategory('a', 'open');
    c.setStateCategory('a', ''); // clear → null branch
    c.setStateLabel('a', 'Entwurf');
    c.setStateEditAllowed('a', false);

    // Übergang a→b anlegen (entspricht dem Aufziehen im Canvas).
    c.graph.update((g: FlowGraph) => ({ ...g, transitions: [{ from: 'a', to: 'b', actions: [] }] }));
    c.selectEdge(0);
    c.setGuard(0, 'roleIs', 'x');
    expect(c.guardOp(c.graph().transitions[0])).toBe('roleIs');
    expect(c.guardValue(c.graph().transitions[0])).toBe('x');
    c.setGuard(0, 'manual', 'true'); // boolean coercion branch
    c.setGuard(0, '', ''); // remove guard branch
    expect(c.graph().transitions[0].guard).toBeUndefined();

    c.setTransitionAutomatic(0, true); // #8
    expect(c.graph().transitions[0].automatic).toBe(true);

    c.addAction(0, 'notify');
    c.addAction(0, ''); // no-op branch
    expect(c.graph().transitions[0].actions).toHaveLength(1);
    c.removeAction(0, 0);
    c.setTransitionLabel(0, 'go');
    c.setTransitionEndpoint(0, 'to', 'b');

    c.setMode('expert');
    c.relayout();
    c.save(); // graph valid (a initial, b reachable) → success
    expect(createFlowVersion).toHaveBeenCalled();
    const graph = createFlowVersion.mock.calls[0][1] as FlowGraph;
    expect(graph.transitions[0].automatic).toBe(true); // automatisch serialisiert

    c.selectEdge(0);
    c.removeSelectedTransition();
    expect(c.graph().transitions).toHaveLength(0);
    c.selection.set({ kind: 'state', key: 'b' });
    c.removeSelectedState();
    expect(c.graph().states).toHaveLength(1);
  });

  it('saves nothing and warns when the graph is invalid', async () => {
    const { fixture, createFlowVersion } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.save(); // empty graph → invalid → error path, no API call
    expect(createFlowVersion).not.toHaveBeenCalled();
  });
});
