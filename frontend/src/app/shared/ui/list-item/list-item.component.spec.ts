import { Component, signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { ListItemComponent } from './list-item.component';

@Component({ standalone: true, template: '' })
class BlankComponent {}

const LONG = 'Sondersitzung des AStA-Vorstands zur Haushaltsplanung 2027 mit Referatsleitungen';

@Component({
  standalone: true,
  imports: [ListItemComponent],
  template: `
    <app-list-item [title]="title" [selected]="selected()" (activate)="opened = opened + 1">
      <span lead data-testid="lead">L</span>
      <span sub>Förderantrag</span>
      <button trail type="button" (click)="trail = trail + 1">Menü</button>
    </app-list-item>
  `,
})
class HostComponent {
  title = LONG;
  readonly selected = signal(false);
  opened = 0;
  trail = 0;
}

describe('ListItemComponent', () => {
  it('shows the title on one line and keeps the full text as the title attribute', async () => {
    await render(HostComponent);
    const title = screen.getByRole('button', { name: LONG });
    expect(title).toHaveAttribute('title', LONG);
    expect(title).toHaveClass('li__title');
  });

  it('projects the lead, the sub line and the trailing slot', async () => {
    await render(HostComponent);
    expect(screen.getByTestId('lead')).toBeInTheDocument();
    expect(screen.getByText('Förderantrag')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Menü' })).toBeInTheDocument();
  });

  it('emits activate on a click, on Enter and on Space', async () => {
    const view = await render(HostComponent);
    const user = userEvent.setup();
    const title = screen.getByRole('button', { name: LONG });
    await user.click(title);
    title.focus();
    await user.keyboard('{Enter}');
    await user.keyboard(' ');
    expect(view.fixture.componentInstance.opened).toBe(3);
  });

  it('keeps a click on a trailing control to that control', async () => {
    const view = await render(HostComponent);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Menü' }));
    expect(view.fixture.componentInstance.trail).toBe(1);
    expect(view.fixture.componentInstance.opened).toBe(0);
  });

  it('marks the selected row as current', async () => {
    const view = await render(HostComponent);
    const title = screen.getByRole('button', { name: LONG });
    expect(title).not.toHaveAttribute('aria-current');
    view.fixture.componentInstance.selected.set(true);
    view.fixture.detectChanges();
    expect(title).toHaveAttribute('aria-current', 'true');
    expect(view.container.querySelector('.li')).toHaveClass('li--on');
  });

  it('renders a link when it has a target and still emits activate', async () => {
    const activate = jest.fn();
    await render(ListItemComponent, {
      inputs: { title: 'Druckkosten', link: ['/applications', 'a1'], selected: true },
      on: { activate },
      providers: [provideRouter([{ path: '**', component: BlankComponent }])],
    });
    const link = screen.getByRole('link', { name: 'Druckkosten' });
    expect(link).toHaveAttribute('href', '/applications/a1');
    expect(link).toHaveAttribute('aria-current', 'true');
    await userEvent.setup().click(link);
    expect(activate).toHaveBeenCalledTimes(1);
  });

  it('shows a plain sub line from the input', async () => {
    const { container } = await render(ListItemComponent, {
      inputs: { title: 'Lastenrad', sub: 'Fachschaftsmittel' },
    });
    expect(container.querySelector('.li__subText')).toHaveTextContent('Fachschaftsmittel');
  });

  it('has no a11y violations', async () => {
    const { container } = await render(HostComponent);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
