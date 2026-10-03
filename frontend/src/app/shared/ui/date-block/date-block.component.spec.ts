import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import { I18nService } from '@core/i18n/i18n.service';
import { runAxe } from '../../../../testing/a11y';
import { DateBlockComponent } from './date-block.component';

describe('DateBlockComponent', () => {
  it('shows the day and the short month in capitals', async () => {
    const { container } = await render(DateBlockComponent, {
      inputs: { date: new Date(2026, 8, 29, 18, 4) },
    });
    expect(container.querySelector('.db__day')).toHaveTextContent('29');
    expect(container.querySelector('.db__month')).toHaveTextContent('SEP');
  });

  it.each([
    [new Date(2026, 9, 2), '02', 'OKT'],
    [new Date(2026, 2, 5), '05', 'MÄR'],
    [new Date(2026, 4, 20), '20', 'MAI'],
  ])('writes %s as %s %s', async (date, day, month) => {
    const { container } = await render(DateBlockComponent, { inputs: { date } });
    expect(container.querySelector('.db__day')).toHaveTextContent(day);
    expect(container.querySelector('.db__month')).toHaveTextContent(month);
  });

  it('reads an ISO string in local time', async () => {
    const iso = new Date(2026, 9, 13, 18, 0).toISOString();
    const { container } = await render(DateBlockComponent, { inputs: { date: iso } });
    expect(container.querySelector('.db__day')).toHaveTextContent('13');
    expect(container.querySelector('time')).toHaveAttribute('datetime', iso);
  });

  it('gives a screen reader the full date instead of the two parts', async () => {
    const { container } = await render(DateBlockComponent, {
      inputs: { date: new Date(2026, 8, 29) },
    });
    expect(screen.getByText('Dienstag, 29. September 2026')).toHaveClass('sr-only');
    expect(container.querySelectorAll('[aria-hidden="true"]')).toHaveLength(2);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('fills the block with the accent for a live meeting', async () => {
    const view = await render(DateBlockComponent, {
      inputs: { date: new Date(2026, 8, 29), live: true },
    });
    expect(view.fixture.nativeElement).toHaveClass('db--live');
  });

  it('follows the locale', async () => {
    const view = await render(DateBlockComponent, { inputs: { date: new Date(2026, 9, 2) } });
    const i18n = TestBed.inject(I18nService);
    i18n.setLocale('en');
    view.fixture.detectChanges();
    expect(view.container.querySelector('.db__month')).toHaveTextContent('OCT');
    i18n.setLocale('de');
  });
});
