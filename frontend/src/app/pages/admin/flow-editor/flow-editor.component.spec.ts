import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { FlowGraph } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { FlowEditorComponent } from './flow-editor.component';

async function setup() {
  const createFlowVersion = jest.fn(() => of({ id: 'fv1' }));
  const api = { createFlowVersion };
  const view = await render(FlowEditorComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
  });
  return { ...view, createFlowVersion };
}

describe('FlowEditorComponent', () => {
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

  it('renders one diagram node per state', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Vorlage übernehmen' }));
    // 3 states → 3 <text> labels in the SVG
    const svg = screen.getByRole('img', { name: 'Diagramm' });
    expect(svg.querySelectorAll('text')).toHaveLength(3);
  });

  it('exposes guard operators only in expert mode', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Vorlage übernehmen' }));
    expect(screen.queryByRole('combobox', { name: 'Bedingung (Guard)' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Experte' }));
    expect(screen.getAllByRole('combobox', { name: 'Bedingung (Guard)' }).length).toBeGreaterThan(0);
  });

  it('exercises state/transition/guard/action mutators', async () => {
    const { fixture, createFlowVersion } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;

    c.addState();
    c.addState();
    c.graph().states[0].key = 'a';
    c.graph().states[1].key = 'b';
    c.touch();
    c.setInitial('b');
    c.setInitial('a'); // a is initial; toggling exercises the reset branch
    expect(c.graph().states.filter((s: { isInitial?: boolean }) => s.isInitial)).toHaveLength(1);
    c.setStateCategory(0, 'open');
    c.setStateCategory(0, ''); // clear → null branch

    c.addTransition(); // seeds a→a
    c.graph().transitions[0].to = 'b'; // a→b so b is reachable
    c.touch();
    c.setGuard(0, 'roleIs', 'x');
    expect(c.guardOp(c.graph().transitions[0])).toBe('roleIs');
    expect(c.guardValue(c.graph().transitions[0])).toBe('x');
    c.setGuard(0, 'manual', 'true'); // boolean coercion branch
    c.setGuard(0, '', ''); // remove guard branch
    expect(c.graph().transitions[0].guard).toBeUndefined();

    c.addAction(0, 'notify');
    c.addAction(0, ''); // no-op branch
    expect(c.graph().transitions[0].actions).toHaveLength(1);
    c.removeAction(0, 0);
    c.setTransitionLabel(0, 'go');
    c.setTransitionLabel(0, ''); // null label branch

    c.setMode('expert');
    c.relayout();
    c.save(); // graph valid (a initial, b reachable) → success
    expect(createFlowVersion).toHaveBeenCalled();

    c.removeTransition(0);
    c.removeState(1);
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
