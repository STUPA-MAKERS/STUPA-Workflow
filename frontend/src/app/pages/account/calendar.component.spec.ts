import { of, throwError } from 'rxjs';
import { render, screen, fireEvent } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import { AccountCalendarComponent } from './calendar.component';

async function setup(opts: { url?: string | null } = {}) {
  const rotateCalendar = jest.fn(() => of({ url: 'https://x/api/calendar/NEW.ics' }));
  const api = {
    myCalendar: jest.fn(() => of({ url: opts.url ?? null })),
    rotateCalendar,
  };
  const view = await render(AccountCalendarComponent, {
    providers: [{ provide: ApiClient, useValue: api }],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, rotateCalendar };
}

describe('AccountCalendarComponent (#ics)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the feed URL when one exists', async () => {
    await setup({ url: 'https://x/api/calendar/TOK.ics' });
    expect(screen.getByDisplayValue('https://x/api/calendar/TOK.ics')).toBeInTheDocument();
  });

  it('offers to generate a link when none exists and rotates on click', async () => {
    const { rotateCalendar } = await setup({ url: null });
    fireEvent.click(screen.getByText('Abo-Link erzeugen'));
    expect(rotateCalendar).toHaveBeenCalled();
  });

  it('copies the URL to the clipboard', async () => {
    const writeText = jest.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    await setup({ url: 'https://x/api/calendar/TOK.ics' });
    fireEvent.click(screen.getByText('Kopieren'));
    expect(writeText).toHaveBeenCalledWith('https://x/api/calendar/TOK.ics');
  });

  it('shows an error when the feed cannot be loaded', async () => {
    const api = {
      myCalendar: jest.fn(() => throwError(() => new Error('boom'))),
      rotateCalendar: jest.fn(),
    };
    await render(AccountCalendarComponent, {
      providers: [{ provide: ApiClient, useValue: api }],
    });
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});
