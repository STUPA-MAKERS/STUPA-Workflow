import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { API_BASE_URL } from '@core/api/api.config';
import type { DelegationRecipient } from '@core/api/delegations.service';
import type { Attendance } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { DELEGATION_CONTEXT } from '../../../../testing/meeting-fixtures';
import { LeadSubstituteDialogComponent } from './lead-substitute-dialog.component';

const BASE = '/api';
const POOL_URL = `${BASE}/delegations/meetings/m-1/recipients?delegatorId=pr-5`;
const CONTEXT_URL = `${BASE}/delegations/meetings/m-1/context`;

const FRITZ: Attendance = {
  principalId: 'pr-5', displayName: 'Fritz Fehlend', email: null, status: 'absent', source: 'lead', note: null, isSelf: false,
};

function sub(id: string, name: string | null, isMember = false): DelegationRecipient {
  return { principalId: id, displayName: name, viaPool: true, isMember };
}

const CTX = { ...DELEGATION_CONTEXT, allowVoteDelegation: true, votingDelegationEnabled: true };

const POOL = [sub('s-1', 'Paula Persönlich'), sub('s-2', 'Sven Stellvertreter', true)];

const toast = { success: jest.fn(), error: jest.fn() };

async function setup(member: Attendance | null = FRITZ) {
  toast.success.mockReset();
  toast.error.mockReset();
  const closed = jest.fn();
  const created = jest.fn();
  const view = await render(LeadSubstituteDialogComponent, {
    inputs: { meetingId: 'm-1', member },
    on: { closed, created },
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
      { provide: ToastService, useValue: toast },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const dialog = () => screen.getByRole('dialog', { name: 'Vertretung eintragen' });
  const submit = () => within(dialog()).getByRole('button', { name: 'Vertretung eintragen' });
  /** Answer the two loads of an opening. */
  const answer = (pool: DelegationRecipient[] = POOL, context = CTX) => {
    http.expectOne(POOL_URL).flush(pool);
    http.expectOne(CONTEXT_URL).flush(context);
    view.fixture.detectChanges();
  };
  return { ...view, http, closed, created, dialog, submit, answer };
}

describe('LeadSubstituteDialogComponent', () => {
  it('stays closed and loads nothing without a member', async () => {
    const { http } = await setup(null);
    expect(screen.queryByRole('dialog')).toBeNull();
    http.verify();
  });

  it('lists the pool of the member and enters the pick with the vote', async () => {
    const { dialog, submit, answer, http, created } = await setup();
    expect(within(dialog()).getByText('für Fritz Fehlend')).toBeInTheDocument();
    expect(within(dialog()).getByText('Lädt …')).toBeInTheDocument();
    answer();
    const group = within(dialog()).getByRole('radiogroup', { name: 'Stellvertretung aus dem Pool' });
    expect(within(group).getAllByRole('radio')).toHaveLength(2);
    expect(within(group).getByText('Stellvertretung')).toBeInTheDocument();
    expect(within(group).getByText('Mitglied')).toBeInTheDocument();
    // Few substitutes: no search field.
    expect(within(dialog()).queryByRole('searchbox')).toBeNull();
    expect(within(dialog()).getByText('Die Vertretung stimmt für Fritz Fehlend ab.')).toBeInTheDocument();
    expect(submit()).toBeDisabled();
    await userEvent.click(within(group).getByRole('radio', { name: /Paula Persönlich/ }));
    await userEvent.click(submit());
    const req = http.expectOne(`${BASE}/delegations`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      meetingId: 'm-1', delegatorId: 'pr-5', delegateId: 's-1', delegateVoting: true,
    });
    req.flush({ id: 'd-9' });
    expect(toast.success).toHaveBeenCalledWith('Vertretung eingetragen.');
    expect(created).toHaveBeenCalledWith({ id: 'd-9' });
  });

  it('sends no vote when the switch is off or the platform has no vote transfer', async () => {
    const { dialog, submit, answer, http, fixture } = await setup();
    answer();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Sven/ }));
    await userEvent.click(within(dialog()).getByRole('switch', { name: 'Stimmrecht mit übertragen' }));
    expect(within(dialog()).getByText('Die Vertretung nimmt teil, stimmt aber nicht ab.')).toBeInTheDocument();
    await userEvent.click(submit());
    const first = http.expectOne(`${BASE}/delegations`);
    expect(first.request.body.delegateVoting).toBe(false);
    first.flush({ id: 'd-1' });

    // A new opening starts again with the vote on; without a vote transfer there is no switch.
    fixture.componentRef.setInput('member', { ...FRITZ, principalId: 'pr-4', displayName: null, email: 'v@x.de' });
    fixture.detectChanges();
    http.expectOne(`${BASE}/delegations/meetings/m-1/recipients?delegatorId=pr-4`).flush(POOL);
    http.expectOne(CONTEXT_URL).flush({ ...CTX, votingDelegationEnabled: false });
    fixture.detectChanges();
    expect(within(dialog()).getByText('für v@x.de')).toBeInTheDocument();
    expect(within(dialog()).queryByRole('switch')).toBeNull();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Paula/ }));
    await userEvent.click(submit());
    expect(http.expectOne(`${BASE}/delegations`).request.body.delegateVoting).toBe(false);
  });

  it('says when the pool of the member is empty or does not load', async () => {
    const { dialog, answer, http, fixture } = await setup();
    answer([]);
    expect(
      within(dialog()).getByText('Für Fritz Fehlend ist niemand im Stellvertretungs-Pool eingetragen.'),
    ).toBeInTheDocument();

    fixture.componentRef.setInput('member', { ...FRITZ, principalId: 'pr-9', displayName: null });
    fixture.detectChanges();
    http
      .expectOne(`${BASE}/delegations/meetings/m-1/recipients?delegatorId=pr-9`)
      .flush(null, { status: 403, statusText: 'Forbidden' });
    http.expectOne(CONTEXT_URL).flush(null, { status: 500, statusText: 'Error' });
    fixture.detectChanges();
    expect(within(dialog()).getByText('für —')).toBeInTheDocument();
    expect(within(dialog()).getByText('Der Pool konnte nicht geladen werden.')).toBeInTheDocument();
    // Without the context the vote transfer counts as off.
    expect(within(dialog()).queryByRole('switch')).toBeNull();
  });

  it('ignores a pool answer for a member who is no longer picked', async () => {
    const { dialog, http, fixture } = await setup();
    const stale = http.expectOne(POOL_URL);
    http.expectOne(CONTEXT_URL).flush(CTX);
    fixture.componentRef.setInput('member', null);
    fixture.detectChanges();
    stale.flush(POOL);
    expect(screen.queryByRole('dialog')).toBeNull();
    fixture.componentRef.setInput('member', FRITZ);
    fixture.detectChanges();
    http.expectOne(POOL_URL).flush([sub('s-3', null)]);
    http.expectOne(CONTEXT_URL).flush(CTX);
    fixture.detectChanges();
    expect(within(dialog()).getAllByRole('radio')).toHaveLength(1);
    expect(within(dialog()).getByText('Ohne Namen')).toBeInTheDocument();
  });

  it('ignores late answers of an earlier opening in a dialog that is open for another member', async () => {
    const { dialog, http, fixture } = await setup();
    const stalePool = http.expectOne(POOL_URL);
    const staleContext = http.expectOne(CONTEXT_URL);
    fixture.componentRef.setInput('member', { ...FRITZ, principalId: 'pr-4', displayName: 'Vera' });
    fixture.detectChanges();
    const pool = http.expectOne(`${BASE}/delegations/meetings/m-1/recipients?delegatorId=pr-4`);
    const context = http.expectOne(CONTEXT_URL);
    // The answers for Fritz fail late; they must not mark the pool of Vera as failed.
    stalePool.flush(null, { status: 500, statusText: 'Error' });
    staleContext.flush(null, { status: 500, statusText: 'Error' });
    fixture.detectChanges();
    expect(within(dialog()).queryByText('Der Pool konnte nicht geladen werden.')).toBeNull();
    expect(within(dialog()).getByText('Lädt …')).toBeInTheDocument();
    pool.flush(POOL);
    context.flush(CTX);
    fixture.detectChanges();
    expect(within(dialog()).getAllByRole('radio')).toHaveLength(2);
    expect(within(dialog()).getByText('Die Vertretung stimmt für Vera ab.')).toBeInTheDocument();
  });

  it('ignores a late context of an earlier opening', async () => {
    const { dialog, http, fixture } = await setup();
    http.expectOne(POOL_URL).flush(POOL);
    const staleContext = http.expectOne(CONTEXT_URL);
    fixture.componentRef.setInput('member', { ...FRITZ, principalId: 'pr-4', displayName: 'Vera' });
    fixture.detectChanges();
    http.expectOne(`${BASE}/delegations/meetings/m-1/recipients?delegatorId=pr-4`).flush(POOL);
    const context = http.expectOne(CONTEXT_URL);
    context.flush({ ...CTX, allowVoteDelegation: true });
    // The late context of Fritz says "no delegation"; Vera's dialog keeps its own gates.
    staleContext.flush({ ...CTX, allowVoteDelegation: false });
    fixture.detectChanges();
    expect(within(dialog()).queryByText('Dieses Gremium lässt keine Vertretung zu.')).toBeNull();
  });

  it('turns the rows off when the gremium allows no delegation', async () => {
    const { dialog, submit, answer } = await setup();
    answer(POOL, { ...CTX, allowVoteDelegation: false });
    expect(within(dialog()).getByRole('status')).toHaveTextContent('Dieses Gremium lässt keine Vertretung zu.');
    for (const radio of within(dialog()).getAllByRole('radio')) expect(radio).toBeDisabled();
    expect(submit()).toBeDisabled();
  });

  it('searches a long pool', async () => {
    const { dialog, answer } = await setup();
    answer([
      sub('a', 'Anna'), sub('b', 'Bert'), sub('c', 'Carla'), sub('d', 'Dora'), sub('e', 'Emil'), sub('f', 'Fiona'),
    ]);
    const search = within(dialog()).getByRole('searchbox', { name: 'Stellvertretung suchen' });
    await userEvent.type(search, 'ber');
    expect(within(dialog()).getAllByRole('radio')).toHaveLength(1);
    await userEvent.type(search, 'zzz');
    expect(within(dialog()).getByText('Kein Mitglied gefunden.')).toBeInTheDocument();
  });

  it('reports a refusal of the server and closes on cancel', async () => {
    const { dialog, submit, answer, http, closed, created } = await setup();
    answer();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Paula/ }));
    await userEvent.click(submit());
    http
      .expectOne(`${BASE}/delegations`)
      .flush({ detail: 'Recipient must be a pool substitute of the member.' }, { status: 403, statusText: 'Forbidden' });
    // The English detail of the server never reaches the toast.
    expect(toast.error).toHaveBeenCalledWith('Vertretung konnte nicht eingetragen werden.');
    expect(toast.error).not.toHaveBeenCalledWith('Recipient must be a pool substitute of the member.');
    await userEvent.click(submit());
    http.expectOne(`${BASE}/delegations`).flush(null, { status: 500, statusText: 'Error' });
    expect(toast.error).toHaveBeenLastCalledWith('Vertretung konnte nicht eingetragen werden.');
    expect(created).not.toHaveBeenCalled();
    await userEvent.click(within(dialog()).getAllByRole('button', { name: 'Abbrechen' })[0]);
    expect(closed).toHaveBeenCalled();
  });
});
