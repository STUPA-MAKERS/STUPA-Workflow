import { Subject, of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import type { WebhookConfig, WebhookDeliveryStatus } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { WebhooksComponent } from './webhooks.component';

const SENT: WebhookDeliveryStatus = {
  webhookId: 'wh-1',
  lastState: 'sent',
  reasonClass: 'delivered',
  responseCode: 200,
  attempts: 1,
  lastAt: '2026-08-05T10:00:00Z',
};
const DEAD: WebhookDeliveryStatus = {
  webhookId: 'wh-2',
  lastState: 'dead',
  reasonClass: 'unreachable_or_blocked',
  responseCode: null,
  attempts: 5,
  lastAt: null,
};

interface Opts {
  /** Make the initial list fail, so the loading state has to end anyway. */
  listError?: boolean;
  saveError?: boolean;
  deleteError?: boolean;
  statusError?: boolean;
  status?: WebhookDeliveryStatus[];
  /** Front-end permission. `false` hides every mutating control. */
  can?: boolean;
}

async function setup(seed: WebhookConfig[] = [], opts: Opts = {}) {
  const saveWebhook = opts.saveError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn((h: WebhookConfig) => of({ ...h, id: h.id || 'wh-new' }));
  const deleteWebhook = opts.deleteError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn(() => of(void 0));
  const listWebhookDeliveryStatus = opts.statusError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn(() => of(opts.status ?? []));
  const api = {
    listWebhooks: opts.listError
      ? jest.fn(() => throwError(() => new Error('boom')))
      : jest.fn(() => of(seed)),
    saveWebhook,
    deleteWebhook,
    listWebhookDeliveryStatus,
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const auth = { can: jest.fn(() => opts.can !== false) };
  const view = await render(WebhooksComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
      { provide: AuthService, useValue: auth },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, saveWebhook, deleteWebhook, listWebhookDeliveryStatus, toast, auth, c };
}

const HOOKS: WebhookConfig[] = [
  { id: 'wh-1', name: 'A', url: 'https://a', events: [], active: true },
  { id: 'wh-2', name: 'B', url: 'https://b', events: [], active: true },
];

describe('WebhooksComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows an empty state with no webhooks', async () => {
    await setup();
    expect(screen.getByText('Keine Webhooks konfiguriert.')).toBeInTheDocument();
  });

  it('validates the URL but allows saving without any event (triggers optional)', async () => {
    const { saveWebhook } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Webhook hinzufügen' }));

    // An empty field is not yet wrong, but the save stays off.
    expect(screen.queryByText('Bitte eine gültige http(s)-URL angeben.')).not.toBeInTheDocument();
    const save = screen.getByRole('button', { name: 'Speichern' });
    expect(save).toBeDisabled();
    const url = screen.getByRole('textbox', { name: 'Ziel-URL' });
    await userEvent.type(url, 'ftp://x');
    expect(screen.getByText('Bitte eine gültige http(s)-URL angeben.')).toBeInTheDocument();

    // A valid URL is enough. The save works even without a single event.
    await userEvent.clear(url);
    await userEvent.type(url, 'https://hook.test');

    expect(save).toBeEnabled();
    await userEvent.click(save);
    expect(saveWebhook).toHaveBeenCalledTimes(1);
    expect(saveWebhook.mock.calls[0][0].events).toEqual([]);
  });

  it('edits an existing webhook via the dialog', async () => {
    const seed = [
      { id: 'wh-1', name: 'A', url: 'https://a', events: ['vote_opened' as const], active: true },
    ];
    const { c, saveWebhook } = await setup(seed);
    c.openEdit(0);
    expect(c.draft().url).toBe('https://a');
    c.toggleEvent('vote_opened');
    expect(c.draft().events).toEqual([]);
    c.toggleEvent('vote_closed');
    expect(c.draft().events).toEqual(['vote_closed']);
    // The edit leaves the original untouched until the save.
    expect(c.hooks()[0].events).toEqual(['vote_opened']);
    c.save();
    expect(saveWebhook).toHaveBeenCalledTimes(1);
    expect(c.hooks()[0].events).toEqual(['vote_closed']);
    expect(c.draft()).toBeNull(); // the dialog closes after the save
  });

  it('cancelling the dialog discards the draft', async () => {
    const { c, saveWebhook } = await setup();
    c.openAdd();
    c.patch('url', 'https://x');
    c.close();
    expect(c.draft()).toBeNull();
    expect(saveWebhook).not.toHaveBeenCalled();
  });

  it('replaces only the edited entry, leaving siblings untouched', async () => {
    const { c, saveWebhook } = await setup(HOOKS);
    c.openEdit(1); // edit the second hook, so index 0 stays as it is (else branch)
    c.patch('name', 'B2');
    c.save();
    expect(saveWebhook).toHaveBeenCalledTimes(1);
    expect(c.hooks()[0].name).toBe('A');
    expect(c.hooks()[1].name).toBe('B2');
  });

  it('appends a newly-saved webhook to the list on add', async () => {
    const { c, saveWebhook, toast } = await setup();
    c.openAdd();
    c.patch('name', 'New');
    c.patch('url', 'https://hook.test');
    c.save();
    expect(saveWebhook).toHaveBeenCalledTimes(1);
    expect(c.hooks().length).toBe(1);
    expect(c.hooks()[0].id).toBe('wh-new');
    expect(toast.success).toHaveBeenCalled();
    expect(c.draft()).toBeNull();
  });

  it('keeps the dialog open and toasts on a save failure', async () => {
    const { c, toast } = await setup([], { saveError: true });
    c.openAdd();
    c.patch('url', 'https://hook.test');
    c.save();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    // the draft stays, so the user can try again
    expect(c.draft()).not.toBeNull();
  });

  it('does not save when the URL is invalid (errors present)', async () => {
    const { c, saveWebhook } = await setup();
    c.openAdd();
    c.patch('url', 'ftp://nope'); // not http or https, so errors() is not empty
    expect(c.errors()).toContain('admin.webhook.badUrl');
    c.save();
    expect(saveWebhook).not.toHaveBeenCalled();
  });

  it('save is a no-op without a draft', async () => {
    const { c, saveWebhook } = await setup();
    c.save();
    expect(saveWebhook).not.toHaveBeenCalled();
  });

  it('errors() is empty when there is no draft', async () => {
    const { c } = await setup();
    expect(c.errors()).toEqual([]);
  });

  it('patch and toggleEvent are no-ops without a draft', async () => {
    const { c } = await setup();
    c.patch('name', 'x');
    expect(c.draft()).toBeNull();
    c.toggleEvent('vote_opened');
    expect(c.draft()).toBeNull();
  });

  it('tr() localises a translation key', async () => {
    const { c } = await setup();
    expect(c.tr('admin.common.actions')).toBe('Aktionen');
  });

  // --- delete ---------------------------------------------------------------

  it('deletes a webhook after the confirm dialog and drops its delivery state', async () => {
    const { c, deleteWebhook, toast } = await setup(HOOKS, { status: [SENT, DEAD] });
    c.askDelete(HOOKS[0]);
    expect(c.confirmDelete()).toEqual(HOOKS[0]);
    c.doDelete();
    expect(deleteWebhook).toHaveBeenCalledWith('wh-1');
    expect(c.hooks().map((h: WebhookConfig) => h.id)).toEqual(['wh-2']);
    expect(c.statusOf('wh-1')).toBeNull();
    expect(c.confirmDelete()).toBeNull();
    expect(toast.success).toHaveBeenCalledWith('Webhook gelöscht.');
  });

  it('renders a delete control that opens the confirm dialog', async () => {
    await setup(HOOKS);
    const remove = screen.getByRole('button', { name: 'Entfernen: A' });
    await userEvent.click(remove);
    expect(screen.getByText(/„A“ wird mit seiner Zustellhistorie gelöscht/)).toBeInTheDocument();
  });

  it('keeps the entry and toasts when the delete fails', async () => {
    const { c, toast } = await setup(HOOKS, { deleteError: true });
    c.askDelete(HOOKS[0]);
    c.doDelete();
    expect(c.hooks()).toHaveLength(2);
    expect(c.confirmDelete()).not.toBeNull();
    expect(toast.error).toHaveBeenCalledWith('Löschen fehlgeschlagen.');
  });

  it('doDelete is a no-op without a confirmed webhook', async () => {
    const { c, deleteWebhook } = await setup(HOOKS);
    c.doDelete();
    expect(deleteWebhook).not.toHaveBeenCalled();
  });

  // --- delivery status ------------------------------------------------------

  it('loads the delivery status once and shows a badge per row', async () => {
    const { c, listWebhookDeliveryStatus } = await setup(HOOKS, { status: [SENT, DEAD] });
    expect(listWebhookDeliveryStatus).toHaveBeenCalledTimes(1);
    expect(c.statusOf('wh-1')).toEqual(SENT);
    expect(screen.getByText('Zugestellt')).toBeInTheDocument();
    expect(screen.getByText('Fehlgeschlagen')).toBeInTheDocument();
  });

  it('shows a dash for a webhook without any delivery record', async () => {
    const { c } = await setup(HOOKS, { status: [SENT] });
    expect(c.statusOf('wh-2')).toBeNull();
  });

  it('opens the diagnosis dialog with the failure class, code and attempts', async () => {
    await setup(HOOKS, { status: [SENT, DEAD] });
    const toggle = screen.getAllByRole('button', { name: 'Zustellstatus' })[1];
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(
      screen.getByText('Das Ziel ist nicht erreichbar oder aus Sicherheitsgründen blockiert.'),
    ).toBeInTheDocument();
    // No HTTP response and no timestamp: both fall back to their placeholders.
    expect(screen.getByText('keine Antwort')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    // A dead letter explains that the retries are used up.
    expect(screen.getByText(/Dead-Letter/)).toBeInTheDocument();
  });

  it('renders the response code and the timestamp of a successful delivery', async () => {
    await setup(HOOKS, { status: [SENT] });
    await userEvent.click(screen.getAllByRole('button', { name: 'Zustellstatus' })[0]);
    expect(screen.getByText('200')).toBeInTheDocument();
    expect(screen.getByText('Erfolgreich zugestellt.')).toBeInTheDocument();
  });

  it('falls back to the hook URL and an empty-state text when no record exists', async () => {
    const { c, fixture } = await setup([{ ...HOOKS[0], name: '' }], { status: [] });
    // Without a name the card shows the URL as its title.
    expect(screen.getAllByText('https://a')).toHaveLength(2);
    c.toggleStatus(c.hooks()[0]);
    fixture.detectChanges();
    expect(c.statusDetail()).not.toBeNull();
    expect(screen.getByText('Für diesen Webhook liegt noch kein Zustellstatus vor.')).toBeInTheDocument();
    c.toggleStatus(c.hooks()[0]);
    expect(c.statusDetail()).toBeNull();
  });

  it('shows no state when the status request fails', async () => {
    const { c, toast } = await setup(HOOKS, { statusError: true });
    expect(c.statusOf('wh-1')).toBeNull();
    // The list itself stays usable, so no error toast fires.
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('maps every state to a status text', async () => {
    const { c } = await setup();
    expect(c.deliveryStatus('sent')).toEqual({ kind: 'accent', key: 'admin.webhook.delivery.state.sent' });
    expect(c.deliveryStatus('dead').kind).toBe('error');
    expect(c.deliveryStatus('pending').kind).toBe('neutral');
    expect(c.deliveryStatus('never').kind).toBe('neutral');
  });

  it('shows the real event keys of a hook, or the flow note without fixed events', async () => {
    await setup([
      { id: 'wh-1', name: 'A', url: 'https://a', events: ['status_changed', 'vote_closed'], active: true },
      { id: 'wh-2', name: 'B', url: 'https://b', events: [], active: false },
    ]);
    expect(screen.getByText('status_changed')).toBeInTheDocument();
    expect(screen.getByText('vote_closed')).toBeInTheDocument();
    expect(screen.getByText('Keine festen Ereignisse · Trigger aus dem Flow')).toBeInTheDocument();
  });

  it('saves the active switch at once and puts it back after a failure', async () => {
    const { c, saveWebhook } = await setup(HOOKS);
    await userEvent.click(screen.getByRole('switch', { name: 'Aktiv: A' }));
    expect(saveWebhook).toHaveBeenCalledWith(expect.objectContaining({ id: 'wh-1', active: false }));
    expect(c.hooks()[0].active).toBe(false);
    expect(c.toggling().size).toBe(0);
  });

  it('puts the active switch back after a failed save', async () => {
    const { c, toast } = await setup(HOOKS, { saveError: true });
    c.setActive(HOOKS[1], false);
    expect(c.hooks()[1].active).toBe(true);
    expect(c.toggling().size).toBe(0);
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
  });

  it('ignores a second toggle of the same webhook while its save runs', async () => {
    const { c, saveWebhook } = await setup(HOOKS);
    c.toggling.set(new Set(['wh-2']));
    c.setActive(HOOKS[1], false);
    expect(saveWebhook).not.toHaveBeenCalled();
  });

  it('saves a second webhook while the save of the first is pending', async () => {
    const { c, saveWebhook } = await setup(HOOKS);
    const pending = new Subject<WebhookConfig>();
    saveWebhook.mockImplementationOnce(() => pending);
    const a = screen.getByRole('switch', { name: 'Aktiv: A' });
    const b = screen.getByRole('switch', { name: 'Aktiv: B' });
    await userEvent.click(a);
    expect(c.isToggling('wh-1')).toBe(true);
    await userEvent.click(b);
    expect(saveWebhook).toHaveBeenCalledTimes(2);
    expect(saveWebhook).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'wh-2', active: false }));
    // Each switch shows the state that its webhook holds.
    expect(b).toHaveAttribute('aria-checked', String(c.hooks()[1].active));
    expect(b).toHaveAttribute('aria-checked', 'false');
    pending.next({ ...HOOKS[0], active: false });
    pending.complete();
    expect(c.toggling().size).toBe(0);
    expect(a).toHaveAttribute('aria-checked', String(c.hooks()[0].active));
  });

  it('shows "Noch nie" for a webhook created in this session', async () => {
    const { c, fixture } = await setup([], { status: [] });
    c.openAdd();
    c.patch('name', 'New');
    c.patch('url', 'https://hook.test');
    c.save();
    fixture.detectChanges();
    expect(c.statusOf('wh-new')).toEqual(
      expect.objectContaining({ lastState: 'never', reasonClass: 'no_deliveries', attempts: 0 }),
    );
    expect(screen.getByText('Noch nie')).toBeInTheDocument();
  });

  it('reads an unknown reason class back raw', async () => {
    const { c } = await setup();
    expect(c.reasonLabel('delivered')).toBe('Erfolgreich zugestellt.');
    expect(c.reasonLabel('brand_new_class')).toBe('brand_new_class');
  });

  // --- permission gating ----------------------------------------------------

  it('hides create, edit, delete and the status column without webhook.manage', async () => {
    const { c, listWebhookDeliveryStatus } = await setup(HOOKS, { can: false });
    expect(c.canManage()).toBe(false);
    // The diagnosis route needs the permission, so it is never called.
    expect(listWebhookDeliveryStatus).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Webhook hinzufügen' })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Bearbeiten/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Entfernen/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Zustellstatus' })).toBeNull();
    expect(screen.getByRole('switch', { name: 'Aktiv: A' })).toBeDisabled();
  });

  it('offers the delivery status with webhook.manage', async () => {
    await setup(HOOKS);
    expect(screen.getAllByRole('button', { name: 'Zustellstatus' })).toHaveLength(2);
  });

  it('stops loading when the list fails, rather than spinning forever', async () => {
    // Without this the table keeps its skeleton rows and never says anything went wrong.
    const { fixture } = await setup([], { listError: true });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((fixture.componentInstance as any).loading()).toBe(false);
  });
});
