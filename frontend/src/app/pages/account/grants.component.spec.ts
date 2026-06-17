import { of, throwError } from 'rxjs';
import { render, screen, fireEvent } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import type { McpSetup, OAuthGrant } from '@core/api/models';
import * as downloadUtil from '@shared/download.util';
import { AccountGrantsComponent } from './grants.component';

const GRANTS: OAuthGrant[] = [
  {
    id: 'g-1',
    clientId: 'mcp',
    scope: 'application:read',
    createdAt: '2026-06-01T10:00:00Z',
    accessExpiresAt: '2026-07-01T10:00:00Z',
    refreshExpiresAt: null,
  },
  {
    id: 'g-2',
    clientId: 'mcp',
    scope: 'budget:read',
    createdAt: null,
    accessExpiresAt: '2026-08-01T10:00:00Z',
    refreshExpiresAt: null,
  },
];

const SETUP: McpSetup = {
  mcpServers: { antragsplattform: { url: 'https://x/mcp' } },
  baseUrl: 'https://x',
  clientId: 'mcp',
  scopesSupported: ['application:read'],
  install: 'npm i -g @antragsplattform/mcp',
  note: 'note',
};

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

interface ApiOverrides {
  listGrants?: jest.Mock;
  revokeGrant?: jest.Mock;
  revokeAllGrants?: jest.Mock;
  mcpConfig?: jest.Mock;
  downloadMcpPackage?: jest.Mock;
}

function makeApi(o: ApiOverrides = {}) {
  return {
    listGrants: o.listGrants ?? jest.fn(() => of(clone(GRANTS))),
    revokeGrant: o.revokeGrant ?? jest.fn(() => of(void 0)),
    revokeAllGrants: o.revokeAllGrants ?? jest.fn(() => of(void 0)),
    mcpConfig: o.mcpConfig ?? jest.fn(() => of(SETUP)),
    downloadMcpPackage:
      o.downloadMcpPackage ?? jest.fn(() => of(new Blob(['x'], { type: 'application/gzip' }))),
  };
}

async function setup(opts: { canMcp?: boolean; api?: ReturnType<typeof makeApi> } = {}) {
  const api = opts.api ?? makeApi();
  const auth = { canAny: jest.fn(() => opts.canMcp ?? false) };
  const view = await render(AccountGrantsComponent, {
    providers: [
      { provide: ApiClient, useValue: api },
      { provide: AuthService, useValue: auth },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const cmp = view.fixture.componentInstance;
  return { ...view, api, auth, cmp };
}

describe('AccountGrantsComponent (#MCP)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads grants on init and renders the table with created/expiry', async () => {
    const { api, cmp } = await setup();
    expect(api.listGrants).toHaveBeenCalled();
    expect(cmp.loading()).toBe(false);
    expect(cmp.grants()).toHaveLength(2);
    expect(screen.getByText('application:read')).toBeInTheDocument();
    // second grant has no createdAt; the access-expiry still renders.
    expect(screen.getByText('2026-08-01T10:00:00Z')).toBeInTheDocument();
  });

  it('shows the empty state when there are no grants', async () => {
    const api = makeApi({ listGrants: jest.fn(() => of([])) });
    const { cmp } = await setup({ api });
    expect(cmp.grants()).toEqual([]);
    expect(screen.getByText('Keine aktiven Zugriffe.')).toBeInTheDocument();
  });

  it('shows an error message when grants fail to load', async () => {
    const api = makeApi({ listGrants: jest.fn(() => throwError(() => new Error('boom'))) });
    const { cmp } = await setup({ api });
    expect(cmp.error()).toBe('account.grants.error');
    expect(cmp.loading()).toBe(false);
  });

  it('does NOT fetch the MCP config or render the MCP card when mcp.use is missing', async () => {
    const { api, auth, cmp } = await setup({ canMcp: false });
    expect(auth.canAny).toHaveBeenCalledWith('mcp.use');
    expect(api.mcpConfig).not.toHaveBeenCalled();
    expect(cmp.setup()).toBeNull();
    expect(cmp.canUseMcp()).toBe(false);
  });

  it('fetches the MCP config and exposes a pretty-printed snippet when allowed', async () => {
    const { api, cmp } = await setup({ canMcp: true });
    expect(api.mcpConfig).toHaveBeenCalled();
    expect(cmp.setup()).toEqual(SETUP);
    expect(cmp.setupJson()).toBe(
      JSON.stringify({ mcpServers: SETUP.mcpServers }, null, 2),
    );
    expect(screen.getByText(SETUP.install)).toBeInTheDocument();
  });

  it('keeps an empty snippet when the MCP config request fails', async () => {
    const api = makeApi({ mcpConfig: jest.fn(() => throwError(() => new Error('x'))) });
    const { cmp } = await setup({ canMcp: true, api });
    expect(cmp.setup()).toBeNull();
    expect(cmp.setupJson()).toBe('');
  });

  // ------------------------------------------------------------------ revoke
  it('revokes a single grant and reloads', async () => {
    const api = makeApi();
    const { cmp } = await setup({ api });
    cmp.revoke('g-1');
    expect(api.revokeGrant).toHaveBeenCalledWith('g-1');
    expect(api.listGrants).toHaveBeenCalledTimes(2);
  });

  it('revokes all grants and reloads', async () => {
    const api = makeApi();
    const { cmp } = await setup({ api });
    cmp.revokeAll();
    expect(api.revokeAllGrants).toHaveBeenCalled();
    expect(api.listGrants).toHaveBeenCalledTimes(2);
  });

  it('revoke-all button is wired in the template when grants exist', async () => {
    const api = makeApi();
    await setup({ api });
    fireEvent.click(screen.getByText('Alle widerrufen'));
    expect(api.revokeAllGrants).toHaveBeenCalled();
  });

  // ------------------------------------------------------------------- mcp
  it('downloads the MCP package as a tarball', async () => {
    const dl = jest.spyOn(downloadUtil, 'downloadBlob').mockImplementation(() => undefined);
    const api = makeApi();
    const { cmp } = await setup({ api, canMcp: true });
    cmp.downloadPackage();
    expect(api.downloadMcpPackage).toHaveBeenCalled();
    expect(dl).toHaveBeenCalledWith(expect.any(Blob), 'antragsplattform-mcp.tar.gz');
    dl.mockRestore();
  });

  it('copies the setup snippet to the clipboard when available', async () => {
    const writeText = jest.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    const { cmp } = await setup({ canMcp: true });
    cmp.copySetup();
    expect(writeText).toHaveBeenCalledWith(cmp.setupJson());
  });

  it('does not copy when there is no setup snippet', async () => {
    const writeText = jest.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    // mcp not allowed → setup is null → setupJson is '' → copy is a no-op.
    const { cmp } = await setup({ canMcp: false });
    cmp.copySetup();
    expect(writeText).not.toHaveBeenCalled();
  });

  it('tolerates a missing clipboard API when copying', async () => {
    Object.assign(navigator, { clipboard: undefined });
    const { cmp } = await setup({ canMcp: true });
    expect(() => cmp.copySetup()).not.toThrow();
  });
});
