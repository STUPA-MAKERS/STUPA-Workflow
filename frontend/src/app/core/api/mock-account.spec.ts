import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { firstValueFrom } from 'rxjs';
import { USE_MOCK_API } from './api.config';
import { mockAccount } from './mock-account';
import { mockApiInterceptor } from './mock-api.interceptor';
import type { ConsentRequest, McpSetup, NotificationPreference, OAuthGrant } from './models';

describe('mockAccount (FE13 demo data)', () => {
  afterEach(() => localStorage.removeItem('mockNoMcp'));

  it('serves the switches of the server catalogue and stores a PUT', () => {
    const before = mockAccount('GET', '/api/notifications/preferences', null)!.body as NotificationPreference[];
    expect(before.map((p) => p.kind)).toEqual([
      'status_update',
      'comment',
      'task',
      'task_reminder',
      'meeting',
      'delegation',
      'protocol',
      'deadline',
      'privacy',
    ]);
    const saved = mockAccount('PUT', '/api/notifications/preferences', {
      preferences: [{ kind: 'protocol', enabled: true }],
    })!.body as NotificationPreference[];
    expect(saved.find((p) => p.kind === 'protocol')?.enabled).toBe(true);
    // A body without preferences keeps every switch.
    expect(mockAccount('PUT', '/api/notifications/preferences', null)!.body).toEqual(saved);
  });

  it('lists the grants, revokes one and then all of them', () => {
    const list = () => mockAccount('GET', '/api/oauth/grants', null)!.body as OAuthGrant[];
    const first = list();
    expect(first.length).toBe(3);
    expect(first.every((g) => g.accessExpiresAt !== null)).toBe(true);
    expect(mockAccount('DELETE', `/api/oauth/grants/${first[0].id}`, null)).toEqual({ status: 204, body: null });
    expect(list().map((g) => g.id)).toEqual(first.slice(1).map((g) => g.id));
    expect(mockAccount('DELETE', '/api/oauth/grants', null)!.status).toBe(204);
    expect(list()).toEqual([]);
  });

  it('serves a consent request with all eight scopes, and without mcp.use on request', () => {
    const req = mockAccount('GET', '/api/oauth/consent-request', null)!.body as ConsentRequest;
    expect(req.canUseMcp).toBe(true);
    expect(req.requestedScopes).toHaveLength(8);
    expect(req.requestedScopes.filter((s) => !s.held).map((s) => s.key)).toEqual(['flows:write']);
    expect(req.lifetimes).not.toContain('never');
    localStorage.setItem('mockNoMcp', '1');
    expect((mockAccount('GET', '/api/oauth/consent-request', null)!.body as ConsentRequest).canUseMcp).toBe(false);
  });

  it('plays the storage of a private window as a person with mcp.use', () => {
    const spy = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    try {
      expect((mockAccount('GET', '/api/oauth/consent-request', null)!.body as ConsentRequest).canUseMcp).toBe(true);
    } finally {
      spy.mockRestore();
    }
  });

  it('answers the consent post with a loopback redirect', () => {
    const ok = mockAccount('POST', '/api/oauth/consent', { approve: true })!.body as { redirect: string };
    expect(ok.redirect).toContain('code=');
    const no = mockAccount('POST', '/api/oauth/consent', null)!.body as { redirect: string };
    expect(no.redirect).toContain('error=access_denied');
  });

  it('serves the MCP setup and the package', () => {
    const setup = mockAccount('GET', '/api/mcp/config', null)!.body as McpSetup;
    expect(setup.mcpServers).toEqual({ antragsplattform: { command: 'antragsplattform-mcp' } });
    expect(mockAccount('GET', '/api/mcp/package', null)!.body).toBeInstanceOf(Blob);
  });

  it('answers nothing for another method or path', () => {
    expect(mockAccount('POST', '/api/notifications/preferences', null)).toBeUndefined();
    expect(mockAccount('POST', '/api/oauth/grants', null)).toBeUndefined();
    expect(mockAccount('GET', '/api/other', null)).toBeUndefined();
  });
});

describe('mockApiInterceptor: account routes', () => {
  let http: HttpClient;
  let ctrl: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([mockApiInterceptor])),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: true },
      ],
    });
    http = TestBed.inject(HttpClient);
    ctrl = TestBed.inject(HttpTestingController);
  });

  afterEach(() => ctrl.verify());

  it('loads the demo data lazily and answers the account pages', async () => {
    const prefs = await firstValueFrom(http.get<NotificationPreference[]>('/api/notifications/preferences'));
    expect(prefs.length).toBe(9);
    const setup = await firstValueFrom(http.get<McpSetup>('/api/mcp/config'));
    expect(setup.clientId).toBe('antragsplattform-mcp');
  });

  it('answers 404 for a method the demo data does not know', async () => {
    await expect(
      firstValueFrom(http.post('/api/notifications/preferences', {})),
    ).rejects.toMatchObject({ status: 404 });
  });

  it('gives the mock principal mcp.use', async () => {
    const me = await firstValueFrom(http.get<{ permissions: string[] }>('/api/auth/me'));
    expect(me.permissions).toContain('mcp.use');
  });
});
