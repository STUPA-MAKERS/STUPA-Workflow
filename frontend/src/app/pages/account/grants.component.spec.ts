import { NEVER, of, throwError } from 'rxjs';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import type { McpSetup, OAuthGrant } from '@core/api/models';
import * as downloadUtil from '@stupa-makers/ui-kit';

/**
 * The kit re-exports `downloadBlob` through getters, which a spy cannot replace. A plain copy of
 * the module lets each test spy on it.
 */
jest.mock('@stupa-makers/ui-kit', () => ({
  __esModule: true,
  ...jest.requireActual('@stupa-makers/ui-kit'),
}));
import { AccountGrantsComponent } from './grants.component';

const GRANTS: OAuthGrant[] = [
  {
    id: 'g-1',
    clientId: 'antragsplattform-mcp',
    scope: 'read meetings:write',
    createdAt: '2026-06-01T10:00:00Z',
    accessExpiresAt: '2026-07-01T10:00:00Z',
    refreshExpiresAt: null,
  },
  {
    id: 'g-2',
    clientId: 'antragsplattform-mcp',
    scope: 'read',
    createdAt: null,
    accessExpiresAt: '2026-08-01T10:00:00Z',
    refreshExpiresAt: null,
  },
];

const SETUP: McpSetup = {
  mcpServers: { antragsplattform: { command: 'antragsplattform-mcp' } },
  baseUrl: 'https://antraege.example.org',
  clientId: 'antragsplattform-mcp',
  scopesSupported: ['read'],
  install: 'pip install -e .  # from the downloaded package directory',
  note: 'note',
};

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

/** What `ldate` renders for the German UI, so the assertions do not hardcode a format. */
const fmt = (iso: string): string =>
  new Intl.DateTimeFormat('de-DE', { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(iso),
  );

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

/** The rows of "Aktive Zugriffe". */
function rows(): HTMLElement[] {
  return within(screen.getByRole('list', { name: 'Aktive Zugriffe' })).getAllByRole('listitem');
}

describe('AccountGrantsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** No raw ISO time and no scope key shows. A missing time is a dash. */
  it('lists the grants with scope labels, Erstellt and Läuft ab, and counts them', async () => {
    await setup();
    expect(screen.getByRole('heading', { name: 'Aktive Zugriffe · 2' })).toBeInTheDocument();
    const [first, second] = rows();
    expect(first).toHaveTextContent('Lesen, Sitzungen verwalten');
    expect(first).toHaveTextContent(`Erstellt ${fmt('2026-06-01T10:00:00Z')}`);
    expect(first).toHaveTextContent(`Läuft ab ${fmt('2026-07-01T10:00:00Z')}`);
    expect(first).not.toHaveTextContent('2026-07-01T10:00:00Z');
    expect(first).not.toHaveTextContent('meetings:write');
    expect(second).toHaveTextContent('Erstellt —');
  });

  it('shows a grant without an expiry as "Unbegrenzt"', async () => {
    const api = makeApi({
      listGrants: jest.fn(() => of([{ ...clone(GRANTS[0]), accessExpiresAt: null }])),
    });
    await setup({ api });
    expect(rows()[0]).toHaveTextContent('Läuft ab Unbegrenzt');
  });

  it('shows an unknown scope by its key', async () => {
    const api = makeApi({
      listGrants: jest.fn(() => of([{ ...clone(GRANTS[0]), scope: 'read future:write' }])),
    });
    await setup({ api });
    expect(rows()[0]).toHaveTextContent('Lesen, future:write');
  });

  it('shows the empty state and no "Alle widerrufen" without grants', async () => {
    const api = makeApi({ listGrants: jest.fn(() => of([])) });
    await setup({ api });
    expect(screen.getByText('Keine aktiven Zugriffe.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Aktive Zugriffe · 0' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Alle widerrufen' })).toBeNull();
  });

  it('shows no count in the heading while the list loads for the first time', async () => {
    const api = makeApi({ listGrants: jest.fn(() => NEVER) });
    await setup({ api });
    expect(screen.getByRole('heading', { name: 'Aktive Zugriffe' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Aktive Zugriffe · / })).toBeNull();
  });

  it('shows the empty list as the shared empty state, not as a row of an empty list', async () => {
    const api = makeApi({ listGrants: jest.fn(() => of([])) });
    const view = await setup({ api });
    expect(screen.queryByRole('list', { name: 'Aktive Zugriffe' })).toBeNull();
    expect(view.container.querySelector('app-empty-state')).toHaveTextContent('Keine aktiven Zugriffe.');
  });

  it('does not name the MCP config block with aria-labelledby (a pre has no name)', async () => {
    const view = await setup({ canMcp: true });
    expect(view.container.querySelector('pre.gr__json')).not.toHaveAttribute('aria-labelledby');
  });

  it('shows an error when the grants cannot load', async () => {
    const api = makeApi({ listGrants: jest.fn(() => throwError(() => new Error('boom'))) });
    await setup({ api });
    expect(screen.getByRole('alert')).toHaveTextContent('Zugriffe konnten nicht geladen werden.');
  });

  it('asks before it revokes one grant, then revokes it and loads again', async () => {
    const { api } = await setup();
    await userEvent.click(
      screen.getByRole('button', { name: 'Widerrufen: Lesen, Sitzungen verwalten' }),
    );
    expect(api.revokeGrant).not.toHaveBeenCalled();
    const dialog = screen.getByRole('dialog', { name: 'Zugriff widerrufen?' });
    expect(dialog).toHaveTextContent('„Lesen, Sitzungen verwalten“');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Widerrufen' }));
    expect(api.revokeGrant).toHaveBeenCalledWith('g-1');
    expect(api.listGrants).toHaveBeenCalledTimes(2);
  });

  it('cancels a revoke without a call', async () => {
    const { api } = await setup();
    await userEvent.click(
      screen.getByRole('button', { name: 'Widerrufen: Lesen, Sitzungen verwalten' }),
    );
    const dialog = screen.getByRole('dialog', { name: 'Zugriff widerrufen?' });
    const cancel = within(dialog).getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(cancel[cancel.length - 1]);
    expect(api.revokeGrant).not.toHaveBeenCalled();
  });

  it('asks before it revokes all grants, then revokes them and loads again', async () => {
    const { api } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Alle widerrufen' }));
    expect(api.revokeAllGrants).not.toHaveBeenCalled();
    const dialog = screen.getByRole('dialog', { name: 'Alle Zugriffe widerrufen?' });
    expect(dialog).toHaveTextContent('Alle Zugriffe enden sofort.');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Alle widerrufen' }));
    expect(api.revokeAllGrants).toHaveBeenCalled();
    expect(api.listGrants).toHaveBeenCalledTimes(2);
  });

  it('shows an error when a revoke fails', async () => {
    const api = makeApi({ revokeGrant: jest.fn(() => throwError(() => new Error('x'))) });
    const { fixture } = await setup({ api });
    await userEvent.click(
      screen.getByRole('button', { name: 'Widerrufen: Lesen, Sitzungen verwalten' }),
    );
    const dialog = screen.getByRole('dialog', { name: 'Zugriff widerrufen?' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Widerrufen' }));
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('Widerrufen fehlgeschlagen.');
  });

  it('has no MCP card and loads no setup without mcp.use', async () => {
    const { api, auth } = await setup({ canMcp: false });
    expect(auth.canAny).toHaveBeenCalledWith('mcp.use');
    expect(api.mcpConfig).not.toHaveBeenCalled();
    expect(screen.queryByRole('heading', { name: 'MCP-Server' })).toBeNull();
  });

  /** The install command shows without the shell comment of the server. */
  it('shows the MCP card: download, steps, config and the platform URL', async () => {
    const { api } = await setup({ canMcp: true });
    expect(api.mcpConfig).toHaveBeenCalled();
    expect(screen.getByRole('heading', { name: 'MCP-Server' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /MCP-Paket herunterladen/ })).toBeInTheDocument();
    expect(screen.getByText('pip install -e .')).toBeInTheDocument();
    expect(screen.getByText(/"command": "antragsplattform-mcp"/)).toBeInTheDocument();
    const url = screen.getByRole('link', { name: SETUP.baseUrl });
    expect(url).toHaveAttribute('href', SETUP.baseUrl);
    expect(url).toHaveAttribute('rel', 'noopener');
  });

  it('downloads the MCP package as a tarball', async () => {
    const dl = jest.spyOn(downloadUtil, 'downloadBlob').mockImplementation(() => undefined);
    const { api } = await setup({ canMcp: true });
    await userEvent.click(screen.getByRole('button', { name: /MCP-Paket herunterladen/ }));
    expect(api.downloadMcpPackage).toHaveBeenCalled();
    expect(dl).toHaveBeenCalledWith(expect.any(Blob), 'antragsplattform-mcp.tar.gz');
    dl.mockRestore();
  });

  it('copies the MCP config and says so', async () => {
    const writeText = jest.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const { cmp, fixture } = await setup({ canMcp: true });
    await userEvent.click(screen.getByRole('button', { name: 'MCP-Konfiguration kopieren' }));
    expect(writeText).toHaveBeenCalledWith(cmp.setupJson());
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Kopiert' })).toBeInTheDocument();
    expect(screen.getByText('Kopiert', { selector: '[aria-live]' })).toBeInTheDocument();
  });

  it('keeps the label when the copy is refused', async () => {
    const writeText = jest.fn(() => Promise.reject(new Error('denied')));
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const { fixture } = await setup({ canMcp: true });
    await userEvent.click(screen.getByRole('button', { name: 'MCP-Konfiguration kopieren' }));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'MCP-Konfiguration kopieren' })).toBeInTheDocument();
  });

  it('shows no copy button without the setup', async () => {
    const { cmp } = await setup({ canMcp: false });
    expect(screen.queryByRole('button', { name: 'MCP-Konfiguration kopieren' })).toBeNull();
    expect(cmp.installCommand()).toBe('');
  });

  it('keeps the download in the card when the setup cannot load', async () => {
    const api = makeApi({ mcpConfig: jest.fn(() => throwError(() => new Error('x'))) });
    await setup({ canMcp: true, api });
    expect(screen.getByRole('button', { name: /MCP-Paket herunterladen/ })).toBeInTheDocument();
    expect(screen.queryByText('MCP-Konfiguration')).toBeNull();
  });

  it('shows an error when the download fails, and ignores a second press while it runs', async () => {
    const api = makeApi({ downloadMcpPackage: jest.fn(() => throwError(() => new Error('x'))) });
    const { cmp, fixture } = await setup({ canMcp: true, api });
    cmp.downloadPackage();
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('Das MCP-Paket konnte nicht geladen werden.');
    cmp.downloading.set(true);
    cmp.downloadPackage();
    expect(api.downloadMcpPackage).toHaveBeenCalledTimes(1);
  });

  it('does nothing on a revoke without a question or while one runs', async () => {
    const { api, cmp } = await setup();
    cmp.doRevoke();
    cmp.askRevokeAll();
    cmp.revoking.set(true);
    cmp.doRevoke();
    expect(api.revokeAllGrants).not.toHaveBeenCalled();
    expect(api.revokeGrant).not.toHaveBeenCalled();
  });

  it('reads a grant without scopes as no labels', async () => {
    const { cmp } = await setup();
    expect(cmp.scopeLabels({ ...clone(GRANTS[0]), scope: null as unknown as string })).toBe('');
  });

  it('tolerates a missing clipboard API', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    const { fixture } = await setup({ canMcp: true });
    await userEvent.click(screen.getByRole('button', { name: 'MCP-Konfiguration kopieren' }));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'MCP-Konfiguration kopieren' })).toBeInTheDocument();
  });
});
