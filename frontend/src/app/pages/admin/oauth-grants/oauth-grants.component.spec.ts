import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import type { AdminPrincipal, OAuthGrantAdmin, OAuthGrantQuery } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { AdminOAuthGrantsComponent } from './oauth-grants.component';

const PRINCIPALS: AdminPrincipal[] = [
  { id: 'p-1', sub: 'kc|alex', email: 'alex@x.de', displayName: 'Alex Admin', assignments: [] },
  { id: 'p-2', sub: 'kc|sam', email: 'sam@x.de', displayName: null, assignments: [] },
  // Neither a name nor an email: the option falls back to the placeholder.
  { id: 'p-3', sub: 'kc|ghost', email: null, displayName: null, assignments: [] },
];

/** A named owner with both expiry dates set. */
const NAMED: OAuthGrantAdmin = {
  id: 'grant-1',
  principalId: 'p-1',
  principalName: 'Alex Admin',
  principalEmail: 'alex@x.de',
  clientId: 'antragsplattform-mcp',
  scope: 'mcp:read mcp:write',
  createdAt: '2026-06-01T10:00:00+00:00',
  accessExpiresAt: '2026-09-01T10:00:00+00:00',
  refreshExpiresAt: '2026-12-01T10:00:00+00:00',
};

/** No owner name and no expiry: placeholder + "never expires". */
const ANONYMOUS: OAuthGrantAdmin = {
  id: 'grant-2',
  principalId: 'p-3',
  principalName: null,
  principalEmail: null,
  clientId: 'cli-agent',
  scope: 'mcp:read',
  createdAt: '2026-05-02T08:30:00+00:00',
  accessExpiresAt: null,
  refreshExpiresAt: null,
};

const GRANTS = [NAMED, ANONYMOUS];

function page(items: OAuthGrantAdmin[], total = items.length, offset = 0) {
  return { items, total, limit: 25, offset };
}

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listOAuthGrants: jest.fn((_q: OAuthGrantQuery = {}) => of(page(GRANTS))),
    revokeOAuthGrant: jest.fn(() => of(void 0)),
    listPrincipals: jest.fn(() => of(PRINCIPALS.map((p) => ({ ...p })))),
    ...over,
  };
}

function makeAuth(canManage = true) {
  return { can: (p: string) => canManage && p === 'admin.users' } as unknown as AuthService;
}

async function setup(api = makeApi(), auth = makeAuth()) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(AdminOAuthGrantsComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: auth },
      { provide: ToastService, useValue: toast },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const inst = view.fixture.componentInstance as any;
  return { ...view, api, toast, inst };
}

describe('AdminOAuthGrantsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the grants with owner, client and scope', async () => {
    const { api } = await setup();
    expect(api.listOAuthGrants).toHaveBeenCalledWith({
      limit: 25,
      offset: 0,
      principalId: null,
    });
    expect(screen.getByText('Alex Admin')).toBeInTheDocument();
    expect(screen.getByText('antragsplattform-mcp')).toBeInTheDocument();
    expect(screen.getByText('cli-agent')).toBeInTheDocument();
    expect(screen.getByText('mcp:write')).toBeInTheDocument();
    // The owner email is a second line, because it adds to the name.
    expect(screen.getByText('alex@x.de')).toBeInTheDocument();
  });

  it('shows a placeholder instead of an id when the owner has no name', async () => {
    const { inst } = await setup();
    expect(screen.getByText('Person ohne Namen')).toBeInTheDocument();
    // The rule is absolute: no principal id reaches the screen.
    expect(screen.queryByText('p-3')).not.toBeInTheDocument();
    expect(inst.ownerName(ANONYMOUS)).toBe('Person ohne Namen');
    expect(inst.ownerEmail(ANONYMOUS)).toBeNull();
    expect(inst.ownerEmail(NAMED)).toBe('alex@x.de');
    // A name that equals the email adds nothing as a second line.
    expect(inst.ownerEmail({ ...NAMED, principalName: 'alex@x.de' })).toBeNull();
  });

  it('renders a null expiry as "never expires" instead of an empty cell', async () => {
    await setup();
    // Access and refresh token of the second row both never expire.
    expect(screen.getAllByText('Läuft nie ab')).toHaveLength(2);
  });

  it('renders the load error instead of the table', async () => {
    const api = makeApi({ listOAuthGrants: jest.fn(() => throwError(() => new Error('boom'))) });
    const { inst } = await setup(api);
    expect(inst.loadError()).toBe(true);
    expect(inst.loading()).toBe(false);
    expect(screen.getByRole('alert')).toHaveTextContent('Die Zugänge konnten nicht geladen werden.');
  });

  it('survives a failing principal list — the grants still show', async () => {
    const api = makeApi({ listPrincipals: jest.fn(() => throwError(() => new Error('boom'))) });
    const { inst } = await setup(api);
    expect(inst.principals()).toEqual([]);
    expect(screen.getByText('Alex Admin')).toBeInTheDocument();
  });

  // --- filter ---------------------------------------------------------------

  it('filters by principal and restarts at page one', async () => {
    const { api, inst } = await setup();
    inst.offset.set(25);
    inst.setPrincipal('p-1');
    expect(inst.offset()).toBe(0);
    expect(api.listOAuthGrants).toHaveBeenLastCalledWith({
      limit: 25,
      offset: 0,
      principalId: 'p-1',
    });
    expect(inst.activeFilterCount()).toBe(1);
    // The reset clears the filter and reloads without it.
    inst.resetFilters();
    expect(inst.activeFilterCount()).toBe(0);
    expect(api.listOAuthGrants).toHaveBeenLastCalledWith({
      limit: 25,
      offset: 0,
      principalId: null,
    });
  });

  it('offers every principal by name, email or placeholder — never an id', async () => {
    const { inst } = await setup();
    expect(inst.principalOptions()).toEqual([
      { value: '', label: 'Alle Personen' },
      { value: 'p-1', label: 'Alex Admin' },
      { value: 'p-2', label: 'sam@x.de' },
      { value: 'p-3', label: 'Person ohne Namen' },
    ]);
  });

  it('filters through the select in the filter bar', async () => {
    const { api } = await setup();
    await userEvent.click(screen.getByRole('button', { name: /Filter/ }));
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Person' }), 'p-1');
    expect(api.listOAuthGrants).toHaveBeenLastCalledWith(
      expect.objectContaining({ principalId: 'p-1' }),
    );
  });

  // --- paging ---------------------------------------------------------------

  it('pages forward and back and reports the range', async () => {
    const first = GRANTS;
    const second = [{ ...NAMED, id: 'grant-3' }];
    const api = makeApi({
      listOAuthGrants: jest.fn((q: OAuthGrantQuery = {}) =>
        of(q.offset === 25 ? page(second, 26, 25) : page(first, 26, 0)),
      ),
    });
    const { inst } = await setup(api);
    expect(inst.rangeLabel()).toBe('1–2 von 26');
    expect(inst.hasPrev()).toBe(false);
    expect(inst.hasNext()).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: 'Weiter' }));
    expect(inst.offset()).toBe(25);
    expect(inst.rangeLabel()).toBe('26–26 von 26');
    expect(inst.hasNext()).toBe(false);
    expect(inst.hasPrev()).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: 'Zurück' }));
    expect(inst.offset()).toBe(0);
    expect(api.listOAuthGrants).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0 }),
    );
  });

  it('ignores a page step past either end', async () => {
    const { api, inst } = await setup();
    const calls = api.listOAuthGrants.mock.calls.length;
    inst.prevPage(); // already on page one
    inst.nextPage(); // the single page holds every row
    expect(api.listOAuthGrants.mock.calls.length).toBe(calls);
    expect(inst.offset()).toBe(0);
  });

  it('reports an empty page as 0 of 0', async () => {
    const api = makeApi({ listOAuthGrants: jest.fn(() => of(page([], 0))) });
    const { inst } = await setup(api);
    expect(inst.rangeLabel()).toBe('0–0 von 0');
    expect(screen.getByText('Keine aktiven Agent-Zugänge.')).toBeInTheDocument();
  });

  // --- revoke ---------------------------------------------------------------

  it('revokes a grant after the confirmation names owner and client', async () => {
    const { api, inst, toast } = await setup();
    await userEvent.click(screen.getAllByRole('button', { name: 'Widerrufen' })[0]);
    expect(inst.confirmRevoke()).toEqual(NAMED);
    expect(
      screen.getByText(/Zugang von Alex Admin für die Anwendung .antragsplattform-mcp./),
    ).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Der Agent verliert den Zugriff sofort.');

    const before = api.listOAuthGrants.mock.calls.length;
    inst.doRevoke();
    expect(api.revokeOAuthGrant).toHaveBeenCalledWith('grant-1');
    expect(inst.confirmRevoke()).toBeNull();
    expect(inst.revoking()).toBe(false);
    expect(toast.success).toHaveBeenCalledWith('Zugang widerrufen.');
    // The list refreshes, so a second admin's change also shows up.
    expect(api.listOAuthGrants.mock.calls.length).toBe(before + 1);
  });

  it('treats a 404 as "already gone" and refreshes the list', async () => {
    const api = makeApi({
      revokeOAuthGrant: jest.fn(() => throwError(() => ({ status: 404 }))),
    });
    const { inst, toast } = await setup(api);
    const before = api.listOAuthGrants.mock.calls.length;
    inst.askRevoke(NAMED);
    inst.doRevoke();
    expect(inst.confirmRevoke()).toBeNull();
    expect(toast.success).toHaveBeenCalledWith('Dieser Zugang bestand nicht mehr.');
    expect(toast.error).not.toHaveBeenCalled();
    expect(api.listOAuthGrants.mock.calls.length).toBe(before + 1);
  });

  it('toasts and keeps the dialog open on any other revoke failure', async () => {
    const api = makeApi({
      revokeOAuthGrant: jest.fn(() => throwError(() => ({ status: 500 }))),
    });
    const { inst, toast } = await setup(api);
    inst.askRevoke(NAMED);
    inst.doRevoke();
    expect(toast.error).toHaveBeenCalledWith('Der Zugang konnte nicht widerrufen werden.');
    expect(inst.confirmRevoke()).toEqual(NAMED);
    expect(inst.revoking()).toBe(false);
  });

  it('treats an error without a status as a plain failure', async () => {
    const api = makeApi({
      revokeOAuthGrant: jest.fn(() => throwError(() => new Error('offline'))),
    });
    const { inst, toast } = await setup(api);
    inst.askRevoke(NAMED);
    inst.doRevoke();
    expect(toast.error).toHaveBeenCalledWith('Der Zugang konnte nicht widerrufen werden.');
  });

  it('treats a non-numeric status as a plain failure', async () => {
    const api = makeApi({
      revokeOAuthGrant: jest.fn(() => throwError(() => ({ status: 'nope' }))),
    });
    const { inst, toast } = await setup(api);
    inst.askRevoke(NAMED);
    inst.doRevoke();
    expect(toast.error).toHaveBeenCalledWith('Der Zugang konnte nicht widerrufen werden.');
  });

  it('does nothing without a pending confirmation or while a revoke runs', async () => {
    const { api, inst } = await setup();
    inst.doRevoke();
    expect(api.revokeOAuthGrant).not.toHaveBeenCalled();
    inst.askRevoke(NAMED);
    inst.revoking.set(true);
    inst.doRevoke();
    expect(api.revokeOAuthGrant).not.toHaveBeenCalled();
  });

  // --- permission gating ----------------------------------------------------

  it('hides the revoke column and control without admin.users', async () => {
    const { inst } = await setup(makeApi(), makeAuth(false));
    expect(inst.canRevoke()).toBe(false);
    expect(inst.columns().some((c: { key: string }) => c.key === 'actions')).toBe(false);
    expect(screen.queryByRole('button', { name: 'Widerrufen' })).not.toBeInTheDocument();
    // The list itself stays readable.
    expect(screen.getByText('Alex Admin')).toBeInTheDocument();
  });

  it('shows the revoke column with admin.users', async () => {
    const { inst } = await setup();
    expect(inst.canRevoke()).toBe(true);
    expect(inst.columns().some((c: { key: string }) => c.key === 'actions')).toBe(true);
    expect(screen.getAllByRole('button', { name: 'Widerrufen' })).toHaveLength(2);
  });
});
