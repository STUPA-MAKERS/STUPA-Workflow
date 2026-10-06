/**
 * Demo data of the account pages for the mock API (dev builds only): the mail switches,
 * the own OAuth grants, the MCP setup and a pending consent request. The interceptor
 * loads this module on first use, so it stays out of the initial bundle.
 *
 * `localStorage['mockNoMcp'] = '1'` makes the consent request report a person without
 * `mcp.use`, for the refusal state of the consent page.
 */
import type { ConsentRequest, McpSetup, NotificationPreference, OAuthGrant } from './models';

/** The answer of a mock route: the status and the body. */
export interface MockAccountReply {
  status: number;
  body: unknown;
}

/** The kinds of the server catalogue (`NOTIFICATION_KINDS`), in its order. */
let prefs: NotificationPreference[] = [
  { kind: 'status_update', enabled: true },
  { kind: 'comment', enabled: true },
  { kind: 'task', enabled: true },
  { kind: 'task_reminder', enabled: false },
  { kind: 'meeting', enabled: true },
  { kind: 'delegation', enabled: true },
  { kind: 'protocol', enabled: false },
  { kind: 'deadline', enabled: true },
  { kind: 'privacy', enabled: true },
];

/** A time `days` from now, as the server sends it. */
function at(days: number, hours = 0): string {
  return new Date(Date.now() + (days * 24 + hours) * 3600_000).toISOString();
}

/** The demo grants, newest first (the server order). */
function initialGrants(): OAuthGrant[] {
  return [
    {
      id: 'c1000000-0000-0000-0000-000000000001',
      clientId: 'antragsplattform-mcp',
      scope: 'read meetings:write votes:write',
      createdAt: at(-1, -2),
      accessExpiresAt: at(0, -2),
      refreshExpiresAt: at(29),
    },
    {
      id: 'c1000000-0000-0000-0000-000000000002',
      clientId: 'antragsplattform-mcp',
      scope: 'read',
      createdAt: at(-2),
      accessExpiresAt: at(88),
      refreshExpiresAt: at(88),
    },
    {
      id: 'c1000000-0000-0000-0000-000000000003',
      clientId: 'antragsplattform-mcp',
      scope: 'read applications:write',
      createdAt: at(-18),
      accessExpiresAt: at(12),
      refreshExpiresAt: at(12),
    },
  ];
}

let grants: OAuthGrant[] = initialGrants();

const SETUP: McpSetup = {
  mcpServers: { antragsplattform: { command: 'antragsplattform-mcp' } },
  baseUrl: 'https://stupa.example',
  clientId: 'antragsplattform-mcp',
  scopesSupported: [
    'admin:write',
    'applications:write',
    'budget:write',
    'flows:write',
    'forms:write',
    'meetings:write',
    'read',
    'votes:write',
  ],
  install: 'pip install -e .  # from the downloaded package directory',
  note: 'The downloaded package is pre-wired to this platform URL.',
};

/** The mock plays a person without `mcp.use` on the consent page. */
function noMcp(): boolean {
  try {
    return localStorage.getItem('mockNoMcp') === '1';
  } catch {
    return false;
  }
}

/** The pending request of the MCP client: all eight scopes, as the client asks. */
function consentRequest(): ConsentRequest {
  const keys = [
    'read',
    'applications:write',
    'votes:write',
    'meetings:write',
    'budget:write',
    'forms:write',
    'flows:write',
    'admin:write',
  ];
  return {
    clientId: 'antragsplattform-mcp',
    canUseMcp: !noMcp(),
    // The demo person holds no flow rights, so one scope shows the "not held" line.
    requestedScopes: keys.map((key) => ({ key, held: key !== 'flows:write' })),
    lifetimes: ['1h', '8h', '1d', '30d', '90d'],
    defaultLifetime: '30d',
  };
}

/** The answer to an account request, or undefined for another path or method. */
export function mockAccount(method: string, p: string, body: unknown): MockAccountReply | undefined {
  if (p.endsWith('/notifications/preferences')) {
    if (method === 'GET') return { status: 200, body: prefs };
    if (method === 'PUT') {
      const sent = (body as { preferences?: NotificationPreference[] } | null)?.preferences ?? [];
      prefs = prefs.map((x) => sent.find((s) => s.kind === x.kind) ?? x);
      return { status: 200, body: prefs };
    }
  }
  if (p.endsWith('/oauth/grants')) {
    if (method === 'GET') return { status: 200, body: grants };
    if (method === 'DELETE') {
      grants = [];
      return { status: 204, body: null };
    }
  }
  const one = /\/oauth\/grants\/([^/]+)$/.exec(p);
  if (one && method === 'DELETE') {
    grants = grants.filter((g) => g.id !== one[1]);
    return { status: 204, body: null };
  }
  if (method === 'GET' && p.endsWith('/oauth/consent-request')) {
    return { status: 200, body: consentRequest() };
  }
  if (method === 'POST' && p.endsWith('/oauth/consent')) {
    const approve = (body as { approve?: boolean } | null)?.approve === true;
    const redirect = approve
      ? 'http://127.0.0.1:8765/callback?code=mock-code&state=mock'
      : 'http://127.0.0.1:8765/callback?error=access_denied&state=mock';
    return { status: 200, body: { redirect } };
  }
  if (method === 'GET' && p.endsWith('/mcp/config')) return { status: 200, body: SETUP };
  if (method === 'GET' && p.endsWith('/mcp/package')) {
    return { status: 200, body: new Blob(['mock'], { type: 'application/gzip' }) };
  }
  return undefined;
}
