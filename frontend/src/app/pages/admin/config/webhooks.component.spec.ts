import { of, throwError } from 'rxjs';
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

    expect(screen.getByText('Bitte eine gültige http(s)-URL angeben.')).toBeInTheDocument();
    const save = screen.getByRole('button', { name: 'Speichern' });
    expect(save).toBeDisabled();

    // A valid URL is enough. The save works even without a single event.
    await userEvent.type(screen.getByRole('textbox', { name: 'Ziel-URL' }), 'https://hook.test');

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
    const remove = screen.getAllByRole('button', { name: 'Entfernen' })[0];
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
    await userEvent.click(screen.getAllByRole('button', { name: 'Zustellstatus anzeigen' })[1]);
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
    await userEvent.click(screen.getByRole('button', { name: 'Zustellstatus anzeigen' }));
    expect(screen.getByText('200')).toBeInTheDocument();
    expect(screen.getByText('Erfolgreich zugestellt.')).toBeInTheDocument();
  });

  it('falls back to the hook URL and an empty-state text when no record exists', async () => {
    const { c } = await setup(HOOKS, { status: [] });
    c.openStatus({ ...HOOKS[0], name: '' });
    await Promise.resolve();
    expect(c.statusDetail()).not.toBeNull();
    c.closeStatus();
    expect(c.statusDetail()).toBeNull();
  });

  it('shows no state when the status request fails', async () => {
    const { c, toast } = await setup(HOOKS, { statusError: true });
    expect(c.statusOf('wh-1')).toBeNull();
    // The list itself stays usable, so no error toast fires.
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('maps every state to a badge variant and falls back for an unknown one', async () => {
    const { c } = await setup();
    expect(c.stateVariant('sent')).toBe('success');
    expect(c.stateVariant('dead')).toBe('danger');
    expect(c.stateVariant('pending')).toBe('info');
    expect(c.stateVariant('never')).toBe('neutral');
    expect(c.stateVariant('from_a_newer_backend')).toBe('neutral');
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
    expect(c.columns().map((col: { key: string }) => col.key)).toEqual([
      'name',
      'url',
      'events',
      'active',
      'actions',
    ]);
    expect(screen.queryByRole('button', { name: 'Webhook hinzufügen' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Bearbeiten' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Entfernen' })).toBeNull();
  });

  it('adds the delivery column with webhook.manage', async () => {
    const { c } = await setup(HOOKS);
    expect(c.columns().map((col: { key: string }) => col.key)).toEqual([
      'name',
      'url',
      'events',
      'active',
      'delivery',
      'actions',
    ]);
  });

  it('stops loading when the list fails, rather than spinning forever', async () => {
    // Without this the table keeps its skeleton rows and never says anything went wrong.
    const { fixture } = await setup([], { listError: true });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((fixture.componentInstance as any).loading()).toBe(false);
  });
});
