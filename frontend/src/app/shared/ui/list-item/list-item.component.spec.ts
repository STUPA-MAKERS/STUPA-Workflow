import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { fireEvent, render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { StatusTextComponent } from '../status-text/status-text.component';
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

@Component({
  standalone: true,
  imports: [ListItemComponent, StatusTextComponent],
  template: `
    <app-list-item title="Druckkosten">
      <span sub data-testid="sub"
        ><app-status-text kind="warn">Auf Tagesordnung</app-status-text> · Förderantrag</span
      >
    </app-list-item>
  `,
})
class StatusSubHostComponent {}

@Component({
  standalone: true,
  imports: [ListItemComponent, StatusTextComponent],
  template: `
    <app-list-item title="35. Sitzung">
      <app-status-text status kind="accent">Live</app-status-text>
      <span sub>Studierendenparlament</span>
    </app-list-item>
  `,
})
class StatusTitleHostComponent {}

/** jsdom has no layout: give the sub line a width and a content width. */
function setWidths(el: Element, scroll: number, client: number): void {
  Object.defineProperty(el, 'scrollWidth', { configurable: true, value: scroll });
  Object.defineProperty(el, 'clientWidth', { configurable: true, value: client });
}

describe('ListItemComponent', () => {
  it('shows the title on one line and keeps the full text as the title attribute', async () => {
    await render(HostComponent);
    const title = screen.getByRole('button', { name: LONG });
    expect(title).toHaveAttribute('title', LONG);
    expect(title).toHaveClass('li__title');
  });

  it('puts a [status] on the title line, after the title and outside the control', async () => {
    await render(StatusTitleHostComponent);
    const title = screen.getByRole('button', { name: '35. Sitzung' });
    const status = screen.getByText('Live');
    const head = title.parentElement as HTMLElement;
    expect(head).toHaveClass('li__head');
    expect(head).toContainElement(status);
    expect(title).not.toContainElement(status);
    expect(title.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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

  it('keeps the current query params on the link when asked to', async () => {
    const { fixture } = await render(ListItemComponent, {
      inputs: { title: 'Druckkosten', link: ['/applications', 'a1'], linkQueryParamsHandling: 'preserve' },
      providers: [provideRouter([{ path: '**', component: BlankComponent }])],
    });
    await TestBed.inject(Router).navigateByUrl('/applications?type=t1');
    fixture.detectChanges();
    expect(screen.getByRole('link', { name: 'Druckkosten' })).toHaveAttribute('href', '/applications/a1?type=t1');
  });

  it('shows a plain sub line from the input', async () => {
    const { container } = await render(ListItemComponent, {
      inputs: { title: 'Lastenrad', sub: 'Fachschaftsmittel' },
    });
    expect(container.querySelector('.li__subText')).toHaveTextContent('Fachschaftsmittel');
  });

  it('puts the [sub] slot with a status into the one-line sub line', async () => {
    const { container } = await render(StatusSubHostComponent);
    const line = screen.getByTestId('sub').parentElement;
    expect(line).toHaveClass('li__sub');
    expect(line?.querySelector('app-status-text')).toHaveTextContent('Auf Tagesordnung');
    expect(container.querySelector('.li__sub')).toBe(line);
  });

  it('adds a cut sub line to the title tooltip when the pointer enters the row', async () => {
    const view = await render(StatusSubHostComponent);
    const control = screen.getByRole('button', { name: 'Druckkosten' });
    const line = view.container.querySelector('.li__sub') as HTMLElement;
    const row = view.container.querySelector('.li') as HTMLElement;

    setWidths(line, 180, 180);
    fireEvent.pointerEnter(row);
    view.fixture.detectChanges();
    expect(control).toHaveAttribute('title', 'Druckkosten');

    setWidths(line, 260, 180);
    fireEvent.pointerEnter(row);
    view.fixture.detectChanges();
    expect(control).toHaveAttribute('title', 'Druckkosten\nAuf Tagesordnung · Förderantrag');
  });

  it('adds a cut plain sub line to the title tooltip', async () => {
    const view = await render(ListItemComponent, {
      inputs: { title: 'Lastenrad', sub: 'Fachschaftsmittel für das Sommersemester' },
    });
    setWidths(view.container.querySelector('.li__sub') as HTMLElement, 300, 120);
    fireEvent.pointerEnter(view.container.querySelector('.li') as HTMLElement);
    view.fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Lastenrad' })).toHaveAttribute(
      'title',
      'Lastenrad\nFachschaftsmittel für das Sommersemester',
    );
  });

  it('has no a11y violations', async () => {
    const { container } = await render(HostComponent);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
