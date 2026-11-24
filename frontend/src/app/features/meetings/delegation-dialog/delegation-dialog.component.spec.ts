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
import { toastMock } from '../../../../testing/toast';

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

const toast = toastMock();

async function setup(context: MeetingDelegationContext = ctx()) {
  toast.success.mockReset();
  toast.error.mockReset();
  const closed = jest.fn();
  const created = jest.fn();
  const view = await render(DelegationDialogComponent, {
    inputs: { open: true, context },
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
  /** A member without a name has a placeholder, never an id. */
  it('lists the own substitutes apart from the other members', async () => {
    const { dialog, group } = await setup();
    const subs = group('Deine Stellvertretung');
    expect(within(subs).getAllByRole('radio')).toHaveLength(2);
    expect(within(subs).getAllByText('Stellvertretung')).toHaveLength(2);
    const others = group('Andere Mitglieder');
    expect(within(others).getAllByRole('radio')).toHaveLength(3);
    expect(within(others).getByText('Mara Keller')).toBeInTheDocument();
    expect(within(others).getByText('Ohne Namen')).toBeInTheDocument();
    expect(within(dialog()).getByText(/^bis .*13\.10\.2026/)).toBeInTheDocument();
  });

  it('leaves the substitute group out when the member has none', async () => {
    const { dialog } = await setup(ctx({ recipients: [person({ principalId: 'm-1', displayName: 'Mara Keller' })] }));
    expect(within(dialog()).queryByRole('radiogroup', { name: 'Deine Stellvertretung' })).toBeNull();
  });

  /** A click on a row that is off picks nothing. */
  it('turns the other members off after the deadline, but keeps the substitutes', async () => {
    const { dialog, group } = await setup(ctx({ deadlinePassed: true }));
    expect(within(dialog()).getByText(/^Frist abgelaufen/)).toBeInTheDocument();
    within(group('Andere Mitglieder'))
      .getAllByRole('radio')
      .forEach((r) => expect(r).toBeDisabled());
    expect(within(dialog()).getByRole('searchbox', { name: 'Mitglied suchen' })).toBeEnabled();
    within(group('Deine Stellvertretung'))
      .getAllByRole('radio')
      .forEach((r) => expect(r).toBeEnabled());
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

  /**
   * The search waits 250 ms with a timer, so the test advances the jest fake timers. A failed
   * search falls back to the members that match on the client; an empty search asks nobody.
   */
  it('asks the server when external substitutes are allowed', async () => {
    jest.useFakeTimers();
    try {
      const { dialog, group, http, fixture } = await setup(ctx({ delegationAllowExternal: true }));
      const box = within(dialog()).getByRole('searchbox', { name: 'Mitglied suchen' });
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

  /** 002900 and 002904: no switch, one line says that the vote moves, the body has no choice. */
  it('always transfers the vote and says so', async () => {
    const { dialog, http, created } = await setup();
    const submit = () => within(dialog()).getByRole('button', { name: 'Vertretung einrichten' });
    expect(submit()).toBeDisabled();
    expect(within(dialog()).queryByRole('switch')).toBeNull();
    expect(within(dialog()).getByText('Die Vertretung stimmt für dich ab.')).toBeInTheDocument();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Emma Vogel/ }));
    await userEvent.click(submit());
    const req = http.expectOne(`${BASE}/delegations`);
    expect(req.request.body).toEqual({ meetingId: 'mt-1', delegateId: 's-1' });
    req.flush({ id: 'd-9' });
    expect(created).toHaveBeenCalledWith({ id: 'd-9' });
    expect(toast.success).toHaveBeenCalledWith('Vertretung eingerichtet.');
  });

  /** 002902: the search sits above the scroll box and filters both groups. */
  it('pins the search above the list and filters the substitutes too', async () => {
    const { dialog, group } = await setup();
    const box = within(dialog()).getByRole('searchbox', { name: 'Mitglied suchen' });
    const list = within(dialog()).getByTestId('delegation-list');
    expect(list.contains(box)).toBe(false);
    expect(list.contains(group('Deine Stellvertretung'))).toBe(true);
    expect(list.contains(group('Andere Mitglieder'))).toBe(true);
    await userEvent.type(box, 'emma');
    expect(within(group('Deine Stellvertretung')).getAllByRole('radio')).toHaveLength(1);
    expect(within(dialog()).queryByRole('radiogroup', { name: 'Andere Mitglieder' })).toBeNull();
  });

  it('marks the chosen row with a check', async () => {
    const { dialog } = await setup();
    const radio = within(dialog()).getByRole('radio', { name: /Mara Keller/ });
    await userEvent.click(radio);
    expect(radio.closest('label')?.querySelector('.dd__check')).not.toBeNull();
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

  it('says in the language of the page that the person holds the most delegations', async () => {
    const { dialog, http } = await setup();
    await userEvent.click(within(dialog()).getByRole('radio', { name: /Mara Keller/ }));
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Vertretung einrichten' }));
    http
      .expectOne(`${BASE}/delegations`)
      .flush({ code: 'delegate_limit', detail: 'Recipient already holds' }, { status: 409, statusText: 'Conflict' });
    expect(toast.error).toHaveBeenCalledWith(
      'Diese Person vertritt in dieser Sitzung schon die Höchstzahl an Mitgliedern.',
    );
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
