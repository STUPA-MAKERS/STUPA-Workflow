import { Subject, of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import type { NotificationPreference } from '@core/api/models';
import { runAxe } from '../../../testing/a11y';
import { AccountNotificationsComponent } from './notifications.component';

const PREFS: NotificationPreference[] = [
  { kind: 'status_update', enabled: true },
  { kind: 'protocol', enabled: false },
];

async function setup(
  prefs: NotificationPreference[] = PREFS,
  save: jest.Mock = jest.fn((p: NotificationPreference[]) => of(p)),
) {
  const api = {
    listNotificationPreferences: jest.fn(() => of(prefs)),
    setNotificationPreferences: save,
  };
  const view = await render(AccountNotificationsComponent, {
    providers: [{ provide: ApiClient, useValue: api }],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api };
}

describe('AccountNotificationsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows one switch row per kind of the API, with label, hint and value', async () => {
    const { container } = await setup();
    const switches = screen.getAllByRole('switch');
    expect(switches).toHaveLength(2);
    expect(switches[0]).toHaveAccessibleName(
      'Status-Updates zu Anträgen Wenn sich der Status eines Antrags ändert, der dich betrifft.',
    );
    expect(switches.map((s) => s.getAttribute('aria-checked'))).toEqual(['true', 'false']);
    expect(screen.getByText('Protokolle')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says that login links always go out', async () => {
    await setup();
    expect(screen.getByText(/Login-Links werden immer zugestellt\./)).toBeInTheDocument();
  });

  it('shows no switch for the kinds that send no mail (vote, role_change)', async () => {
    await setup([
      { kind: 'status_update', enabled: true },
      { kind: 'vote', enabled: true },
      { kind: 'role_change', enabled: true },
    ]);
    expect(screen.getAllByRole('switch')).toHaveLength(1);
    expect(screen.queryByText('vote')).toBeNull();
    expect(screen.queryByText('role_change')).toBeNull();
  });

  it('saves the full set, the hidden kinds included, when a switch flips', async () => {
    const all: NotificationPreference[] = [...PREFS, { kind: 'vote', enabled: false }];
    const { api } = await setup(all);
    await userEvent.click(screen.getAllByRole('switch')[0]);
    expect(api.setNotificationPreferences).toHaveBeenCalledWith([
      { kind: 'status_update', enabled: false },
      { kind: 'protocol', enabled: false },
      { kind: 'vote', enabled: false },
    ]);
  });

  it('turns the switch back and shows an error when the save fails', async () => {
    // The PUT answers later, as over HTTP: the page renders the new state first.
    const answer = new Subject<NotificationPreference[]>();
    const save = jest.fn(() => answer.asObservable());
    const { fixture } = await setup(PREFS, save);
    await userEvent.click(screen.getAllByRole('switch')[0]);
    fixture.detectChanges();
    expect(screen.getAllByRole('switch')[0]).toHaveAttribute('aria-checked', 'false');
    answer.error(new Error('boom'));
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('Speichern fehlgeschlagen');
    expect(screen.getAllByRole('switch')[0]).toHaveAttribute('aria-checked', 'true');
  });

  it('runs one PUT at a time and sends the latest state when the running one ends', async () => {
    const answers: Subject<NotificationPreference[]>[] = [];
    const save = jest.fn(() => {
      const a = new Subject<NotificationPreference[]>();
      answers.push(a);
      return a.asObservable();
    });
    const { fixture } = await setup(PREFS, save);
    await userEvent.click(screen.getAllByRole('switch')[0]);
    await userEvent.click(screen.getAllByRole('switch')[1]);
    fixture.detectChanges();
    // The second switch shows at once, but waits for the first PUT.
    expect(save).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole('switch')[1]).toHaveAttribute('aria-checked', 'true');
    answers[0].next([
      { kind: 'status_update', enabled: false },
      { kind: 'protocol', enabled: false },
    ]);
    answers[0].complete();
    fixture.detectChanges();
    // The answer of the first PUT does not turn the second switch back.
    expect(screen.getAllByRole('switch')[1]).toHaveAttribute('aria-checked', 'true');
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith([
      { kind: 'status_update', enabled: false },
      { kind: 'protocol', enabled: true },
    ]);
  });

  it('goes back to the last confirmed state when a later PUT fails', async () => {
    const answers: Subject<NotificationPreference[]>[] = [];
    const save = jest.fn(() => {
      const a = new Subject<NotificationPreference[]>();
      answers.push(a);
      return a.asObservable();
    });
    const { fixture } = await setup(PREFS, save);
    await userEvent.click(screen.getAllByRole('switch')[0]);
    await userEvent.click(screen.getAllByRole('switch')[1]);
    answers[0].next([
      { kind: 'status_update', enabled: false },
      { kind: 'protocol', enabled: false },
    ]);
    answers[0].complete();
    answers[1].error(new Error('boom'));
    fixture.detectChanges();
    // The server holds the first change only, and the page shows the same.
    expect(screen.getAllByRole('switch').map((s) => s.getAttribute('aria-checked'))).toEqual([
      'false',
      'false',
    ]);
    expect(screen.getByRole('alert')).toHaveTextContent('Speichern fehlgeschlagen');
  });

  it('shows one line when the server sends no kind to switch', async () => {
    await setup([{ kind: 'vote', enabled: true }]);
    expect(screen.queryAllByRole('switch')).toHaveLength(0);
    expect(
      screen.getByText('Für dein Konto gibt es keine Benachrichtigungen zum Ausschalten.'),
    ).toBeInTheDocument();
  });

  it('shows an error when the switches cannot load', async () => {
    const api = {
      listNotificationPreferences: jest.fn(() => throwError(() => new Error('x'))),
      setNotificationPreferences: jest.fn(),
    };
    await render(AccountNotificationsComponent, {
      providers: [{ provide: ApiClient, useValue: api }],
    });
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Einstellungen konnten nicht geladen werden.',
    );
    expect(screen.queryAllByRole('switch')).toHaveLength(0);
  });

  it('falls back to the raw kind for a kind without a translation', async () => {
    await setup([{ kind: 'brand_new_kind', enabled: true }]);
    expect(screen.getByRole('switch')).toHaveAccessibleName('brand_new_kind');
  });
});
