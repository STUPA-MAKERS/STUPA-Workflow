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

  it('surfaces an error and clears busy when rotation fails', async () => {
    const rotateCalendar = jest.fn(() => throwError(() => new Error('nope')));
    const api = { myCalendar: jest.fn(() => of({ url: null })), rotateCalendar };
    const view = await render(AccountCalendarComponent, {
      providers: [{ provide: ApiClient, useValue: api }],
    });
    await view.fixture.whenStable();
    view.fixture.detectChanges();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    c.rotate();
    expect(rotateCalendar).toHaveBeenCalledTimes(1);
    expect(c.error()).toBe(true);
    expect(c.busy()).toBe(false);
  });

  it('updates the URL on a successful rotation', async () => {
    const { fixture, rotateCalendar } = await setup({ url: null });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.rotate();
    expect(rotateCalendar).toHaveBeenCalledTimes(1);
    expect(c.url()).toBe('https://x/api/calendar/NEW.ics');
    expect(c.busy()).toBe(false);
  });

  it('ignores a rotate while one is already in flight (busy guard)', async () => {
    const { fixture, rotateCalendar } = await setup({ url: 'https://x/api/calendar/TOK.ics' });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.busy.set(true);
    c.rotate();
    expect(rotateCalendar).not.toHaveBeenCalled();
  });

  it('does nothing on copy when there is no URL yet', async () => {
    const writeText = jest.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    const { fixture } = await setup({ url: null });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.copy();
    expect(writeText).not.toHaveBeenCalled();
  });

  it('marks copied=false when the clipboard write rejects', async () => {
    const writeText = jest.fn(() => Promise.reject(new Error('denied')));
    Object.assign(navigator, { clipboard: { writeText } });
    const { fixture } = await setup({ url: 'https://x/api/calendar/TOK.ics' });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.copy();
    await Promise.resolve();
    await Promise.resolve();
    expect(writeText).toHaveBeenCalledWith('https://x/api/calendar/TOK.ics');
    expect(c.copied()).toBe(false);
  });

  it('handles a missing clipboard API gracefully (optional chaining)', async () => {
    Object.assign(navigator, { clipboard: undefined });
    const { fixture } = await setup({ url: 'https://x/api/calendar/TOK.ics' });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(() => c.copy()).not.toThrow();
    expect(c.copied()).toBe(false);
  });
});
