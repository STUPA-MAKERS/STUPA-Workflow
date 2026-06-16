import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { WebhookConfig } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { ToastService } from '@shared/ui';
import { WebhooksComponent } from './webhooks.component';

async function setup(seed: WebhookConfig[] = [], opts: { saveError?: boolean } = {}) {
  const saveWebhook = opts.saveError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn((h: WebhookConfig) => of({ ...h, id: h.id || 'wh-new' }));
  const api = { listWebhooks: jest.fn(() => of(seed)), saveWebhook };
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(WebhooksComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, saveWebhook, toast };
}

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

    // Gültige URL genügt — ohne ein einziges Ereignis ist Speichern erlaubt (#6).
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
    const { fixture, saveWebhook } = await setup(seed);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openEdit(0);
    expect(c.draft().url).toBe('https://a');
    c.toggleEvent('vote_opened'); // remove existing event from the draft
    expect(c.draft().events).toEqual([]);
    c.toggleEvent('vote_closed'); // add a new one
    expect(c.draft().events).toEqual(['vote_closed']);
    // Bearbeiten lässt das Original unberührt, bis gespeichert wird.
    expect(c.hooks()[0].events).toEqual(['vote_opened']);
    c.save();
    expect(saveWebhook).toHaveBeenCalledTimes(1);
    expect(c.hooks()[0].events).toEqual(['vote_closed']);
    expect(c.draft()).toBeNull(); // Dialog nach dem Speichern zu
  });

  it('cancelling the dialog discards the draft', async () => {
    const { fixture, saveWebhook } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openAdd();
    c.patch('url', 'https://x');
    c.close();
    expect(c.draft()).toBeNull();
    expect(saveWebhook).not.toHaveBeenCalled();
  });

  it('replaces only the edited entry, leaving siblings untouched', async () => {
    const seed = [
      { id: 'wh-1', name: 'A', url: 'https://a', events: [] as const, active: true },
      { id: 'wh-2', name: 'B', url: 'https://b', events: [] as const, active: true },
    ];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { fixture, saveWebhook } = await setup(seed as any);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openEdit(1); // edit the SECOND hook → index 0 stays as-is (else branch)
    c.patch('name', 'B2');
    c.save();
    expect(saveWebhook).toHaveBeenCalledTimes(1);
    expect(c.hooks()[0].name).toBe('A'); // untouched sibling
    expect(c.hooks()[1].name).toBe('B2');
  });

  it('appends a newly-saved webhook to the list on add', async () => {
    const { fixture, saveWebhook, toast } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
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
    const { fixture, toast } = await setup([], { saveError: true });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openAdd();
    c.patch('url', 'https://hook.test');
    c.save();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    // draft is preserved so the user can retry
    expect(c.draft()).not.toBeNull();
  });

  it('does not save when the URL is invalid (errors present)', async () => {
    const { fixture, saveWebhook } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openAdd();
    c.patch('url', 'ftp://nope'); // not http(s) → errors().length > 0
    expect(c.errors()).toContain('admin.webhook.badUrl');
    c.save();
    expect(saveWebhook).not.toHaveBeenCalled();
  });

  it('save is a no-op without a draft', async () => {
    const { fixture, saveWebhook } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.save();
    expect(saveWebhook).not.toHaveBeenCalled();
  });

  it('errors() is empty when there is no draft', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.errors()).toEqual([]);
  });

  it('patch and toggleEvent are no-ops without a draft', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.patch('name', 'x');
    expect(c.draft()).toBeNull();
    c.toggleEvent('vote_opened');
    expect(c.draft()).toBeNull();
  });

  it('tr() localises a translation key', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.tr('admin.common.actions')).toBe('Aktionen');
  });
});
