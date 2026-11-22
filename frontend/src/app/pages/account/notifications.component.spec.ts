import { Subject, of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import type { NotificationPreference, PushDevice } from '@core/api/models';
import { PushDeviceService, type PushSupport } from '@core/pwa/push-device.service';
import { runAxe } from '../../../testing/a11y';
import { AccountNotificationsComponent } from './notifications.component';

const PREFS: NotificationPreference[] = [
  { kind: 'status_update', enabled: true },
  { kind: 'protocol', enabled: false },
];

async function setup(
  prefs: NotificationPreference[] = PREFS,
  save: jest.Mock = jest.fn((p: NotificationPreference[]) => of(p)),
  permissions: string[] = [],
  push: Partial<PushMock> = {},
) {
  const api = {
    listNotificationPreferences: jest.fn(() => of(prefs)),
    setNotificationPreferences: save,
    ...pushApi(push),
  };
  const auth = { can: (p: string) => permissions.includes(p) };
  const device = pushDevice(push);
  const view = await render(AccountNotificationsComponent, {
    providers: [
      { provide: ApiClient, useValue: api },
      { provide: AuthService, useValue: auth },
      { provide: PushDeviceService, useValue: device },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, device };
}

/** The push state of the test device and its server rows. */
interface PushMock {
  support: PushSupport;
  endpoint: string | null;
  devices: PushDevice[];
  prefs: NotificationPreference[];
  enable: jest.Mock;
  disable: jest.Mock;
  remove: jest.Mock;
  savePush: jest.Mock;
}

const PHONE: PushDevice = {
  id: 'd1',
  label: 'Safari · iPhone',
  endpoint: 'https://web.push.apple.com/a',
  createdAt: '2026-11-22T10:00:00Z',
  lastSuccessAt: null,
};
const LAPTOP: PushDevice = {
  id: 'd2',
  label: '',
  endpoint: 'https://fcm.googleapis.com/b',
  createdAt: '2026-11-21T10:00:00Z',
  lastSuccessAt: null,
};
const PUSH_PREFS: NotificationPreference[] = [
  { kind: 'status_update', enabled: false },
  { kind: 'protocol', enabled: true },
];

function pushApi(push: Partial<PushMock>) {
  return {
    listPushDevices: jest.fn(() => of(push.devices ?? [])),
    listPushPreferences: jest.fn(() => of(push.prefs ?? PUSH_PREFS)),
    setPushPreferences: push.savePush ?? jest.fn((p: NotificationPreference[]) => of(p)),
    removePushDevice: push.remove ?? jest.fn(() => of(undefined)),
  };
}

function pushDevice(push: Partial<PushMock>) {
  return {
    support: jest.fn(() => push.support ?? 'unsupported'),
    endpoint: jest.fn(() => Promise.resolve(push.endpoint ?? null)),
    enable: push.enable ?? jest.fn(() => Promise.resolve(PHONE)),
    disable: push.disable ?? jest.fn(() => Promise.resolve()),
  };
}

/** Let the promises of the device service settle, then render. */
async function settle(fixture: { detectChanges(): void; whenStable(): Promise<unknown> }) {
  await new Promise((r) => setTimeout(r, 0));
  await fixture.whenStable();
  fixture.detectChanges();
}

describe('AccountNotificationsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows one switch row per kind of the API, with label and value', async () => {
    const { container } = await setup();
    const switches = screen.getAllByRole('switch');
    expect(switches).toHaveLength(2);
    expect(switches[0]).toHaveAccessibleName('Status-Updates zu Anträgen');
    expect(switches.map((s) => s.getAttribute('aria-checked'))).toEqual(['true', 'false']);
    expect(screen.getByText('Protokolle')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
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

  /** The PUT answers later, as over HTTP, so the page renders the new state first. */
  it('turns the switch back and shows an error when the save fails', async () => {
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

  /**
   * The second switch shows at once, but waits for the first PUT. The answer of the first PUT does
   * not turn the second switch back.
   */
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
    expect(save).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole('switch')[1]).toHaveAttribute('aria-checked', 'true');
    answers[0].next([
      { kind: 'status_update', enabled: false },
      { kind: 'protocol', enabled: false },
    ]);
    answers[0].complete();
    fixture.detectChanges();
    expect(screen.getAllByRole('switch')[1]).toHaveAttribute('aria-checked', 'true');
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith([
      { kind: 'status_update', enabled: false },
      { kind: 'protocol', enabled: true },
    ]);
  });

  /** The server holds the first change only, and the page shows the same. */
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
      providers: [
        { provide: ApiClient, useValue: api },
        { provide: AuthService, useValue: { can: () => false } },
        { provide: PushDeviceService, useValue: pushDevice({}) },
      ],
    });
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Einstellungen konnten nicht geladen werden.',
    );
    expect(screen.queryAllByRole('switch')).toHaveLength(0);
  });

  it('shows the ticket mails of the team only to a holder of ticket.manage', async () => {
    const prefs: NotificationPreference[] = [
      { kind: 'ticket_created', enabled: true },
      { kind: 'ticket_message', enabled: true },
      { kind: 'ticket_answer', enabled: true },
    ];
    await setup(prefs);
    expect(screen.getAllByRole('switch')).toHaveLength(1);
    expect(screen.getByText('Antworten auf meine Tickets')).toBeInTheDocument();
    expect(screen.queryByText('Nachrichten zu Tickets')).toBeNull();
  });

  it('shows every ticket mail to the team', async () => {
    const prefs: NotificationPreference[] = [
      { kind: 'ticket_created', enabled: true },
      { kind: 'ticket_message', enabled: false },
      { kind: 'ticket_answer', enabled: true },
    ];
    const save = jest.fn((p: NotificationPreference[]) => of(p));
    await setup(prefs, save, ['ticket.manage']);
    expect(screen.getAllByRole('switch')).toHaveLength(3);
    expect(screen.getByText('Nachrichten zu Tickets')).toBeInTheDocument();
  });

  it('falls back to the raw kind for a kind without a translation', async () => {
    await setup([{ kind: 'brand_new_kind', enabled: true }]);
    expect(screen.getByRole('switch')).toHaveAccessibleName('brand_new_kind');
  });

  /** Spec 000758: a kind of a feature that is off has no switch. */
  it('shows no switch for the kinds of a feature that is off', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['meetings', 'todos']));
    await setup([
      { kind: 'status_update', enabled: true },
      { kind: 'protocol', enabled: true },
      { kind: 'todo_due', enabled: true },
      { kind: 'appointment', enabled: true },
    ]);
    localStorage.removeItem('ap.features.off');
    expect(screen.getAllByRole('switch')).toHaveLength(2);
    expect(screen.queryByText('Protokolle')).toBeNull();
  });

  describe('push (§F/collaboration/notifications/002500-002502)', () => {
    it('shows no push group and calls no push route on a browser without push', async () => {
      const { api } = await setup();
      expect(screen.queryByText('Per Push')).toBeNull();
      expect(screen.queryByText('Per Mail')).toBeNull();
      expect(api.listPushDevices).not.toHaveBeenCalled();
    });

    it('shows no push group while the feature push is off', async () => {
      localStorage.setItem('ap.features.off', JSON.stringify(['push']));
      const { api } = await setup(PREFS, undefined, [], { support: 'ready' });
      localStorage.removeItem('ap.features.off');
      expect(screen.queryByText('Push auf diesem Gerät')).toBeNull();
      expect(api.listPushDevices).not.toHaveBeenCalled();
    });

    it('shows only the device switch while no device has push', async () => {
      const { container, fixture } = await setup(PREFS, undefined, [], { support: 'ready' });
      await settle(fixture);
      expect(screen.getByText('Per Mail')).toBeInTheDocument();
      const device = screen.getByRole('switch', { name: 'Push auf diesem Gerät' });
      expect(device).toHaveAttribute('aria-checked', 'false');
      expect(device).not.toBeDisabled();
      expect(screen.queryByText('Per Push')).toBeNull();
      expect(await runAxe(container)).toHaveNoViolations();
    });

    it('turns push on for this device and then shows the devices and the push kinds', async () => {
      const { fixture, device } = await setup(PREFS, undefined, [], { support: 'ready' });
      await settle(fixture);
      await userEvent.click(screen.getByRole('switch', { name: 'Push auf diesem Gerät' }));
      await settle(fixture);
      expect(device.enable).toHaveBeenCalled();
      expect(screen.getByRole('switch', { name: 'Push auf diesem Gerät' })).toHaveAttribute(
        'aria-checked',
        'true',
      );
      expect(screen.getByText('Safari · iPhone')).toBeInTheDocument();
      expect(screen.getByText('Dieses Gerät')).toBeInTheDocument();
      expect(screen.getByText('Per Push')).toBeInTheDocument();
      expect(screen.getAllByRole('switch')).toHaveLength(5);
    });

    it('shows an error when the browser refuses the subscription', async () => {
      const enable = jest.fn(() => Promise.reject(new Error('denied')));
      const { fixture } = await setup(PREFS, undefined, [], { support: 'ready', enable });
      await settle(fixture);
      await userEvent.click(screen.getByRole('switch', { name: 'Push auf diesem Gerät' }));
      await settle(fixture);
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Push konnte nicht eingeschaltet werden.',
      );
      expect(screen.getByRole('switch', { name: 'Push auf diesem Gerät' })).toHaveAttribute(
        'aria-checked',
        'false',
      );
    });

    it('turns push off for this device and removes its row', async () => {
      const { fixture, device } = await setup(PREFS, undefined, [], {
        support: 'ready',
        endpoint: PHONE.endpoint,
        devices: [PHONE, LAPTOP],
      });
      await settle(fixture);
      await userEvent.click(screen.getByRole('switch', { name: 'Push auf diesem Gerät' }));
      await settle(fixture);
      expect(device.disable).toHaveBeenCalledWith(PHONE);
      expect(screen.queryByText('Safari · iPhone')).toBeNull();
      expect(screen.getByText('Gerät')).toBeInTheDocument();
    });

    it('saves a push switch without the mail switches', async () => {
      const savePush = jest.fn((p: NotificationPreference[]) => of(p));
      const { fixture, api } = await setup(PREFS, undefined, [], {
        support: 'ready',
        endpoint: PHONE.endpoint,
        devices: [PHONE],
        savePush,
      });
      await settle(fixture);
      const switches = screen.getAllByRole('switch', { name: 'Status-Updates zu Anträgen' });
      expect(switches).toHaveLength(2);
      await userEvent.click(switches[1]);
      expect(savePush).toHaveBeenCalledWith([
        { kind: 'status_update', enabled: true },
        { kind: 'protocol', enabled: true },
      ]);
      expect(api.setNotificationPreferences).not.toHaveBeenCalled();
    });

    it('removes another device through the API and this device through the browser', async () => {
      const { fixture, api, device } = await setup(PREFS, undefined, [], {
        support: 'ready',
        endpoint: PHONE.endpoint,
        devices: [PHONE, LAPTOP],
      });
      await settle(fixture);
      const page = fixture.componentInstance;
      page.act('device:d2');
      await settle(fixture);
      expect(api.removePushDevice).toHaveBeenCalledWith('d2');
      expect(screen.queryByText('Gerät')).toBeNull();
      page.act('device:d1');
      await settle(fixture);
      expect(device.disable).toHaveBeenCalledWith(PHONE);
      expect(screen.queryByText('Safari · iPhone')).toBeNull();
      page.act('device:unknown');
      expect(api.removePushDevice).toHaveBeenCalledTimes(1);
    });

    it('shows an error when a device cannot be removed', async () => {
      const remove = jest.fn(() => throwError(() => new Error('x')));
      const { fixture } = await setup(PREFS, undefined, [], {
        support: 'ready',
        devices: [LAPTOP],
        remove,
      });
      await settle(fixture);
      fixture.componentInstance.act('device:d2');
      await settle(fixture);
      expect(screen.getByRole('alert')).toHaveTextContent('Speichern fehlgeschlagen');
      expect(screen.getByText('Gerät')).toBeInTheDocument();
    });

    it.each([
      ['install', 'Nur in der App vom Home-Bildschirm'],
      ['blocked', 'Im Browser blockiert'],
    ] as const)(
      'disables the device switch with a reason when support is %s',
      async (support, text) => {
        const { fixture } = await setup(PREFS, undefined, [], { support });
        await settle(fixture);
        expect(screen.getByRole('switch', { name: 'Push auf diesem Gerät' })).toBeDisabled();
        expect(screen.getByText(new RegExp(text))).toBeInTheDocument();
      },
    );
  });
});
