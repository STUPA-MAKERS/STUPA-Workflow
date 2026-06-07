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

  it('validates URL and at least one event before allowing save', async () => {
    const { saveWebhook } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Webhook hinzufügen' }));

    expect(screen.getByText('Bitte eine gültige http(s)-URL angeben.')).toBeInTheDocument();
    const save = screen.getByRole('button', { name: 'Speichern' });
    expect(save).toBeDisabled();

    await userEvent.type(screen.getByRole('textbox', { name: 'Ziel-URL' }), 'https://hook.test');
    await userEvent.click(screen.getByRole('checkbox', { name: 'application_created' }));

    expect(save).toBeEnabled();
    await userEvent.click(save);
    expect(saveWebhook).toHaveBeenCalledTimes(1);
    expect(saveWebhook.mock.calls[0][0].events).toEqual(['application_created']);
  });

  it('toggles events off and removes a webhook', async () => {
    const seed = [
      { id: 'wh-1', name: 'A', url: 'https://a', events: ['vote_opened' as const], active: true },
    ];
    const { fixture } = await setup(seed);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.toggleEvent(0, 'vote_opened'); // remove existing event
    expect(c.hooks()[0].events).toEqual([]);
    c.toggleEvent(0, 'vote_closed'); // add new
    expect(c.hooks()[0].events).toEqual(['vote_closed']);
    expect(c.tr('admin.webhook.badUrl')).toContain('URL');
    c.save(0); // valid row (https + 1 event) → saveWebhook path
    c.remove(0);
    expect(c.hooks()).toHaveLength(0);
  });
});
