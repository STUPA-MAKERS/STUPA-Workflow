import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { DateRangeComponent, type DateRange } from './date-range.component';

describe('DateRangeComponent', () => {
  it('renders start and end (localized) inputs under the labels', async () => {
    await render(`<app-date-range legend="Zeitraum" startLabel="Von" endLabel="Bis" />`, {
      imports: [DateRangeComponent],
    });
    expect((screen.getByLabelText('Von') as HTMLInputElement).type).toBe('text');
    expect((screen.getByLabelText('Bis') as HTMLInputElement).type).toBe('text');
  });

  it('writes a model range into both controls (localized display)', async () => {
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
    await fixture.whenStable();
    fixture.detectChanges();
    expect((screen.getByLabelText('Von') as HTMLInputElement).value).toBe('01.01.2026');
    expect((screen.getByLabelText('Bis') as HTMLInputElement).value).toBe('31.03.2026');
  });

  it('emits the ISO start when a localized date is typed', async () => {
    @Component({
      standalone: true,
      imports: [DateRangeComponent, FormsModule],
      template: `<app-date-range startLabel="Von" endLabel="Bis" [(ngModel)]="range" />`,
    })
    class Host {
      range: DateRange = { start: '', end: '' };
    }
    const { fixture } = await render(Host);
    await userEvent.type(screen.getByLabelText('Von'), '10.05.2026');
    await userEvent.tab(); // blur → commit
    expect(fixture.componentInstance.range.start).toBe('2026-05-10');
  });
});
