import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../testing/a11y';
import { DecisionEditorComponent } from './decision-editor.component';
import type { DecisionDraft } from './decision.util';

async function setup(draft: DecisionDraft, requested: string | null = '1250.00') {
  localStorage.setItem('ap.locale', 'de');
  const changes: DecisionDraft[] = [];
  const view = await render(DecisionEditorComponent, { inputs: { draft, requested } });
  const cmp = view.fixture.componentInstance;
  // A model signal is its own output.
  cmp.draft.subscribe((d) => changes.push(d));
  return { ...view, cmp, changes, last: () => changes[changes.length - 1] };
}

const norm = (s: string | null | undefined) => (s ?? '').replace(/\u00a0/g, ' ');

describe('DecisionEditorComponent', () => {
  it('shows only the switch while it is off', async () => {
    const { container, last } = await setup({ enabled: false, amount: '1250.00', conditions: [] });
    expect(screen.queryByLabelText('Förderbetrag')).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.click(screen.getByRole('switch', { name: /Mit Abweichungen genehmigen/ }));
    expect(last().enabled).toBe(true);
  });

  it('shows the requested amount and the difference', async () => {
    const { container, cmp, fixture } = await setup({ enabled: true, amount: '1250.00', conditions: [] });
    expect(norm(cmp.amountHint())).toBe('Beantragt: 1.250,00 €');
    fixture.componentRef.setInput('draft', { enabled: true, amount: '900', conditions: [] });
    fixture.detectChanges();
    expect(norm(cmp.amountHint())).toBe('Beantragt: 1.250,00 € · Abweichung −350,00 €');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has no hint without a requested amount', async () => {
    const { cmp } = await setup({ enabled: true, amount: '', conditions: [] }, null);
    expect(cmp.amountHint()).toBe('');
  });

  it('edits, adds, moves and removes the conditions', async () => {
    const { cmp, last, fixture } = await setup({ enabled: true, amount: '', conditions: ['A', 'B'] });
    await userEvent.click(screen.getByRole('button', { name: 'Auflage hinzufügen' }));
    expect(last().conditions).toEqual(['A', 'B', '']);
    fixture.componentRef.setInput('draft', { enabled: true, amount: '', conditions: ['A', 'B'] });
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Auflage 1 nach oben' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Auflage 2 nach unten' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Auflage 1 nach unten' }));
    expect(last().conditions).toEqual(['B', 'A']);
    cmp.moveCondition(0, -1);
    expect(last().conditions).toEqual(['B', 'A']);
    await userEvent.click(screen.getByRole('button', { name: 'Auflage 2 entfernen' }));
    expect(last().conditions).toEqual(['B']);
    cmp.setCondition(0, 'C');
    expect(last().conditions).toEqual(['C']);
    cmp.setAmount('5');
    expect(last().amount).toBe('5');
    cmp.setAmount(null as unknown as string);
    expect(last().amount).toBe('');
  });

  it('shows the errors of the amount and of the list', async () => {
    const { cmp, fixture } = await setup({ enabled: true, amount: '2000', conditions: [] });
    expect(cmp.amountError()).toContain('nicht übersteigen');
    expect(cmp.listError()).toBe('');
    fixture.componentRef.setInput('draft', { enabled: true, amount: '', conditions: ['x'.repeat(1001)] });
    fixture.detectChanges();
    expect(cmp.amountError()).toBe('');
    expect(screen.getByRole('alert')).toHaveTextContent('höchstens 1000 Zeichen');
  });

  it('stops adding at twenty conditions', async () => {
    const twenty = Array.from({ length: 20 }, (_, i) => `c${i}`);
    const { cmp, changes } = await setup({ enabled: true, amount: '', conditions: twenty });
    expect(cmp.canAdd()).toBe(false);
    cmp.addCondition();
    expect(changes).toEqual([]);
  });
});
