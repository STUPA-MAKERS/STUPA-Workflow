import { render, screen } from '@testing-library/angular';
import { EmptyStateComponent } from './empty-state.component';

describe('EmptyStateComponent', () => {
  it('shows the heading as a section heading when it fills the page or pane', async () => {
    await render(EmptyStateComponent, {
      inputs: { heading: 'Antrag nicht gefunden', fill: true },
    });
    expect(
      screen.getByRole('heading', { level: 2, name: 'Antrag nicht gefunden' }),
    ).toBeInTheDocument();
  });

  it('omits the body when there is nothing useful to add', async () => {
    const { container } = await render(EmptyStateComponent, {
      inputs: { heading: 'Nichts da' },
    });
    expect(container.querySelector('.es__body')).toBeNull();
  });

  it('shows a code above the heading when one is given', async () => {
    await render(EmptyStateComponent, {
      inputs: { heading: 'Seite nicht gefunden', code: '404' },
    });
    expect(screen.getByText('404')).toBeInTheDocument();
  });

  it('draws five ghost rows hidden from the screen reader', async () => {
    const { container } = await render(EmptyStateComponent, {
      inputs: { heading: 'Leer' },
    });
    expect(container.querySelector('.es__ghosts')).toHaveAttribute('aria-hidden', 'true');
    expect(container.querySelectorAll('.es__ghost')).toHaveLength(5);
  });

  it('draws fewer ghost rows when asked, at least one and at most five', async () => {
    const { container, rerender } = await render(EmptyStateComponent, {
      inputs: { heading: 'Leer', rows: 3 },
    });
    expect(container.querySelectorAll('.es__ghost')).toHaveLength(3);
    await rerender({ inputs: { heading: 'Leer', rows: 0 }, partialUpdate: true });
    expect(container.querySelectorAll('.es__ghost')).toHaveLength(1);
    await rerender({ inputs: { heading: 'Leer', rows: 9 }, partialUpdate: true });
    expect(container.querySelectorAll('.es__ghost')).toHaveLength(5);
  });

  it('is a plain line, not a heading, inside a card or a dialog', async () => {
    await render(EmptyStateComponent, { inputs: { heading: 'Leer' } });
    expect(screen.queryByRole('heading')).toBeNull();
    expect(screen.getByText('Leer')).toBeInTheDocument();
  });

  it('takes an explicit heading level', async () => {
    await render(EmptyStateComponent, { inputs: { heading: 'Leer', level: 3 } });
    expect(screen.getByRole('heading', { level: 3, name: 'Leer' })).toBeInTheDocument();
  });

  it('accepts the level as a bare attribute', async () => {
    await render(`<app-empty-state heading="Leer" level="1" />`, { imports: [EmptyStateComponent] });
    expect(screen.getByRole('heading', { level: 1, name: 'Leer' })).toBeInTheDocument();
  });

  it('projects the way on below the message', async () => {
    await render(
      `<app-empty-state heading="Leer"><button type="button">Zurücksetzen</button></app-empty-state>`,
      { imports: [EmptyStateComponent] },
    );
    expect(screen.getByRole('button', { name: 'Zurücksetzen' }).closest('.es__action')).toBeTruthy();
  });

  it('stays at its own height by default, for cards and list rows', async () => {
    const { fixture } = await render(EmptyStateComponent, {
      inputs: { heading: 'Leer' },
    });
    expect(fixture.nativeElement).not.toHaveClass('es-host--fill');
  });

  it('fills and centres in the page when fill is set', async () => {
    const { fixture } = await render(EmptyStateComponent, {
      inputs: { heading: 'Leer', fill: true },
    });
    expect(fixture.nativeElement).toHaveClass('es-host--fill');
  });

  it('accepts fill as a bare attribute', async () => {
    const { container } = await render(
      `<app-empty-state heading="Leer" fill />`,
      { imports: [EmptyStateComponent] },
    );
    expect(container.querySelector('app-empty-state')).toHaveClass('es-host--fill');
  });
});
