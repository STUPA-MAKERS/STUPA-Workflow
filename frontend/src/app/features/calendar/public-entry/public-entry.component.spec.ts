import { Router, provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { PublicAppointment, PublicMeeting } from '@core/api/calendar.service';
import { runAxe } from '../../../../testing/a11y';
import { PublicEntryComponent } from './public-entry.component';
import type { PublicEntry } from './public-entry.component';

const TERMIN: PublicAppointment = {
  id: 'a-7',
  title: 'Vollversammlung',
  startsOn: '2026-11-18',
  endsOn: '2026-11-18',
  startTime: '14:00:00',
  endTime: '16:00:00',
  place: 'Aula',
  description: 'Alle Studierenden sind eingeladen.',
};
const MEETING: PublicMeeting = {
  id: 'm-35',
  title: '35. Sitzung',
  day: '2026-11-12',
  startTime: '18:00:00',
  endTime: '20:00:00',
  gremium: 'Studierendenparlament',
  tops: ['Begrüßung', 'Haushalt 2027'],
  protocolId: 'p-35',
};

async function setup(entry: PublicEntry | null, open = true) {
  localStorage.setItem('ap.locale', 'de');
  const on = { closed: jest.fn() };
  const view = await render(PublicEntryComponent, {
    inputs: { open, entry },
    on,
    providers: [provideRouter([{ path: '**', children: [] }])],
  });
  return { ...view, on, router: view.fixture.debugElement.injector.get(Router) };
}

describe('PublicEntryComponent', () => {
  afterEach(() => localStorage.clear());

  /** § 000730: a public Termin shows its time, its place and its description, and no person. */
  it('shows the time, the place and the description of a Termin', async () => {
    const view = await setup({ kind: 'appointment', data: TERMIN });
    const dialog = screen.getByRole('dialog', { name: 'Vollversammlung' });
    expect(within(dialog).getByText('Mi, 18.11.2026 · 14:00 – 16:00')).toBeInTheDocument();
    expect(within(dialog).getByText('Aula')).toBeInTheDocument();
    expect(within(dialog).getByText('Alle Studierenden sind eingeladen.')).toBeInTheDocument();
    expect(within(dialog).queryByText('Tagesordnung')).toBeNull();
    expect(within(dialog).queryByRole('button', { name: 'Protokoll ansehen' })).toBeNull();
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('leaves out the place and the description that a Termin does not have', async () => {
    await setup({ kind: 'appointment', data: { ...TERMIN, startTime: null, endTime: null, place: null, description: null } });
    const dialog = screen.getByRole('dialog', { name: 'Vollversammlung' });
    expect(within(dialog).queryByText('Ort')).toBeNull();
    expect(dialog.querySelector('.apv__desc')).toBeNull();
  });

  /** § 000731: a public meeting shows its Gremium, its public TOPs and the link to its protocol. */
  it('shows the Gremium and the TOPs of a meeting and opens its public protocol', async () => {
    const view = await setup({ kind: 'meeting', data: MEETING });
    const dialog = screen.getByRole('dialog', { name: '35. Sitzung' });
    expect(within(dialog).getByText('Do, 12.11.2026 · 18:00 – 20:00')).toBeInTheDocument();
    expect(within(dialog).getByText('Studierendenparlament')).toBeInTheDocument();
    expect(within(dialog).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Begrüßung', 'Haushalt 2027']);
    expect(await runAxe(view.container)).toHaveNoViolations();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Protokoll ansehen' }));
    await view.fixture.whenStable();
    expect(view.on.closed).toHaveBeenCalled();
    expect(view.router.url).toBe('/protocols/p-35');
  });

  it('shows no agenda and no link for a meeting without TOPs and without a protocol', async () => {
    await setup({ kind: 'meeting', data: { ...MEETING, tops: [], protocolId: null } });
    const dialog = screen.getByRole('dialog', { name: '35. Sitzung' });
    expect(within(dialog).queryByText('Tagesordnung')).toBeNull();
    expect(within(dialog).queryByRole('button', { name: 'Protokoll ansehen' })).toBeNull();
  });

  it('shows nothing without an entry', async () => {
    const view = await setup(null);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(view.fixture.componentInstance.title()).toBe('');
    expect(view.fixture.componentInstance.when()).toBe('');
  });
});
