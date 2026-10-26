import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { ExpandRowComponent } from './expand-row.component';

async function setup(template: string, props: Record<string, unknown> = {}) {
  return render(template, { imports: [ExpandRowComponent], componentProperties: props });
}

describe('ExpandRowComponent', () => {
  it('opens and closes its body on a press on the row, and says so on the row button', async () => {
    const { container } = await setup(`<app-expand-row title="Finanzer" sub="3 Rechte"><p>Rechte</p></app-expand-row>`);
    const head = screen.getByRole('button', { name: /Finanzer/ });
    expect(head).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Rechte')).toBeNull();

    await userEvent.click(head);
    expect(head).toHaveAttribute('aria-expanded', 'true');
    const body = screen.getByText('Rechte').parentElement!;
    expect(head).toHaveAttribute('aria-controls', body.id);
    expect(container.querySelector('app-expand-row')).toHaveClass('xr--open');
    expect(await runAxe(container)).toHaveNoViolations();

    await userEvent.click(head);
    expect(head).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Rechte')).toBeNull();
  });

  it('emits activate on a press on the row in chevron mode, and only the chevron opens', async () => {
    const activate = jest.fn();
    const { container } = await setup(
      `<app-expand-row title="Hook" toggle="chevron" toggleLabel="Zustellstatus: Hook" (activate)="activate()"><p>Status</p></app-expand-row>`,
      { activate },
    );
    const head = screen.getByRole('button', { name: /^Hook/ });
    expect(head).not.toHaveAttribute('aria-expanded');

    await userEvent.click(head);
    expect(activate).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Status')).toBeNull();

    const chevron = screen.getByRole('button', { name: 'Zustellstatus: Hook' });
    expect(chevron).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(chevron);
    expect(chevron).toHaveAttribute('aria-expanded', 'true');
    expect(chevron).toHaveAttribute('aria-controls', screen.getByText('Status').parentElement!.id);
    expect(activate).toHaveBeenCalledTimes(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('follows the open input and reports a flip through openChange', async () => {
    const openChange = jest.fn();
    const { rerender } = await setup(
      `<app-expand-row title="Gremium" [open]="open" (openChange)="openChange($event)"><p>Mitglieder</p></app-expand-row>`,
      { open: true, openChange },
    );
    expect(screen.getByText('Mitglieder')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /Gremium/ }));
    expect(openChange).toHaveBeenCalledWith(false);
    expect(screen.queryByText('Mitglieder')).toBeNull();
    await rerender({ componentProperties: { open: false, openChange } });
    await rerender({ componentProperties: { open: true, openChange } });
    expect(screen.getByText('Mitglieder')).toBeTruthy();
  });
});
