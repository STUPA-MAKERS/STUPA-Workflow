import { of, throwError } from 'rxjs';
import { render, screen, fireEvent } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import type { ConsentRequest } from '@core/api/models';
import { mockWindowLocation, type LocationMock } from '../../../testing/location-mock';
import { OAuthConsentComponent } from './consent.component';

const REQ: ConsentRequest = {
  clientId: 'mcp-cli',
  canUseMcp: true,
  requestedScopes: [
    { key: 'application:read', held: true },
    { key: 'budget:write', held: false },
  ],
  lifetimes: ['1d', '30d', 'never'],
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

async function setup(api = makeApi()) {
  const view = await render(OAuthConsentComponent, {
    providers: [{ provide: ApiClient, useValue: api }],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const cmp = view.fixture.componentInstance;
  return { ...view, api, cmp };
}

describe('OAuthConsentComponent (#MCP)', () => {
  let loc: LocationMock;
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    loc = mockWindowLocation();
  });
  afterEach(() => loc.restore());

  it('loads the request, preselects every requested scope and the default lifetime', async () => {
    const { api, cmp } = await setup();
    expect(api.consentRequest).toHaveBeenCalled();
    expect(cmp.loading()).toBe(false);
    expect(cmp.req()).toEqual(REQ);
    expect(cmp.selected()).toEqual({ 'application:read': true, 'budget:write': true });
    expect(cmp.lifetime()).toBe('30d');
    expect(cmp.anySelected()).toBe(true);
  });

  it('shows an error when the consent request fails', async () => {
    const api = makeApi({ consentRequest: jest.fn(() => throwError(() => new Error('boom'))) });
    const { cmp } = await setup(api);
    expect(cmp.error()).toBe('account.consent.error');
    expect(cmp.loading()).toBe(false);
    expect(cmp.req()).toBeNull();
    expect(screen.getByText('Anfrage konnte nicht verarbeitet werden.')).toBeInTheDocument();
  });

  it('builds i18n keys for lifetimes and scope label/description', async () => {
    const { cmp } = await setup();
    expect(cmp.lifetimeKey('never')).toBe('account.lifetime.never');
    // ':' is normalized to '_' for the i18n key.
    expect(cmp.scopeLabelKey('application:read')).toBe('account.scope.application_read.label');
    expect(cmp.scopeDescKey('budget:write')).toBe('account.scope.budget_write.desc');
  });

  it('toggle flips a single scope without touching the others', async () => {
    const { cmp } = await setup();
    cmp.toggle('application:read');
    expect(cmp.selected()).toEqual({ 'application:read': false, 'budget:write': true });
    expect(cmp.anySelected()).toBe(true);
    cmp.toggle('budget:write');
    expect(cmp.selected()).toEqual({ 'application:read': false, 'budget:write': false });
    expect(cmp.anySelected()).toBe(false);
  });

  it('toggle adds a previously-unseen scope key as enabled', async () => {
    const { cmp } = await setup();
    cmp.toggle('extra:scope');
    expect(cmp.selected()['extra:scope']).toBe(true);
  });

  it('setLifetime updates the chosen token lifetime', async () => {
    const { cmp } = await setup();
    cmp.setLifetime('never');
    expect(cmp.lifetime()).toBe('never');
  });

  // ----------------------------------------------------------------- approve
  it('approve submits only the enabled scopes and redirects', async () => {
    const api = makeApi();
    const { cmp } = await setup(api);
    cmp.toggle('budget:write'); // disable the second scope
    cmp.approve();
    expect(api.submitConsent).toHaveBeenCalledWith({
      approve: true,
      scopes: ['application:read'],
      lifetime: '30d',
    });
    expect(loc.assign).toHaveBeenCalledWith('http://127.0.0.1:9999/cb?code=abc');
  });

  it('deny submits with no scopes and redirects', async () => {
    const api = makeApi({ submitConsent: jest.fn(() => of({ redirect: 'http://127.0.0.1/cb?error=denied' })) });
    const { cmp } = await setup(api);
    cmp.deny();
    expect(api.submitConsent).toHaveBeenCalledWith({
      approve: false,
      scopes: [],
      lifetime: '30d',
    });
    expect(loc.assign).toHaveBeenCalledWith('http://127.0.0.1/cb?error=denied');
  });

  it('shows an error and clears submitting when the submission fails', async () => {
    const api = makeApi({ submitConsent: jest.fn(() => throwError(() => new Error('x'))) });
    const { cmp } = await setup(api);
    cmp.approve();
    expect(cmp.error()).toBe('account.consent.error');
    expect(cmp.submitting()).toBe(false);
    expect(loc.assign).not.toHaveBeenCalled();
  });

  it('renders approve/deny buttons and wires them through the template', async () => {
    const api = makeApi();
    await setup(api);
    fireEvent.click(screen.getByText('Erlauben'));
    expect(api.submitConsent).toHaveBeenCalledWith(
      expect.objectContaining({ approve: true }),
    );
  });
});
