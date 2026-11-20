import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/angular';
import { ListDetailNav } from '@stupa-makers/ui-kit';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { PaneFormHeadComponent } from './pane-form-head.component';

describe('PaneFormHeadComponent', () => {
  it('shows the title, the subtitle and cancels', async () => {
    const closed = jest.fn();
    const { container } = await render(
      `<form aria-labelledby="f-t"><header class="ff__head" appPaneFormHead heading="Buchung bearbeiten" headingId="f-t" subtitle="Druckkosten" (closed)="closed()"></header></form>`,
      { imports: [PaneFormHeadComponent], componentProperties: { closed } },
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Buchung bearbeiten' })).toHaveAttribute('id', 'f-t');
    expect(screen.getByText('Druckkosten')).toHaveClass('pfh__subtitle');
    expect(container.querySelector('header.ff__head')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(closed).toHaveBeenCalledTimes(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows no subtitle line without a subtitle', async () => {
    const { container } = await render(`<header appPaneFormHead heading="Neu"></header>`, {
      imports: [PaneFormHeadComponent],
    });
    expect(container.querySelector('.pfh__subtitle')).toBeNull();
  });

  it('docks in the bar of the one-view layout and gives the task back when it ends', async () => {
    const nav = new ListDetailNav();
    nav.active.set(true);
    const closed = jest.fn();
    const { container, fixture } = await render(
      `<header appPaneFormHead heading="Buchung hinzufügen" headingId="f-t" (closed)="closed()"></header>`,
      { imports: [PaneFormHeadComponent], componentProperties: { closed }, providers: [{ provide: ListDetailNav, useValue: nav }] },
    );
    expect(container.querySelector('header')).toHaveClass('pfh--docked');
    expect(screen.queryByRole('button', { name: 'Abbrechen' })).toBeNull();
    expect(screen.getByRole('heading', { level: 2, name: 'Buchung hinzufügen' })).toBeInTheDocument();
    const task = nav.task();
    expect(task).toMatchObject({ title: 'Buchung hinzufügen', cancelLabel: 'Abbrechen' });
    task?.cancel();
    expect(closed).toHaveBeenCalledTimes(1);
    nav.active.set(false);
    fixture.detectChanges();
    expect(nav.task()).toBeNull();
    expect(screen.getByRole('button', { name: 'Abbrechen' })).toBeInTheDocument();
    nav.active.set(true);
    fixture.detectChanges();
    expect(nav.task()).not.toBeNull();
    fixture.destroy();
    expect(nav.task()).toBeNull();
  });

  it('shows the icon of a new thing before the title', async () => {
    const { container } = await render(`<header appPaneFormHead icon="repeat" heading="Umschichtung buchen"></header>`, {
      imports: [PaneFormHeadComponent],
    });
    const icon = container.querySelector('app-icon.pfh__icon');
    expect(icon).toBeTruthy();
    expect(icon?.nextElementSibling?.textContent).toContain('Umschichtung buchen');
  });
});

/**
 * Spec 001870 and 001871: the bar of a form that takes the place of a detail is the bar of
 * "Antrag bearbeiten", and the label of "Abbrechen" ends at the side inset of the icon.
 */
describe('FormBar', () => {
  const read = (path: string): string => readFileSync(join(__dirname, path), 'utf8');

  it('ends the pill of "Abbrechen" the 12px of its label closer to the edge', () => {
    const bar = read('../_form-bar.scss');
    expect(bar).toContain('$text-button-pad: var(--space-3);');
    expect(bar).toContain('padding-inline: $side calc(#{$side} - #{$text-button-pad});');
  });

  it('is the same bar for the pane forms and for "Antrag bearbeiten"', () => {
    expect(read('pane-form-head.component.scss')).toContain('@include fb.bar(var(--space-6));');
    const detail = read('../../../pages/applications/applications-detail.component.scss');
    expect(detail).toContain('@include fb.bar(var(--ad-gutter));');
    expect(detail).toMatch(/\.ad--split \.ad__editBar \{\s*--ad-gutter: var\(--space-6\);/);
  });
});
