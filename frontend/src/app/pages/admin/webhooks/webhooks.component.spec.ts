import { Subject, of, throwError, type Observable } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import type { WebhookCatalogEvent, WebhookConfig, WebhookDeliveryStatus } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { WebhooksComponent, previewBody, withSubscription } from './webhooks.component';
import { loadErrorToast, retryLoadError, toastWith } from '../../../../testing/load-error';

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

const NO_FILTER = { subscriptions: [], gremiumIds: [], typeIds: [], stateKeys: [] };

const CATALOG: WebhookCatalogEvent[] = [
  {
    name: 'application.transition',
    group: 'applications',
    idKeys: ['applicationId', 'transitionId', 'statusEventId'],
    fields: [
      { key: 'title', personal: false, example: 'Zuschuss Sommerfest' },
      { key: 'applicantEmail', personal: true, example: 'erika@example.org' },
    ],
  },
  {
    name: 'vote.closed',
    group: 'votes',
    idKeys: ['voteId'],
    fields: [{ key: 'result', personal: false, example: 'passed' }],
  },
];

interface Opts {
  /** Make the initial list fail, so the loading state has to end anyway. */
  listError?: boolean;
  saveError?: boolean;
  deleteError?: boolean;
  statusError?: boolean;
  status?: WebhookDeliveryStatus[];
  /** Front-end permission. `false` hides every mutating control. */
  can?: boolean;
  /** Make the reads of the catalog and the filter choices fail. */
  choicesError?: boolean;
  testError?: boolean;
}

async function setup(seed: WebhookConfig[] = [], opts: Opts = {}) {
  const saveWebhook = opts.saveError
    ? jest.fn((_h: WebhookConfig): Observable<WebhookConfig> => throwError(() => new Error('boom')))
    : jest.fn((h: WebhookConfig): Observable<WebhookConfig> => of({ ...h, id: h.id || 'wh-new' }));
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
    getWebhookCatalog: jest.fn(() =>
      opts.choicesError ? throwError(() => new Error('x')) : of(CATALOG),
    ),
    listGremienOptions: jest.fn(() =>
      opts.choicesError ? throwError(() => new Error('x')) : of([{ id: 'g1', name: 'StuPa' }]),
    ),
    listApplicationTypes: jest.fn(() =>
      opts.choicesError
        ? throwError(() => new Error('x'))
        : of([{ id: 't1', name: 'Finanzantrag' }]),
    ),
    getGlobalFlow: jest.fn(() =>
      opts.choicesError
        ? throwError(() => new Error('x'))
        : of({ states: [{ key: 'approved', label: { de: 'Genehmigt' } }] }),
    ),
    sendWebhookTest: jest.fn(() =>
      opts.testError ? throwError(() => new Error('x')) : of({ deliveryId: 'd1' }),
    ),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const auth = { can: jest.fn(() => opts.can !== false) };
  const view = await render(WebhooksComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useFactory: () => toastWith(toast) },
      { provide: AuthService, useValue: auth },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, saveWebhook, deleteWebhook, listWebhookDeliveryStatus, toast, auth, c };
}

const HOOKS: WebhookConfig[] = [
  { id: 'wh-1', name: 'A', url: 'https://a', active: true, ...NO_FILTER },
  { id: 'wh-2', name: 'B', url: 'https://b', active: true, ...NO_FILTER },
];

describe('WebhooksComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows an empty state with no webhooks', async () => {
    await setup();
    expect(screen.getByText('Keine Webhooks konfiguriert.')).toBeInTheDocument();
  });

  /**
   * An empty field is not yet wrong, but the save stays off. A name and a valid URL are enough.
   * A new webhook subscribes to no event until one is checked.
   */
  it('validates the URL and saves a webhook without a subscription', async () => {
    const { saveWebhook } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Webhook anlegen' }));

    expect(screen.queryByText('Bitte eine gültige http(s)-URL angeben.')).not.toBeInTheDocument();
    const save = screen.getByRole('button', { name: 'Speichern' });
    expect(save).toBeDisabled();
    const url = screen.getByRole('textbox', { name: 'Ziel-URL' });
    await userEvent.type(url, 'ftp://x');
    expect(screen.getByText('Bitte eine gültige http(s)-URL angeben.')).toBeInTheDocument();

    await userEvent.clear(url);
    await userEvent.type(url, 'https://hook.test');
    // §NF/usability/controls/002582: the save also needs a name.
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByRole('textbox', { name: /^Name/ }), 'Hook');

    expect(save).toBeEnabled();
    await userEvent.click(save);
    expect(saveWebhook).toHaveBeenCalledTimes(1);
    expect(saveWebhook.mock.calls[0][0].subscriptions).toEqual([]);
  });

  /**
   * The edit leaves the original untouched until the save, and the dialog closes after the save.
   */
  it('edits an existing webhook via the dialog', async () => {
    const seed = [{ id: 'wh-1', name: 'A', url: 'https://a', active: true, ...NO_FILTER }];
    const { c, saveWebhook } = await setup(seed);
    c.openEdit(0);
    expect(c.draft().url).toBe('https://a');
    c.patch('name', 'B');
    expect(c.draft().name).toBe('B');
    expect(c.hooks()[0].name).toBe('A');
    c.save();
    expect(saveWebhook).toHaveBeenCalledTimes(1);
    expect(c.hooks()[0].name).toBe('B');
    expect(c.draft()).toBeNull();
  });

  it('cancelling the dialog discards the draft', async () => {
    const { c, saveWebhook } = await setup();
    c.openAdd();
    c.patch('url', 'https://x');
    c.close();
    expect(c.draft()).toBeNull();
    expect(saveWebhook).not.toHaveBeenCalled();
  });

  /** The test edits the second hook, so index 0 stays as it is. */
  it('replaces only the edited entry, leaving siblings untouched', async () => {
    const { c, saveWebhook } = await setup(HOOKS);
    c.openEdit(1);
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

  /** The draft stays, so the user can try again. */
  it('keeps the dialog open and toasts on a save failure', async () => {
    const { c, toast } = await setup([], { saveError: true });
    c.openAdd();
    c.patch('name', 'Hook');
    c.patch('url', 'https://hook.test');
    c.save();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    expect(c.draft()).not.toBeNull();
  });

  /** The URL is not http or https, so errors() is not empty. */
  it('does not save when the URL is invalid (errors present)', async () => {
    const { c, saveWebhook } = await setup();
    c.openAdd();
    c.patch('url', 'ftp://nope');
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

  it('patch is a no-op without a draft', async () => {
    const { c } = await setup();
    c.patch('name', 'x');
    expect(c.draft()).toBeNull();
  });

  it('tr() localises a translation key', async () => {
    const { c } = await setup();
    expect(c.tr('admin.common.actions')).toBe('Aktionen');
  });

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
    await userEvent.click(screen.getByRole('button', { name: 'Weitere Aktionen: A' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Entfernen' }));
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

  /**
   * Without an HTTP response and a timestamp, both fall back to their placeholders. A dead letter
   * explains that the retries are used up.
   */
  it('opens the diagnosis dialog with the failure class, code and attempts', async () => {
    await setup(HOOKS, { status: [SENT, DEAD] });
    const toggle = screen.getAllByRole('button', { name: /^Zustellstatus/ })[1];
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(
      screen.getByText('Das Ziel ist nicht erreichbar oder aus Sicherheitsgründen blockiert.'),
    ).toBeInTheDocument();
    expect(screen.getByText('keine Antwort')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText(/Dead-Letter/)).toBeInTheDocument();
  });

  it('renders the response code and the timestamp of a successful delivery', async () => {
    await setup(HOOKS, { status: [SENT] });
    await userEvent.click(screen.getAllByRole('button', { name: /^Zustellstatus/ })[0]);
    expect(screen.getByText('200')).toBeInTheDocument();
    expect(screen.getByText('Erfolgreich zugestellt.')).toBeInTheDocument();
  });

  /** Without a name the card shows the URL as its title. */
  it('falls back to the hook URL and an empty-state text when no record exists', async () => {
    const { c, fixture } = await setup([{ ...HOOKS[0], name: '' }], { status: [] });
    expect(screen.getAllByText('https://a')).toHaveLength(2);
    c.toggleStatus(c.hooks()[0]);
    fixture.detectChanges();
    expect(c.statusDetail()).not.toBeNull();
    expect(screen.getByText('Für diesen Webhook liegt noch kein Zustellstatus vor.')).toBeInTheDocument();
    c.toggleStatus(c.hooks()[0]);
    expect(c.statusDetail()).toBeNull();
  });

  /** The list itself stays usable, so no error toast fires. */
  it('shows no state when the status request fails', async () => {
    const { c, toast } = await setup(HOOKS, { statusError: true });
    expect(c.statusOf('wh-1')).toBeNull();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('maps every state to a status text', async () => {
    const { c } = await setup();
    expect(c.deliveryStatus('sent')).toEqual({ kind: 'accent', key: 'admin.webhook.delivery.state.sent' });
    expect(c.deliveryStatus('dead').kind).toBe('error');
    expect(c.deliveryStatus('pending').kind).toBe('neutral');
    expect(c.deliveryStatus('never').kind).toBe('neutral');
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

  /** Each switch shows the state that its webhook holds. */
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

  /** The diagnosis route needs the permission, so it is never called. */
  it('hides create, edit, delete and the status column without webhook.manage', async () => {
    const { c, listWebhookDeliveryStatus } = await setup(HOOKS, { can: false });
    expect(c.canManage()).toBe(false);
    expect(listWebhookDeliveryStatus).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Webhook anlegen' })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Bearbeiten/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Entfernen/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Zustellstatus/ })).toBeNull();
    expect(screen.getByRole('switch', { name: 'Aktiv: A' })).toBeDisabled();
  });

  it('offers the delivery status with webhook.manage', async () => {
    await setup(HOOKS);
    expect(screen.getAllByRole('button', { name: /^Zustellstatus/ })).toHaveLength(2);
  });

  /** §ui-kit:000576 and §ui-kit:S/frontend/angular/000632: a failed read is a toast with a retry. */
  it('names a failed read in a toast with a retry, and in the face under it', async () => {
    const { fixture, api } = await setup([], { listError: true });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((fixture.componentInstance as any).loading()).toBe(false);
    expect(loadErrorToast()).toBe('Webhooks konnten nicht geladen werden.');
    expect(document.querySelector('app-empty-state')?.textContent).toContain('Webhooks konnten nicht geladen werden.');
    expect(screen.queryByText('Keine Webhooks konfiguriert.')).toBeNull();
    retryLoadError();
    expect(api.listWebhooks).toHaveBeenCalledTimes(2);
  });

  it('offers no "Webhook anlegen" without webhook.manage', async () => {
    await setup(HOOKS, { can: false });
    expect(screen.queryByRole('button', { name: 'Webhook anlegen' })).toBeNull();
  });
  /** §F/integrations/webhooks/002410, 002412, 002413: a new subscription starts without personal fields. */
  it('subscribes to an event with its fields that are not personal', async () => {
    const { c } = await setup();
    c.openAdd();
    c.setEvent(CATALOG[0], true);
    expect(c.subscriptionOf('application.transition')).toEqual({
      event: 'application.transition',
      fields: ['title'],
    });
    expect(c.hasTransition()).toBe(true);
    c.setField(CATALOG[0], 'applicantEmail', true);
    expect(c.subscriptionOf('application.transition').fields).toEqual(['title', 'applicantEmail']);
    c.setField(CATALOG[0], 'title', false);
    expect(c.subscriptionOf('application.transition').fields).toEqual(['applicantEmail']);
    c.setEvent(CATALOG[0], false);
    expect(c.subscriptionOf('application.transition')).toBeNull();
    expect(c.hasTransition()).toBe(false);
    c.setField(CATALOG[1], 'result', true);
    expect(c.subscriptionOf('vote.closed')).toBeNull();
  });

  it('ignores event and field changes without a draft', async () => {
    const { c } = await setup();
    c.setEvent(CATALOG[0], true);
    c.setField(CATALOG[0], 'title', true);
    expect(c.draft()).toBeNull();
    expect(c.subscriptionOf('application.transition')).toBeNull();
    expect(c.previews()).toEqual([]);
  });

  /** §F/integrations/webhooks/002411, 002414: the dialog lists the catalog and the filter choices. */
  it('renders the events by group, the personal mark and the filters', async () => {
    const { c, fixture } = await setup();
    c.openAdd();
    c.setEvent(CATALOG[0], true);
    fixture.detectChanges();
    expect(c.groups().map((g: { group: string }) => g.group)).toEqual(['applications', 'votes']);
    expect(c.gremiumOptions()).toEqual([{ value: 'g1', label: 'StuPa' }]);
    expect(c.typeOptions()).toEqual([{ value: 't1', label: 'Finanzantrag' }]);
    expect(c.stateOptions()).toEqual([{ value: 'approved', label: 'Genehmigt' }]);
    expect(screen.getByRole('checkbox', { name: 'Statuswechsel' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Statuswechsel' })).toBeInTheDocument();
    expect(screen.getAllByText('personenbezogen').length).toBeGreaterThan(0);
  });

  /** §NF/usability/controls/002581: a filter select names its chosen values. */
  it('names the chosen values in the text of a filter', async () => {
    const { c, fixture } = await setup();
    c.openAdd();
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Gremien' })).toBeInTheDocument();
    c.patch('gremiumIds', ['g1', 'gone']);
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Gremien: StuPa, gone' })).toBeInTheDocument();
  });

  it('leaves the choices empty when their reads fail', async () => {
    const { c } = await setup([], { choicesError: true });
    expect(c.catalog()).toEqual([]);
    expect(c.gremiumOptions()).toEqual([]);
    expect(c.typeOptions()).toEqual([]);
    expect(c.stateOptions()).toEqual([]);
  });

  /** §F/integrations/webhooks/002415: the preview shows the body of each subscribed event. */
  it('previews the body of each subscribed event', async () => {
    const { c } = await setup();
    c.openAdd();
    c.patch('subscriptions', [
      { event: 'vote.closed', fields: ['result'] },
      { event: 'gone.event', fields: [] },
    ]);
    const previews = c.previews();
    expect(previews).toHaveLength(1);
    expect(JSON.parse(previews[0].body)).toEqual({
      event: 'vote.closed',
      occurredAt: '2026-11-23T09:00:00+00:00',
      voteId: '3f6c1d2e-8a4b-4c5d-9e6f-7a8b9c0d1e2f',
      data: { result: 'passed' },
    });
  });

  it('builds the preview body and the subscription list', () => {
    expect(JSON.parse(previewBody(CATALOG[0], [])).data).toEqual({});
    const subs = withSubscription([], 'vote.closed', ['result']);
    expect(subs).toEqual([{ event: 'vote.closed', fields: ['result'] }]);
    expect(withSubscription(subs, 'vote.closed', null)).toEqual([]);
  });

  /** §F/integrations/webhooks/002416: the ⋮ menu sends a test delivery. */
  it('sends a test delivery from the menu and reads the status again later', async () => {
    jest.useFakeTimers();
    try {
      const { c, api, toast, listWebhookDeliveryStatus } = await setup(HOOKS);
      c.onMenu(HOOKS[0], { id: 'test', label: 'Testzustellung senden' });
      expect(api.sendWebhookTest).toHaveBeenCalledWith('wh-1');
      expect(toast.success).toHaveBeenCalled();
      const before = listWebhookDeliveryStatus.mock.calls.length;
      jest.advanceTimersByTime(15_000);
      expect(listWebhookDeliveryStatus.mock.calls.length).toBe(before + 1);
    } finally {
      jest.useRealTimers();
    }
  });

  it('toasts a failed test delivery', async () => {
    const { c, toast } = await setup(HOOKS, { testError: true });
    c.sendTest(HOOKS[0]);
    expect(toast.error).toHaveBeenCalled();
  });

  it('opens the delete confirm from the menu', async () => {
    const { c } = await setup(HOOKS);
    c.onMenu(HOOKS[1], { id: 'delete', label: 'Entfernen' });
    expect(c.confirmDelete()).toEqual(HOOKS[1]);
  });
});
