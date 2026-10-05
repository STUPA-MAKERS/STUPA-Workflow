import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import type { ConsentRequest } from '@core/api/models';
import {
  createLocationMock,
  provideLocationMock,
  type LocationMock,
} from '../../../testing/location-mock';
import { runAxe } from '../../../testing/a11y';
import { OAuthConsentComponent } from './consent.component';

/** The eight scopes of the server (`auth/oauth.py` SCOPE_ORDER), as the MCP client asks. */
const ALL_SCOPES = [
  'read',
  'applications:write',
  'votes:write',
  'meetings:write',
  'budget:write',
  'forms:write',
  'flows:write',
  'admin:write',
];

const LABELS = [
  'Lesen',
  'Anträge bearbeiten',
  'Abstimmungen verwalten',
  'Sitzungen verwalten',
  'Budget verwalten',
  'Formulare bearbeiten',
  'Workflows bearbeiten',
  'Administration',
];

const REQ: ConsentRequest = {
  clientId: 'antragsplattform-mcp',
  canUseMcp: true,
  requestedScopes: ALL_SCOPES.map((key) => ({ key, held: key !== 'flows:write' })),
  lifetimes: ['1h', '8h', '1d', '30d', '90d'],
  defaultLifetime: '30d',
};

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

interface ApiOverrides {
  consentRequest?: jest.Mock;
  submitConsent?: jest.Mock;
}

function makeApi(o: ApiOverrides = {}) {
  return {
    consentRequest: o.consentRequest ?? jest.fn(() => of(clone(REQ))),
    submitConsent:
      o.submitConsent ?? jest.fn(() => of({ redirect: 'http://127.0.0.1:9999/cb?code=abc' })),
  };
}

let loc: LocationMock;

async function setup(api = makeApi()) {
  const view = await render(OAuthConsentComponent, {
    providers: [{ provide: ApiClient, useValue: api }, provideLocationMock(loc)],
  });
  // ngModel writes to the boxes asynchronously.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const cmp = view.fixture.componentInstance;
  return { ...view, api, cmp };
}

describe('OAuthConsentComponent', () => {
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    loc = createLocationMock();
  });

  it('names the client', async () => {
    await setup();
    expect(screen.getByRole('heading', { level: 1, name: 'Zugriff erlauben' })).toBeInTheDocument();
    expect(screen.getByText('antragsplattform-mcp')).toBeInTheDocument();
  });

  it('lists every requested scope by its label, all ticked', async () => {
    const { container } = await setup();
    const boxes = screen.getAllByRole('checkbox') as HTMLInputElement[];
    expect(boxes).toHaveLength(8);
    expect(boxes.every((b) => b.checked)).toBe(true);
    for (const label of LABELS) {
      expect(screen.getByRole('checkbox', { name: new RegExp(`^${label}`) })).toBeInTheDocument();
    }
    // No raw key and no translation key shows.
    expect(container.textContent).not.toContain('account.scope.');
    expect(screen.queryByText('meetings:write')).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says which scopes the person does not hold', async () => {
    await setup();
    expect(
      screen.getByRole('checkbox', { name: /^Workflows bearbeiten.*Du besitzt dieses Recht aktuell nicht/ }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Du besitzt dieses Recht aktuell nicht/)).toHaveLength(1);
  });

  it('shows an unknown scope by its key', async () => {
    const api = makeApi({
      consentRequest: jest.fn(() =>
        of({ ...clone(REQ), requestedScopes: [{ key: 'future:write', held: true }] }),
      ),
    });
    await setup(api);
    expect(screen.getByRole('checkbox', { name: 'future:write' })).toBeInTheDocument();
  });

  it('offers the lifetimes of the server, the default chosen, and no "never"', async () => {
    await setup();
    const chips = ['1 Stunde', '8 Stunden', '1 Tag', '30 Tage', '90 Tage'].map((n) =>
      screen.getByRole('button', { name: n }),
    );
    expect(chips.map((c) => c.getAttribute('aria-pressed'))).toEqual([
      'false',
      'false',
      'false',
      'true',
      'false',
    ]);
    expect(screen.queryByText(/nie ab/)).toBeNull();
  });

  it('shows an unknown lifetime by its key', async () => {
    const api = makeApi({
      consentRequest: jest.fn(() => of({ ...clone(REQ), lifetimes: ['2w'], defaultLifetime: '2w' })),
    });
    await setup(api);
    expect(screen.getByRole('button', { name: '2w' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('sends the chosen scopes and the chosen lifetime, then follows the redirect', async () => {
    const { api } = await setup();
    await userEvent.click(screen.getByRole('checkbox', { name: /^Administration/ }));
    await userEvent.click(screen.getByRole('button', { name: '8 Stunden' }));
    await userEvent.click(screen.getByRole('button', { name: 'Erlauben' }));
    expect(api.submitConsent).toHaveBeenCalledWith({
      approve: true,
      scopes: ALL_SCOPES.filter((s) => s !== 'admin:write'),
      lifetime: '8h',
    });
    expect(loc.assign).toHaveBeenCalledWith('http://127.0.0.1:9999/cb?code=abc');
  });

  it('disables "Erlauben" when no scope is ticked', async () => {
    const { cmp, fixture } = await setup();
    for (const key of ALL_SCOPES) cmp.setScope(key, false);
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Erlauben' })).toBeDisabled();
  });

  it('denies with no scopes and follows the redirect', async () => {
    const api = makeApi({
      submitConsent: jest.fn(() => of({ redirect: 'http://127.0.0.1/cb?error=access_denied' })),
    });
    await setup(api);
    await userEvent.click(screen.getByRole('button', { name: 'Ablehnen' }));
    expect(api.submitConsent).toHaveBeenCalledWith({ approve: false, scopes: [], lifetime: '30d' });
    expect(loc.assign).toHaveBeenCalledWith('http://127.0.0.1/cb?error=access_denied');
  });

  it('without mcp.use: shows the error line, no choices, and disables "Erlauben"', async () => {
    const api = makeApi({
      consentRequest: jest.fn(() => of({ ...clone(REQ), canUseMcp: false })),
    });
    await setup(api);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Dir fehlt die Berechtigung »mcp.use« für API-Agenten.',
    );
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Erlauben' })).toBeDisabled();
    // The person can still deny, so the client learns the outcome.
    await userEvent.click(screen.getByRole('button', { name: 'Ablehnen' }));
    expect(api.submitConsent).toHaveBeenCalledWith(expect.objectContaining({ approve: false }));
  });

  it('shows an error when the request cannot load', async () => {
    const api = makeApi({ consentRequest: jest.fn(() => throwError(() => new Error('boom'))) });
    await setup(api);
    expect(screen.getByRole('alert')).toHaveTextContent('Anfrage konnte nicht verarbeitet werden.');
    expect(screen.queryByRole('button', { name: 'Erlauben' })).toBeNull();
  });

  it('shows an error and stays when the submission fails', async () => {
    const api = makeApi({ submitConsent: jest.fn(() => throwError(() => new Error('x'))) });
    const { cmp, fixture } = await setup(api);
    await userEvent.click(screen.getByRole('button', { name: 'Erlauben' }));
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('Anfrage konnte nicht verarbeitet werden.');
    expect(cmp.submitting()).toBe(false);
    expect(loc.assign).not.toHaveBeenCalled();
  });
});
