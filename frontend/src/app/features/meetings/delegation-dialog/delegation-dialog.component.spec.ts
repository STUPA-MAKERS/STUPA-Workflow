import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { API_BASE_URL } from '@core/api/api.config';
import type { DelegationRecipient, MeetingDelegationContext } from '@core/api/delegations.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { DelegationDialogComponent } from './delegation-dialog.component';

const BASE = '/api';

function person(over: Partial<DelegationRecipient>): DelegationRecipient {
  return { principalId: 'x', displayName: 'X', viaPool: false, isMember: true, ...over };
}

const RECIPIENTS: DelegationRecipient[] = [
  person({ principalId: 's-1', displayName: 'Emma Vogel', viaPool: true, isMember: false }),
  person({ principalId: 's-2', displayName: 'Lukas Frey', viaPool: true, isMember: true }),
  person({ principalId: 'm-1', displayName: 'Mara Keller' }),
  person({ principalId: 'm-2', displayName: 'Jonas Weber' }),
  person({ principalId: 'm-3', displayName: null }),
];

function ctx(over: Partial<MeetingDelegationContext> = {}): MeetingDelegationContext {
  return {
    meetingId: 'mt-1',
    gremiumId: 'g-1',
    allowVoteDelegation: true,
    votingDelegationEnabled: true,
    delegationAllowExternal: false,
    deadline: '2026-10-13T15:00:00Z',
    deadlinePassed: false,
    meetingStarted: false,
    canDelegate: true,
    myDelegation: null,
    incoming: [],
    recipients: RECIPIENTS,
    ...over,
  };
}

const toast = { success: jest.fn(), error: jest.fn() };

async function setup(context: MeetingDelegationContext = ctx()) {
  toast.success.mockReset();
  toast.error.mockReset();
  const closed = jest.fn();
  const created = jest.fn();
  const view = await render(DelegationDialogComponent, {
    inputs: { open: true, context, subtitle: '35. Sitzung · Di., 13.10.2026' },
    on: { closed, created },
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
      { provide: ToastService, useValue: toast },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const dialog = () => screen.getByRole('dialog', { name: 'Vertretung einrichten' });
  const group = (name: string) => within(dialog()).getByRole('radiogroup', { name });
  return { ...view, http, closed, created, dialog, group };
}

describe('DelegationDialogComponent', () => {
  it('lists the own substitutes apart from the other members', async () => {
    const { dialog, group } = await setup();
    expect(within(dialog()).getByText('35. Sitzung · Di., 13.10.2026')).toBeInTheDocument();
    const subs = group('Deine Stellvertretung');
    expect(within(subs).getAllByRole('radio')).toHaveLength(2);
    expect(within(subs).getAllByText('Stellvertretung')).toHaveLength(2);
    expect(within(dialog()).getByText('Stellvertretungen vertreten dich ohne Vorlauf bis Sitzungsbeginn.')).toBeInTheDocument();
    const others = group('Andere Mitglieder');
    expect(within(others).getAllByRole('radio')).toHaveLength(3);
    expect(within(others).getByText('Mara Keller')).toBeInTheDocument();
    // A member without a name has a placeholder, never an id.
    expect(within(others).getByText('Ohne Namen')).toBeInTheDocument();
    expect(within(dialog()).getByText(/^bis .*13\.10\.2026/)).toBeInTheDocument();
  });

  it('leaves the substitute group out when the member has none', async () => {
    const { dialog } = await setup(ctx({ recipients: [person({ principalId: 'm-1', displayName: 'Mara Keller' })] }));
    expect(within(dialog()).queryByRole('radiogroup', { name: 'Deine Stellvertretung' })).toBeNull();
  });

  it('turns the other members off after the deadline, but keeps the substitutes', async () => {
    const { dialog, group } = await setup(ctx({ deadlinePassed: true }));
    expect(within(dialog()).getByText(/^Frist abgelaufen/)).toBeInTheDocument();
    within(group('Andere Mitglieder'))
      .getAllByRole('radio')
      .forEach((r) => expect(r).toBeDisabled());
    expect(within(dialog()).getByRole('searchbox', { name: 'Mitglied suchen' })).toBeDisabled();
    within(group('Deine Stellvertretung'))
      .getAllByRole('radio')
      .forEach((r) => expect(r).toBeEnabled());
    // A click on a row that is off picks nothing.
    fireEvent.change(within(group('Andere Mitglieder')).getAllByRole('radio')[0]);
    expect(within(dialog()).getByRole('button', { name: 'Vertretung einrichten' })).toBeDisabled();
  });

  it('shows no deadline without one', async () => {
    const { dialog } = await setup(ctx({ deadline: null }));
    expect(within(dialog()).queryByText(/^bis /)).toBeNull();
  });

  it('filters the members by name on the client when externals are off', async () => {
    const { dialog, group, http } = await setup();
    await userEvent.type(within(dialog()).getByRole('searchbox', { name: 'Mitglied suchen' }), 'jon');
    expect(within(group('Andere Mitglieder')).getAllByRole('radio')).toHaveLength(1);
    expect(within(group('Andere Mitglieder')).getByText('Jonas Weber')).toBeInTheDocument();
    await userEvent.type(within(dialog()).getByRole('searchbox', { name: 'Mitglied suchen' }), 'xyz');
    expect(within(dialog()).getByText('Kein Mitglied gefunden.')).toBeInTheDocument();
    http.verify();
  });

  it('asks the server when external substitutes are allowed', async () => {
    jest.useFakeTimers();
    try {
      const { dialog, group, http, fixture } = await setup(ctx({ delegationAllowExternal: true }));
      const box = within(dialog()).getByRole('searchbox', { name: 'Mitglied suchen' });
      // RxJS debounceTime(250) uses setTimeout, so advance the jest fake timers.
      fireEvent.input(box, { target: { value: 'ext' } });
      await jest.advanceTimersByTimeAsync(260);
      http.expectOne(`${BASE}/delegations/meetings/mt-1/recipients?q=ext`).flush([
        person({ principalId: 'e-1', displayName: 'Eva Extern', isMember: false }),
        person({ principalId: 's-1', displayName: 'Emma Vogel', viaPool: true }),
      ]);
      fixture.detectChanges();
      const others = within(group('Andere Mitglieder'));
      expect(others.getAllByRole('radio')).toHaveLength(1);
      expect(others.getByText('Extern')).toBeInTheDocument();
      // A failed search falls back to the members that match on the client; an empty
      // search asks nobody.
      fireEvent.input(box, { target: { value: 'boom' } });
      await jest.advanceTimersByTimeAsync(260);
      http
        .expectOne(`${BASE}/delegations/meetings/mt-1/recipients?q=boom`)
        .flush({}, { status: 500, statusText: 'Error' });
      fixture.detectChanges();
      expect(within(dialog()).getByText('Kein Mitglied gefunden.')).toBeInTheDocument();
      fireEvent.input(box, { target: { value: ' ' } });
      await jest.advanceTimersByTimeAsync(260);
      http.verify();
    } finally {
      jest.useRealTimers();
    }
  });

  it('sends the pick with the voting right and says what the switch means', async () => {
    const { dialog, http, created } = await setup();
    const submit = () => within(dialog()).getByRole('button', { name: 'Vertretung einrichten' });
    expect(submit()).toBeDisabled();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Emma Vogel/ }));
    expect(within(dialog()).getByText('Die Vertretung nimmt ohne Stimmrecht teil. Dein Stimmrecht bleibt bei dir.')).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('switch', { name: 'Stimmrecht mit übertragen' }));
    expect(within(dialog()).getByText('Die Vertretung stimmt für dich ab. Du selbst stimmst in dieser Sitzung nicht ab.')).toBeInTheDocument();
    await userEvent.click(submit());
    const req = http.expectOne(`${BASE}/delegations`);
    expect(req.request.body).toEqual({ meetingId: 'mt-1', delegateId: 's-1', delegateVoting: true });
    req.flush({ id: 'd-9' });
    expect(created).toHaveBeenCalledWith({ id: 'd-9' });
    expect(toast.success).toHaveBeenCalledWith('Vertretung eingerichtet.');
  });

  it('sends no voting right when the server turned the transfer off', async () => {
    const { dialog, http } = await setup(ctx({ votingDelegationEnabled: false }));
    expect(within(dialog()).queryByRole('switch')).toBeNull();
    expect(within(dialog()).getByText(/Die Übertragung des Stimmrechts ist serverseitig deaktiviert/)).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Mara Keller/ }));
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Vertretung einrichten' }));
    expect(http.expectOne(`${BASE}/delegations`).request.body.delegateVoting).toBe(false);
  });

  it('shows the reason of a refusal and keeps the dialog', async () => {
    const { dialog, http, created } = await setup();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Mara Keller/ }));
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Vertretung einrichten' }));
    http.expectOne(`${BASE}/delegations`).flush({ detail: 'Frist abgelaufen' }, { status: 409, statusText: 'Conflict' });
    expect(toast.error).toHaveBeenCalledWith('Frist abgelaufen');
    expect(created).not.toHaveBeenCalled();
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Vertretung einrichten' }));
    http.expectOne(`${BASE}/delegations`).flush(null, { status: 500, statusText: 'Error' });
    expect(toast.error).toHaveBeenLastCalledWith('Vertretung konnte nicht eingerichtet werden.');
  });

  it('closes on cancel and starts empty on the next opening', async () => {
    const { dialog, closed, fixture } = await setup();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Mara Keller/ }));
    const cancel = within(dialog()).getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(cancel[cancel.length - 1]);
    expect(closed).toHaveBeenCalled();
    fixture.componentRef.setInput('open', false);
    fixture.detectChanges();
    fixture.componentRef.setInput('open', true);
    fixture.detectChanges();
    expect(within(dialog()).getByRole('button', { name: 'Vertretung einrichten' })).toBeDisabled();
  });
});
