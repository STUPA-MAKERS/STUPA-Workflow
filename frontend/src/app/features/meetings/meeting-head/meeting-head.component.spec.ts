import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { MEDIA } from '@stupa-makers/ui-kit';
import { MeetingHeadComponent } from './meeting-head.component';

describe('MeetingHeadComponent', () => {
  it('shows back, the title with its status and the sub line, then the page controls', async () => {
    const back = jest.fn();
    const { container } = await render(
      `<header appMeetingHead heading="12. Sitzung" statusKind="accent" statusText="Läuft" sub="Mo, 12.10. · Raum 3"
               (back)="back()"><button type="button">Menü</button></header>`,
      { imports: [MeetingHeadComponent], componentProperties: { back } },
    );
    const title = screen.getByRole('heading', { level: 1, name: '12. Sitzung' });
    expect(title).toHaveAttribute('title', '12. Sitzung');
    expect(screen.getByText('Läuft')).toBeInTheDocument();
    expect(screen.getByText('Mo, 12.10. · Raum 3')).toHaveClass('mh__sub');
    const header = container.querySelector('header')!;
    expect(header.lastElementChild).toHaveTextContent('Menü');
    await userEvent.click(screen.getByRole('button', { name: 'Zurück zu Sitzungen' }));
    expect(back).toHaveBeenCalledTimes(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('leaves the sub line out for null and keeps an empty one', async () => {
    const { container, rerender } = await render(
      `<header appMeetingHead heading="A" statusText="Geplant" [sub]="sub"></header>`,
      {
        imports: [MeetingHeadComponent],
        componentProperties: { sub: null as string | null },
      },
    );
    expect(container.querySelector('.mh__sub')).toBeNull();
    await rerender({ componentProperties: { sub: '' } });
    expect(container.querySelector('.mh__sub')).not.toBeNull();
  });

  it('is the sticky bar of the kit on a phone: back, title, status and sub line, the controls as actions', async () => {
    const real = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: query === MEDIA.phone,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia;
    try {
      const back = jest.fn();
      const { container } = await render(
        `<header appMeetingHead heading="12. Sitzung" statusKind="accent" statusText="Läuft" sub="seit 18:04"
                 (back)="back()"><button type="button">Menü</button></header>`,
        { imports: [MeetingHeadComponent], componentProperties: { back } },
      );
      await new Promise((r) => setTimeout(r));
      const bar = container.querySelector('app-list-detail-bar')!;
      expect(bar).toHaveClass('ld__bar--condensed');
      expect(bar.querySelector('.ld__barTitle')).toHaveTextContent('12. Sitzung');
      expect(bar.querySelector('.ld__barSub')).toHaveTextContent('Läuft·seit 18:04');
      expect(bar.querySelector('.ld__barActions')).toHaveTextContent('Menü');
      expect(screen.getByRole('heading', { level: 1, name: '12. Sitzung' })).toHaveClass('sr-only');
      expect(container.querySelector('.mh__titles')).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Zurück zu Sitzungen' }));
      expect(back).toHaveBeenCalledTimes(1);
    } finally {
      window.matchMedia = real;
    }
  });

  it('lets the page size the title and the status', () => {
    const scss = readFileSync(join(__dirname, 'meeting-head.component.scss'), 'utf8');
    expect(scss).toContain('font-size: var(--mh-title-size, var(--fs-h1))');
    expect(scss).toContain('line-height: var(--mh-title-line, 1.75rem)');
    expect(scss).toContain('font-size: var(--mh-status-size, var(--fs-body))');
  });
});
