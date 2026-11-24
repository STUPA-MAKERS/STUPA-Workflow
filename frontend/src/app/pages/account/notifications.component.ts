import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import type { Observable } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { NotificationPreference, PushDevice } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { PushDeviceService, type PushSupport } from '@core/pwa/push-device.service';
import {
  SettingsScreenComponent,
  type SettingsGroup,
  type SettingsNotice,
  type SettingsRow,
  type SettingsState,
} from '@stupa-makers/ui-kit/screens';
import { FeatureService, type FeatureKey } from '@core/features/feature.service';

/**
 * Kinds that the page never shows. No mail goes out for them: "vote" has no sender,
 * and "role_change" has no caller. The server catalogue does not list them any more; the
 * filter keeps an older server from showing a switch that does nothing.
 */
const HIDDEN_KINDS: ReadonlySet<string> = new Set(['vote', 'role_change']);

/**
 * Kinds that only reach the team that works on tickets. The page shows them only to a
 * person who works in a Bereich (`ticket.manage`, or the Gremium permission
 * `ticket.work`), because nobody else gets these mails.
 */
const TEAM_KINDS: ReadonlySet<string> = new Set(['ticket_created', 'ticket_message', 'ticket_assigned']);

/** The feature whose mails a kind switches; a kind without an entry has no feature. */
const KIND_FEATURE: ReadonlyMap<string, FeatureKey> = new Map<string, FeatureKey>([
  ['meeting', 'meetings'],
  ['delegation', 'meetings'],
  ['protocol', 'meetings'],
  ['ticket_created', 'tickets'],
  ['ticket_message', 'tickets'],
  ['ticket_answer', 'tickets'],
  ['ticket_assigned', 'tickets'],
  ['todo_assigned', 'todos'],
  ['todo_mentioned', 'todos'],
  ['todo_due', 'todos'],
  ['todo_board_added', 'todos'],
  ['poll_started', 'voting'],
  ['poll_reminder', 'voting'],
  ['appointment', 'calendar'],
]);

/** The key prefix of a push switch row and of a device row. */
const PUSH_PREFIX = 'push:';
const DEVICE_PREFIX = 'device:';
/** The key of the switch "Push auf diesem Gerät". */
const THIS_DEVICE = 'push-this-device';

/** The line under the device switch while this device cannot take push. */
const SUPPORT_HINT: Readonly<Record<PushSupport, TranslationKey | null>> = {
  ready: null,
  install: 'account.notifications.push.install',
  blocked: 'account.notifications.push.blocked',
  unsupported: null,
};

/**
 * One list of switches that saves at once, one PUT at a time.
 *
 * A switch that flips during a PUT shows at once, and one more PUT with the latest state
 * follows when the running one ends. When a save fails, every switch goes back to the last
 * state that the server confirmed and `failed` runs. Thus the page and the server always agree
 * after a save.
 */
class SwitchList {
  readonly items = signal<NotificationPreference[]>([]);
  /** The last state that the server sent or confirmed. A failed save goes back to it. */
  private confirmed: NotificationPreference[] = [];
  /** A PUT runs. */
  private saving = false;
  /** A switch flipped while a PUT ran: send the latest state when the PUT ends. */
  private dirty = false;

  constructor(
    private readonly put: (items: NotificationPreference[]) => Observable<NotificationPreference[]>,
    private readonly failed: () => void,
  ) {}

  /** Take the state that the server sent. */
  loaded(items: NotificationPreference[]): void {
    this.confirmed = items;
    this.items.set(items);
  }

  /** Flip one switch and save at once. The server returns the effective state. */
  toggle(kind: string, enabled: boolean): void {
    this.items.update((all) => all.map((p) => (p.kind === kind ? { ...p, enabled } : p)));
    this.save();
  }

  private save(): void {
    if (this.saving) {
      this.dirty = true;
      return;
    }
    this.saving = true;
    this.dirty = false;
    this.put(this.items()).subscribe({
      next: (saved) => {
        this.saving = false;
        this.confirmed = saved;
        if (this.dirty) this.save();
        else this.items.set(saved);
      },
      error: () => {
        this.saving = false;
        this.dirty = false;
        this.items.set(this.confirmed);
        this.failed();
      },
    });
  }
}

/**
 * Account page "Benachrichtigungen".
 *
 * One row per kind of the server catalogue: the label and a switch. The server sends the
 * effective value of each kind: most kinds are on by default, the team mails about applications
 * are off until switched on. The magic-link mails are essential and have no switch.
 *
 * With the feature push on and a device that can take push, the page adds the push groups
 * (§F/collaboration/notifications/002500-002502): the switch "Push auf diesem Gerät", the list
 * of the own devices with push, each removable, and a push switch per kind, which never changes
 * the mail switch of the kind. The browser asks for the permission only after the tap on the
 * device switch. A device that cannot take push now gets a disabled switch with the reason
 * (an iPhone without the app on the home screen, or notifications blocked in the browser); a
 * browser without push shows no push group.
 *
 * Every switch saves at once (see `SwitchList`). When a save fails, the switches go back to the
 * last state that the server confirmed and an error shows.
 */
@Component({
  selector: 'app-account-notifications',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SettingsScreenComponent, TranslatePipe],
  templateUrl: './notifications.component.html',
  styleUrl: './notifications.component.scss',
})
export class AccountNotificationsComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthService);
  private readonly features = inject(FeatureService);
  private readonly push = inject(PushDeviceService);

  readonly loading = signal(true);
  readonly error = signal<TranslationKey | null>(null);

  /** The mail switches; every kind the server sent, the hidden ones included. */
  private readonly mail = new SwitchList(
    (items) => this.api.setNotificationPreferences(items),
    () => this.error.set('account.notifications.saveError'),
  );
  /** The push switches of every kind. */
  private readonly pushKinds = new SwitchList(
    (items) => this.api.setPushPreferences(items),
    () => this.error.set('account.notifications.saveError'),
  );

  /** Whether this device can take push; `unsupported` hides every push group. */
  protected readonly support = signal<PushSupport>('unsupported');
  /** The own devices with push. */
  protected readonly devices = signal<PushDevice[]>([]);
  /** The endpoint of the subscription of this device, or null. */
  protected readonly endpoint = signal<string | null>(null);
  /** The device switch is busy: the browser asks, or the server stores. */
  protected readonly pushBusy = signal(false);
  /**
   * The state the device switch shows while it is busy. The switch goes back to the real
   * state afterwards, so a refused subscription turns the switch off again.
   */
  private readonly pushWanted = signal<boolean | null>(null);

  /** The push groups show: the feature is on and the browser has push. */
  protected readonly pushShown = computed(
    () => this.features.isOn('push') && this.support() !== 'unsupported',
  );

  /** The row of this device, when it has push. */
  private readonly thisDevice = computed(() => {
    const endpoint = this.endpoint();
    return endpoint ? this.devices().find((d) => d.endpoint === endpoint) : undefined;
  });

  /** The kinds that get a row. */
  readonly rows = computed(() => this.mail.items().filter((p) => this.shown(p.kind)));

  /** The push kinds that get a row: the same kinds as the mail rows. */
  private readonly pushRows = computed(() =>
    this.pushKinds.items().filter((p) => this.shown(p.kind)),
  );

  /** The state of the settings screen (§ui-kit:002244): six grey rows while it loads. */
  protected readonly screenState = computed<SettingsState>(() =>
    this.loading()
      ? { state: 'loading', skeleton: { variant: 'rows', count: 6 } }
      : { state: 'ready' },
  );

  /** The mail group, then the push groups when they show. */
  protected readonly groups = computed<SettingsGroup[]>(() => {
    const rows = this.rows();
    if (!rows.length) return [];
    const pushed = this.pushShown();
    const mail: SettingsGroup = {
      key: 'kinds',
      ...(pushed ? { label: this.i18n.translate('account.notifications.mail.title') } : {}),
      rows: rows.map((p) => this.switchRow(p.kind, p.kind, p.enabled)),
    };
    return pushed ? [mail, ...this.pushGroups()] : [mail];
  });

  /** A failed load or save, as a note under the head. */
  protected readonly notice = computed<SettingsNotice | null>(() => {
    const e = this.error();
    return e ? { kind: 'error', text: this.i18n.translate(e) } : null;
  });

  constructor() {
    this.api.listNotificationPreferences().subscribe({
      next: (p) => {
        this.mail.loaded(p);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('account.notifications.error');
        this.loading.set(false);
      },
    });
    this.loadPush();
  }

  /** A switch of the page flipped: this device, a push kind, or a mail kind. */
  toggle(key: string, enabled: boolean): void {
    this.error.set(null);
    if (key === THIS_DEVICE) {
      void this.switchDevice(enabled);
      return;
    }
    if (key.startsWith(PUSH_PREFIX)) {
      this.pushKinds.toggle(key.slice(PUSH_PREFIX.length), enabled);
      return;
    }
    this.mail.toggle(key, enabled);
  }

  /** A device row was confirmed: remove that device. */
  act(key: string): void {
    const device = this.devices().find((d) => `${DEVICE_PREFIX}${d.id}` === key);
    if (!device) return;
    this.error.set(null);
    void this.removeDevice(device);
  }

  /** Read the push state of the device and, when push shows, the devices and switches. */
  private loadPush(): void {
    const support = this.push.support();
    this.support.set(support);
    if (!this.features.isOn('push') || support === 'unsupported') return;
    void this.push.endpoint().then((e) => this.endpoint.set(e));
    this.api.listPushDevices().subscribe({ next: (d) => this.devices.set(d) });
    this.api.listPushPreferences().subscribe({ next: (p) => this.pushKinds.loaded(p) });
  }

  private async switchDevice(enabled: boolean): Promise<void> {
    this.pushBusy.set(true);
    this.pushWanted.set(enabled);
    try {
      if (enabled) {
        const device = await this.push.enable();
        this.endpoint.set(device.endpoint);
        this.devices.update((all) => [device, ...all.filter((d) => d.id !== device.id)]);
      } else {
        const device = this.thisDevice();
        await this.push.disable(device);
        this.endpoint.set(null);
        this.devices.update((all) => all.filter((d) => d.id !== device?.id));
      }
    } catch {
      this.error.set('account.notifications.push.error');
    } finally {
      this.support.set(this.push.support());
      this.pushWanted.set(null);
      this.pushBusy.set(false);
    }
  }

  private async removeDevice(device: PushDevice): Promise<void> {
    try {
      await (device.id === this.thisDevice()?.id
        ? this.push.disable(device)
        : new Promise<void>((resolve, reject) =>
            this.api.removePushDevice(device.id).subscribe({ next: resolve, error: reject }),
          ));
      this.endpoint.update((e) => (e === device.endpoint ? null : e));
      this.devices.update((all) => all.filter((d) => d.id !== device.id));
    } catch {
      this.error.set('account.notifications.saveError');
    }
  }

  /** The device switch, the device list (when there is a device) and the push kinds. */
  private pushGroups(): SettingsGroup[] {
    const support = this.support();
    const hint = SUPPORT_HINT[support];
    const on = !!this.thisDevice();
    const device: SettingsGroup = {
      key: 'push-device',
      label: this.i18n.translate('account.notifications.push.title'),
      rows: [
        {
          key: THIS_DEVICE,
          label: this.i18n.translate('account.notifications.push.thisDevice'),
          control: 'switch',
          value: this.pushWanted() ?? on,
          disabled: this.pushBusy() || (!on && support !== 'ready'),
          ...(hint ? { meta: this.i18n.translate(hint) } : {}),
        },
      ],
    };
    const devices = this.devices();
    if (!devices.length) return [device];
    return [
      device,
      {
        key: 'push-devices',
        label: this.i18n.translate('account.notifications.push.devices'),
        rows: devices.map((d) => this.deviceRow(d)),
      },
      {
        key: 'push-kinds',
        label: this.i18n.translate('account.notifications.push.kinds'),
        rows: this.pushRows().map((p) =>
          this.switchRow(`${PUSH_PREFIX}${p.kind}`, p.kind, p.enabled),
        ),
      },
    ];
  }

  private deviceRow(d: PushDevice): SettingsRow {
    const label = d.label || this.i18n.translate('account.notifications.push.device');
    const current = d.id === this.thisDevice()?.id;
    return {
      key: `${DEVICE_PREFIX}${d.id}`,
      label,
      ...(current ? { meta: this.i18n.translate('account.notifications.push.current') } : {}),
      control: 'action',
      action: {
        key: `${DEVICE_PREFIX}${d.id}`,
        label: this.i18n.translate('account.notifications.push.remove'),
        icon: 'trash',
        confirm: {
          title: this.i18n.translate('account.notifications.push.removeTitle', { device: label }),
          confirmLabel: this.i18n.translate('account.notifications.push.remove'),
        },
      },
    };
  }

  private switchRow(key: string, kind: string, value: boolean): SettingsRow {
    return { key, label: this.kindLabel(kind), control: 'switch', value };
  }

  /** A kind shows when it is not hidden, the person may get it and its feature is on. */
  private shown(kind: string): boolean {
    return !HIDDEN_KINDS.has(kind) && this.mayGet(kind) && this.featureOn(kind);
  }

  /** A kind of a feature that is off gets no row (spec 000758). */
  private featureOn(kind: string): boolean {
    const feature = KIND_FEATURE.get(kind);
    return feature === undefined || this.features.isOn(feature);
  }

  /** A team kind shows only to the holders of its permission. */
  private mayGet(kind: string): boolean {
    return !TEAM_KINDS.has(kind) || this.auth.worksOnTickets();
  }

  protected kindLabel(kind: string): string {
    return this.lookup(`account.notifications.kind.${kind}`, kind);
  }

  /** Translate a key. A new kind with no translation shows the fallback, not the key. */
  private lookup(key: string, fallback: string): string {
    const label = this.i18n.translate(key as TranslationKey);
    return label === key ? fallback : label;
  }
}
