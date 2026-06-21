import { render, screen, fireEvent } from '@testing-library/angular';
import { CostCentreTreeComponent } from './cost-centre-tree.component';
import { PALETTE } from './budget-year-tree.component';
import type { BudgetTreeNode } from './budget-tree.api';

function node(over: Partial<BudgetTreeNode> = {}): BudgetTreeNode {
  return {
    id: 'n-1',
    parentId: null,
    gremiumId: null,
    key: 'VS',
    pathKey: 'VS',
    name: 'VS-Mittel',
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
    ...over,
  };
}

describe('CostCentreTreeComponent', () => {
  it('renders an empty-state label when there are no nodes and no "all" node', async () => {
    await render(CostCentreTreeComponent, {
      inputs: { nodes: [], emptyLabel: 'Keine Kostenstellen' },
    });
    expect(screen.getByText('Keine Kostenstellen')).toBeInTheDocument();
  });

  it('does NOT show the empty-state when an "all" node is configured', async () => {
    await render(CostCentreTreeComponent, {
      inputs: { nodes: [], allLabel: 'Alle', emptyLabel: 'Keine Kostenstellen' },
    });
    expect(screen.queryByText('Keine Kostenstellen')).not.toBeInTheDocument();
    expect(screen.getByText('Alle')).toBeInTheDocument();
  });

  it('renders the "all" node and emits "" when it is clicked', async () => {
    let picked: string | undefined;
    const { fixture } = await render(CostCentreTreeComponent, {
      inputs: { nodes: [node()], allLabel: 'Alle', selectedId: '' },
      on: { picked: (id: string) => (picked = id) },
    });
    // With no selection, the "all" node is the active one.
    expect(fixture.nativeElement.querySelector('.cct__node--all.cct__node--active')).toBeTruthy();
    fireEvent.click(screen.getByText('Alle'));
    expect(picked).toBe('');
  });

  it('renders roots + recursive children with key and name', async () => {
    const tree = [
      node({
        id: 'r',
        key: 'VS',
        name: 'Root',
        children: [node({ id: 'c', key: '800', name: 'Child', children: [] })],
      }),
    ];
    const { fixture } = await render(CostCentreTreeComponent, { inputs: { nodes: tree } });
    expect(screen.getByText('VS')).toBeInTheDocument();
    expect(screen.getByText('Root')).toBeInTheDocument();
    expect(screen.getByText('800')).toBeInTheDocument();
    expect(screen.getByText('Child')).toBeInTheDocument();
    // The root is depth 0 → has a colour dot; the child (depth>0) does not.
    const dots = fixture.nativeElement.querySelectorAll('.cct__dot');
    expect(dots.length).toBe(1);
    // The child branch has the children wrapper.
    expect(fixture.nativeElement.querySelector('.cct__children')).toBeTruthy();
  });

  it('emits the node id when a node button is clicked', async () => {
    let picked: string | undefined;
    await render(CostCentreTreeComponent, {
      inputs: { nodes: [node({ id: 'n-42', key: 'K', name: 'Klick' })] },
      on: { picked: (id: string) => (picked = id) },
    });
    fireEvent.click(screen.getByText('Klick'));
    expect(picked).toBe('n-42');
  });

  it('marks the selected node as active', async () => {
    const { fixture } = await render(CostCentreTreeComponent, {
      inputs: { nodes: [node({ id: 'sel', key: 'K', name: 'N' })], selectedId: 'sel' },
    });
    expect(fixture.nativeElement.querySelector('.cct__node--active')).toBeTruthy();
  });

  it('sets the aria-label from the input', async () => {
    const { fixture } = await render(CostCentreTreeComponent, {
      inputs: { nodes: [], ariaLabel: 'Kostenstellen-Baum' },
    });
    expect(fixture.nativeElement.querySelector('nav').getAttribute('aria-label')).toBe(
      'Kostenstellen-Baum',
    );
  });

  describe('dotColor', () => {
    it('returns the explicit colour when the node has one', async () => {
      const { fixture } = await render(CostCentreTreeComponent, {
        inputs: { nodes: [node({ id: 'r', color: '#123456' })] },
      });
      expect(fixture.componentInstance.dotColor(node({ id: 'r', color: '#123456' }))).toBe(
        '#123456',
      );
    });

    it('falls back to the palette indexed by the root position', async () => {
      const roots = [node({ id: 'r0' }), node({ id: 'r1' })];
      const { fixture } = await render(CostCentreTreeComponent, { inputs: { nodes: roots } });
      const c = fixture.componentInstance;
      expect(c.dotColor(roots[0])).toBe(PALETTE[0]);
      expect(c.dotColor(roots[1])).toBe(PALETTE[1]);
    });

    it('returns the last palette colour for a node missing from the roots (index -1)', async () => {
      const { fixture } = await render(CostCentreTreeComponent, {
        inputs: { nodes: [node({ id: 'known' })] },
      });
      const expected = PALETTE[PALETTE.length - 1];
      expect(fixture.componentInstance.dotColor(node({ id: 'unknown' }))).toBe(expected);
    });
  });
});
