import { fireEvent, render, screen } from '@testing-library/angular';
import type { BudgetTreeNode } from '../../budget/budget-tree.api';
import { CostCentrePickerComponent, findCostCentre } from './cost-centre-picker.component';

function node(id: string, key: string, name: string, children: BudgetTreeNode[] = []): BudgetTreeNode {
  return {
    id,
    parentId: null,
    gremiumId: null,
    key,
    pathKey: key,
    name,
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
    children,
  };
}

const TREE = [node('r', 'VSM', 'Wurzel', [node('c', 'VSM-8', 'Kind')])];

describe('CostCentrePickerComponent', () => {
  it('finds nodes at any depth', () => {
    expect(findCostCentre(TREE, 'c')?.name).toBe('Kind');
    expect(findCostCentre(TREE, 'x')).toBeNull();
  });

  it('shows the placeholder, opens the tree and emits the pick', async () => {
    const view = await render(CostCentrePickerComponent, {
      inputs: { nodes: TREE, value: '', label: 'Kostenstelle', placeholder: 'Wählen…', allLabel: 'Alle' },
    });
    const picked: string[] = [];
    view.fixture.componentInstance.picked.subscribe((id: string) => picked.push(id));
    const button = screen.getByRole('button', { name: /Kostenstelle/ });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('Wählen…')).toBeInTheDocument();
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(screen.getByText('Kind'));
    expect(picked).toEqual(['c']);
    // The pick closes the tree.
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });

  it('shows "path key · name", or the unknown label for an id outside the tree', async () => {
    const view = await render(CostCentrePickerComponent, {
      inputs: { nodes: TREE, value: 'c', label: 'K', unknownLabel: 'Unbekannt' },
    });
    expect(screen.getByText('VSM-8 · Kind')).toBeInTheDocument();
    view.fixture.componentRef.setInput('value', 'zzz');
    view.fixture.detectChanges();
    expect(screen.getByText('Unbekannt')).toBeInTheDocument();
  });
});
