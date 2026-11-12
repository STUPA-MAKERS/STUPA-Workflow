import { render, screen } from '@testing-library/angular';
import type { ExternalEntry } from '@core/api/calendar.service';
import { ExternalEntryComponent } from './external-entry.component';

const ENTRY: ExternalEntry = {
  id: 'x-1',
  title: 'Vorlesungsfreie Zeit',
  startsOn: '2026-12-24',
  endsOn: '2026-12-26',
  startTime: null,
  endTime: null,
  place: null,
  description: null,
  calendar: 'Hochschulkalender',
};

describe('ExternalEntryComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** § 000714: title, time and the name of the calendar; no place line without a place. */
  it('shows the span and the calendar of an all-day entry', async () => {
    await render(ExternalEntryComponent, { inputs: { open: true, entry: ENTRY } });
    const dialog = await screen.findByRole('dialog', { name: 'Vorlesungsfreie Zeit' });
    expect(dialog.textContent).toContain('Do, 24.12.2026 – Sa, 26.12.2026');
    expect(dialog.textContent).toContain('Hochschulkalender');
    expect(screen.queryByText('Ort')).toBeNull();
    expect(dialog.querySelector('.apv__desc')).toBeNull();
  });

  it('shows nothing without an entry', async () => {
    const view = await render(ExternalEntryComponent, { inputs: { open: true, entry: null } });
    expect(view.fixture.componentInstance.when()).toBe('');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
