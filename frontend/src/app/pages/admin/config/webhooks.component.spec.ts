import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { WebhookConfig } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { WebhooksComponent } from './webhooks.component';

async function setup(seed: WebhookConfig[] = []) {
  const saveWebhook = jest.fn((h: WebhookConfig) => of({ ...h, id: h.id || 'wh-new' }));
  const api = { listWebhooks: jest.fn(() => of(seed)), saveWebhook };
  const view = await render(WebhooksComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
  });
  return { ...view, saveWebhook };
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
});
