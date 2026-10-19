import { fireEvent, render, screen } from '@testing-library/angular';
import type { BudgetTreeNode } from './budget-tree.api';
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

  it('names the pick by name, or by name and short path, with its colour', async () => {
    const coloured = [{ ...node('r', 'VSM', 'Wurzel', [node('c', 'VSM-8', 'Kind')]), color: '#ff0000' }];
    const view = await render(CostCentrePickerComponent, {
      inputs: { nodes: coloured, value: 'c', label: 'K', text: 'name', swatch: true },
    });
    const value = screen.getByText('Kind');
    expect(value).toHaveAttribute('title', 'Kind');
    const swatch = view.container.querySelector('.ccp__swatch') as HTMLElement;
    expect(swatch).toBeTruthy();
    expect(swatch.style.background).not.toBe('');
    view.fixture.componentRef.setInput('text', 'namePath');
    view.fixture.detectChanges();
    expect(view.container.querySelector('.ccp__path')?.textContent).toBe('VSM-8');
    // Without `swatch` there is no colour, and an unknown id has none either.
    view.fixture.componentRef.setInput('swatch', false);
    view.fixture.detectChanges();
    expect(view.container.querySelector('.ccp__swatch')).toBeNull();
    view.fixture.componentRef.setInput('swatch', true);
    view.fixture.componentRef.setInput('value', 'zzz');
    view.fixture.detectChanges();
    expect(view.container.querySelector('.ccp__swatch')).toBeNull();
    expect(view.container.querySelector('.ccp__path')).toBeNull();
  });

  it('marks a required field and takes a grid cell with inGrid', async () => {
    const view = await render(CostCentrePickerComponent, {
      inputs: { nodes: TREE, label: 'Kostenstelle', placeholder: 'Wählen', required: true, inGrid: true },
    });
    expect(view.container.querySelector('.text-danger')?.textContent?.trim()).toBe('*');
    // The asterisk is not part of the name.
    expect(screen.getByRole('button', { name: 'Kostenstelle Wählen' })).toBeInTheDocument();
    expect((view.fixture.nativeElement as HTMLElement).classList.contains('ccp--grid')).toBe(true);
  });
});
