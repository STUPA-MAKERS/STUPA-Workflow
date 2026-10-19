import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { TodoAssigneesComponent } from './todo-assignees.component';
import { TodoDueComponent } from './todo-due.component';
import { TodoLabelComponent } from './todo-label.component';

describe('to-do card facts', () => {
  it('shows a label as a hidden dot in the label colour before its name', async () => {
    const { container } = await render(`<app-todo-label [label]="label" />`, {
      imports: [TodoLabelComponent],
      componentProperties: { label: { id: 'l1', name: 'Finanzen', color: 'green' } },
    });
    const label = screen.getByText('Finanzen');
    expect(label).toHaveAttribute('data-color', 'green');
    expect(label.querySelector('.tlb__dot')).toHaveAttribute('aria-hidden', 'true');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the due date with its note and colours an overdue one', async () => {
    const { container, rerender } = await render(`<app-todo-due [due]="due" />`, {
      imports: [TodoDueComponent],
      componentProperties: { due: { date: '14.10.', note: 'überfällig', tone: 'overdue' } },
    });
    const host = container.querySelector('app-todo-due')!;
    expect(host).toHaveTextContent('14.10. · überfällig');
    expect(host).toHaveClass('tdu--overdue');
    await rerender({ componentProperties: { due: { date: '30.10.', note: null, tone: 'normal' } } });
    expect(host.textContent?.trim()).toBe('30.10.');
    expect(host).not.toHaveClass('tdu--overdue');
    expect(host).not.toHaveClass('tdu--soon');
  });

  it('takes the quiet colour from the page', () => {
    const scss = readFileSync(join(__dirname, 'todo-due.component.scss'), 'utf8');
    expect(scss).toContain('color: var(--tdu-color, currentColor)');
  });

  it('shows the avatars of the people, or a named empty circle', async () => {
    const { container, rerender } = await render(`<app-todo-assignees [names]="names" [ids]="ids" />`, {
      imports: [TodoAssigneesComponent],
      componentProperties: { names: ['Anna Berg'], ids: [null] as (string | null)[] },
    });
    expect(container.querySelector('app-avatar-stack')).not.toBeNull();
    expect(screen.queryByRole('img', { name: 'Niemand zuständig' })).toBeNull();
    await rerender({ componentProperties: { names: [], ids: [] } });
    expect(container.querySelector('app-avatar-stack')).toBeNull();
    expect(screen.getByRole('img', { name: 'Niemand zuständig' })).toBeInTheDocument();
  });
});
