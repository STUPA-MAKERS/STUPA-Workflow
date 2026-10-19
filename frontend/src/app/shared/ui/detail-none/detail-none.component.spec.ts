import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { DetailNoneComponent } from './detail-none.component';

describe('DetailNoneComponent', () => {
  it('asks to pick a row, on the sheet of an open row', async () => {
    const { container } = await render(
      `<app-detail-none icon="vote" heading="Wähle eine Abstimmung aus." body="Sie öffnet sich hier." />`,
      { imports: [DetailNoneComponent] },
    );
    expect(screen.getByText('Wähle eine Abstimmung aus.')).toBeInTheDocument();
    expect(screen.getByText('Sie öffnet sich hier.')).toBeInTheDocument();
    const host = container.querySelector('app-detail-none');
    expect(host).toHaveClass('dn--sheet');
    expect(host).toHaveClass('dn--inset');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the text of an empty list with its own icon', async () => {
    const { container } = await render(
      `<app-detail-none state="empty" icon="tasks" emptyIcon="check" heading="Wähle" emptyHeading="Keine Aufgaben" emptyBody="Alles erledigt." />`,
      { imports: [DetailNoneComponent] },
    );
    expect(screen.getByText('Keine Aufgaben')).toBeInTheDocument();
    expect(screen.getByText('Alles erledigt.')).toBeInTheDocument();
    expect(screen.queryByText('Wähle')).toBeNull();
    expect(container.querySelector('app-empty-state')).toBeTruthy();
  });

  it('shows nothing while the list loads', async () => {
    const { container } = await render(`<app-detail-none state="busy" heading="Wähle" />`, {
      imports: [DetailNoneComponent],
    });
    expect(container.querySelector('app-empty-state')).toBeNull();
    expect(container.querySelector('app-detail-none')).toHaveClass('dn--sheet');
  });

  it('has no sheet when flat, and no padding without inset', async () => {
    const { container } = await render(
      `<app-detail-none surface="flat" heading="a" /><app-detail-none [inset]="false" heading="b" />`,
      { imports: [DetailNoneComponent] },
    );
    const [flat, bare] = Array.from(container.querySelectorAll('app-detail-none'));
    expect(flat).not.toHaveClass('dn--sheet');
    expect(bare).toHaveClass('dn--sheet');
    expect(bare).not.toHaveClass('dn--inset');
  });

  it('shows hidden bars in the shape of a sheet as a ghost', async () => {
    const { container } = await render(`<app-detail-none [ghost]="true" heading="x" />`, {
      imports: [DetailNoneComponent],
    });
    expect(container.querySelector('.dn__ghost')).toHaveAttribute('aria-hidden', 'true');
    expect(container.querySelectorAll('.dn__bar--card')).toHaveLength(2);
    expect(screen.queryByText('x')).toBeNull();
  });
});
