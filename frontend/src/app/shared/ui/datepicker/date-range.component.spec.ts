import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { DateRangeComponent, type DateRange } from './date-range.component';

describe('DateRangeComponent', () => {
  it('renders start and end date inputs under the labels', async () => {
    await render(`<app-date-range legend="Zeitraum" startLabel="Von" endLabel="Bis" />`, {
      imports: [DateRangeComponent],
    });
    expect((screen.getByLabelText('Von') as HTMLInputElement).type).toBe('date');
    expect((screen.getByLabelText('Bis') as HTMLInputElement).type).toBe('date');
  });

  it('writes a model range into both controls', async () => {
    @Component({
      standalone: true,
      imports: [DateRangeComponent, FormsModule],
      template: `<app-date-range startLabel="Von" endLabel="Bis" [(ngModel)]="range" />`,
    })
    class Host {
      range: DateRange = { start: '2026-01-01', end: '2026-03-31' };
    }
    const { fixture } = await render(Host);
    await fixture.whenStable();
    fixture.detectChanges();
    expect((screen.getByLabelText('Von') as HTMLInputElement).value).toBe('2026-01-01');
    expect((screen.getByLabelText('Bis') as HTMLInputElement).value).toBe('2026-03-31');
  });

  it('couples the bounds so end cannot precede start', async () => {
    @Component({
      standalone: true,
      imports: [DateRangeComponent, FormsModule],
      template: `<app-date-range startLabel="Von" endLabel="Bis" [(ngModel)]="range" />`,
    })
    class Host {
      range: DateRange = { start: '', end: '' };
    }
    const { fixture } = await render(Host);
    await userEvent.type(screen.getByLabelText('Von'), '2026-05-10');
    fixture.detectChanges();
    expect(screen.getByLabelText('Bis')).toHaveAttribute('min', '2026-05-10');
    expect(fixture.componentInstance.range.start).toBe('2026-05-10');
  });
});
