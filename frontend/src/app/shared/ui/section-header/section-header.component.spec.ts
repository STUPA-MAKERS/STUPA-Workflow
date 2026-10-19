import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { SectionHeaderComponent } from './section-header.component';

describe('SectionHeaderComponent', () => {
  it('names the section with a level-2 title and shows the count', async () => {
    const { container } = await render(
      `<section aria-labelledby="t1"><app-section-header headingId="t1" heading="Aktive Vertretungen" [count]="3" /></section>`,
      { imports: [SectionHeaderComponent] },
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Aktive Vertretungen' })).toHaveAttribute('id', 't1');
    expect(screen.getByRole('region', { name: 'Aktive Vertretungen' })).toBeInTheDocument();
    expect(container.querySelector('.sh__count')).toHaveTextContent('3');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('takes level 3 and puts the actions at the end', async () => {
    await render(
      `<app-section-header [level]="3" heading="Rechte"><button type="button">Neu</button></app-section-header>`,
      { imports: [SectionHeaderComponent] },
    );
    expect(screen.getByRole('heading', { level: 3, name: 'Rechte' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Neu' }).closest('.sh__end')).toBeTruthy();
  });

  it('shows only the actions without a heading, and no count without one', async () => {
    const { container } = await render(
      `<app-section-header><button type="button">Neu</button></app-section-header>`,
      { imports: [SectionHeaderComponent] },
    );
    expect(screen.queryByRole('heading')).toBeNull();
    expect(container.querySelector('.sh__count')).toBeNull();
  });

  it('shows a count of zero', async () => {
    const { container } = await render(`<app-section-header heading="X" [count]="0" />`, {
      imports: [SectionHeaderComponent],
    });
    expect(container.querySelector('.sh__count')).toHaveTextContent('0');
  });

  it('lets the page set the geometry through custom properties', () => {
    const scss = readFileSync(join(__dirname, 'section-header.component.scss'), 'utf8');
    for (const prop of ['--sh-align', '--sh-wrap', '--sh-gap', '--sh-min-height', '--sh-inset', '--sh-title-inset']) {
      expect(scss).toContain(`var(${prop},`);
    }
  });
});
