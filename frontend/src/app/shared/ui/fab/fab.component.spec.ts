import { provideRouter, Router } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { FabComponent } from './fab.component';

async function setup(template: string, props: Record<string, unknown> = {}) {
  const view = await render(template, {
    imports: [FabComponent],
    providers: [provideRouter([])],
    componentProperties: props,
  });
  const router = view.fixture.debugElement.injector.get(Router);
  return { ...view, router };
}

describe('FabComponent', () => {
  it('is one fab button with the plus icon and its label as the name', async () => {
    const { container } = await setup(`<app-fab label="Gremium anlegen" />`);
    const button = screen.getByRole('button', { name: 'Gremium anlegen' });
    expect(button).toHaveClass('btn--fab');
    expect(button).toHaveTextContent('Gremium anlegen');
    expect(container.querySelector('app-icon')).toBeTruthy();
    expect(container.querySelector('app-fab')).toHaveClass('fab');
    expect(container.querySelector('app-fab')).not.toHaveClass('fab--contained');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('emits activate on a click and from the keyboard', async () => {
    const activate = jest.fn();
    await setup(`<app-fab label="Frist anlegen" (activate)="activate()" />`, { activate });
    await userEvent.click(screen.getByRole('button', { name: 'Frist anlegen' }));
    expect(activate).toHaveBeenCalledTimes(1);
    (document.activeElement as HTMLElement).blur();
    await userEvent.tab();
    expect(screen.getByRole('button', { name: 'Frist anlegen' })).toHaveFocus();
    await userEvent.keyboard('{Enter}');
    expect(activate).toHaveBeenCalledTimes(2);
  });

  it('opens its link instead of emitting', async () => {
    const activate = jest.fn();
    const { router } = await setup(`<app-fab label="Antrag stellen" link="/apply" (activate)="activate()" />`, {
      activate,
    });
    const nav = jest.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Antrag stellen' }));
    expect(nav).toHaveBeenCalledWith('/apply');
    expect(activate).not.toHaveBeenCalled();
  });

  it('marks the contained mode on the host', async () => {
    const { container } = await setup(`<app-fab label="Sitzung anlegen" [contained]="true" />`);
    expect(container.querySelector('app-fab')).toHaveClass('fab--contained');
  });

  it('is the save action with the check icon, and takes no click while it saves or is disabled', async () => {
    const activate = jest.fn();
    const { rerender } = await setup(
      `<app-fab icon="check" label="Speichern" [loading]="loading" [disabled]="disabled" (activate)="activate()" />`,
      { activate, loading: true, disabled: false },
    );
    const button = screen.getByRole('button', { name: 'Speichern' });
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(button).toBeDisabled();
    await rerender({ componentProperties: { activate, loading: false, disabled: true } });
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled();
    await rerender({ componentProperties: { activate, loading: false, disabled: false } });
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(activate).toHaveBeenCalledTimes(1);
  });
});
