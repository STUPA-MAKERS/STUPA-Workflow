import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { DelegationApiService } from './delegations-api.service';
import { DelegationsComponent } from './delegations.component';
import type { Delegation } from './delegations.models';

function makeDelegation(over: Partial<Delegation> = {}): Delegation {
  return {
    id: 'del-1',
    principalId: 'p-1',
    roleId: 'r-1',
    gremiumId: null,
    delegatedBy: 'me',
    grantedBy: 'me',
    validFrom: null,
    validUntil: '2099-01-01T00:00',
    delegateVoting: false,
    active: true,
    ...over,
  };
}

async function setup(seed: Delegation[] = []) {
  const create = jest.fn((input) => of(makeDelegation({ id: 'del-new', ...input })));
  const revoke = jest.fn(() => of(void 0));
  const api = { list: jest.fn(() => of(seed)), create, revoke };
  const view = await render(DelegationsComponent, {
    providers: [{ provide: DelegationApiService, useValue: api }],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, create, revoke, c };
}

describe('DelegationsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the empty state with no delegations', async () => {
    await setup();
    expect(screen.getByText('Keine Delegationen vorhanden.')).toBeInTheDocument();
  });

  it('blocks submit until recipient, role and a future end date are set', async () => {
    const { c, create } = await setup();
    expect(c.errors()).toContain('admin.deleg.errRequired');

    // past end date → future error
    c.draft.set({
      principalId: 'p-9',
      roleId: 'r-9',
      gremiumId: '',
      validFrom: '',
      validUntil: '2000-01-01T00:00',
      delegateVoting: false,
    });
    expect(c.errors()).toContain('admin.deleg.errFuture');
    c.create();
    expect(create).not.toHaveBeenCalled();

    // valid → create called, list prepended, draft reset
    c.draft.set({
      principalId: 'p-9',
      roleId: 'r-9',
      gremiumId: ' g-1 ',
      validFrom: '',
      validUntil: '2099-01-01T00:00',
      delegateVoting: true,
    });
    expect(c.errors()).toEqual([]);
    c.create();
    expect(create).toHaveBeenCalledTimes(1);
    expect(create.mock.calls[0][0].gremiumId).toBe('g-1'); // getrimmt
    expect(create.mock.calls[0][0].delegateVoting).toBe(true);
    expect(c.delegations()).toHaveLength(1);
    expect(c.draft().principalId).toBe('');
  });

  it('renders an active badge and revokes a delegation', async () => {
    const { c, revoke } = await setup([makeDelegation()]);
    expect(screen.getByText('Aktiv')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /Widerrufen p-1/ }),
    ).toBeInTheDocument();
    c.revoke('del-1');
    expect(revoke).toHaveBeenCalledWith('del-1');
    expect(c.delegations()).toEqual([]);
  });

  it('shows an expired badge for an inactive delegation', async () => {
    await setup([makeDelegation({ active: false, validUntil: '2000-01-01T00:00' })]);
    expect(screen.getByText('Abgelaufen')).toBeInTheDocument();
  });

  it('translates validation keys via tr()', async () => {
    const { c } = await setup();
    expect(c.tr('admin.deleg.errRequired')).toContain('erforderlich');
  });
});
