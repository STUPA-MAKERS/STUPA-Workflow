import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { API_BASE_URL } from '@core/api/api.config';
import type {
  Delegation,
  DelegationRecipient,
  MeetingDelegationContext,
} from '@core/api/delegations.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { MeetingDelegationCardComponent } from './meeting-delegation-card.component';

const BASE = '/api';
const CONTEXT_URL = `${BASE}/delegations/meetings/m-1/context`;

function recipient(over: Partial<DelegationRecipient> = {}): DelegationRecipient {
  return { principalId: 'r-1', displayName: 'Max Mitglied', viaPool: false, isMember: true, ...over };
}

function delegation(over: Partial<Delegation> = {}): Delegation {
  return {
    id: 'd-1',
    meetingId: 'm-1',
    meetingTitle: 'Sitzung',
    meetingDate: '2026-06-12',
    gremiumId: 'g-1',
    gremiumName: 'StuPa',
    delegatorId: 'p-1',
    delegatorName: 'Jonas Weber',
    delegateId: 'r-1',
    delegateName: 'Max Mitglied',
    delegateVoting: false,
    viaPool: false,
    createdAt: '2026-06-01T00:00:00Z',
    revocable: true,
    direction: 'outgoing',
    ...over,
  };
}

function ctx(over: Partial<MeetingDelegationContext> = {}): MeetingDelegationContext {
  return {
    meetingId: 'm-1',
    gremiumId: 'g-1',
    allowVoteDelegation: true,
    votingDelegationEnabled: true,
    delegationAllowExternal: false,
    deadline: null,
    deadlinePassed: false,
    meetingStarted: false,
    canDelegate: true,
    myDelegation: null,
    incoming: [],
    recipients: [recipient()],
    ...over,
  };
}

const toast = { success: jest.fn(), error: jest.fn(), info: jest.fn() };

async function setup(variant: 'section' | 'box' = 'section') {
  toast.success.mockReset();
  toast.error.mockReset();
  const changed = jest.fn();
  const contextChange = jest.fn();
  const view = await render(MeetingDelegationCardComponent, {
    on: { changed, contextChange },
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
      { provide: ToastService, useValue: toast },
    ],
    inputs: { meetingId: 'm-1', variant, subtitle: 'Sitzung · Di., 13.10.2026' },
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const flush = (body: MeetingDelegationContext | null) => {
    const req = http.expectOne(CONTEXT_URL);
    if (body) req.flush(body);
    else req.flush({ detail: 'no' }, { status: 403, statusText: 'Forbidden' });
    view.fixture.detectChanges();
  };
  return { ...view, http, changed, contextChange, flush };
}

describe('MeetingDelegationCardComponent', () => {
  it('stays hidden while delegation is off in the gremium, and reports the context', async () => {
    const { flush, contextChange, http } = await setup();
    const c = ctx({ allowVoteDelegation: false });
    flush(c);
    expect(screen.queryByRole('region', { name: 'Vertretung' })).toBeNull();
    expect(contextChange).toHaveBeenCalledWith(c);
    http.verify();
  });

  it('stays hidden and reports no context when the read fails', async () => {
    const { flush, contextChange } = await setup();
    flush(null);
    expect(screen.queryByRole('region', { name: 'Vertretung' })).toBeNull();
    expect(contextChange).toHaveBeenCalledWith(null);
  });

  it('stays hidden for a member who neither delegates nor represents', async () => {
    const { flush } = await setup();
    flush(ctx({ canDelegate: false }));
    expect(screen.queryByRole('region', { name: 'Vertretung' })).toBeNull();
  });

  it('offers the setup with the deadline as a row of the attendance sheet', async () => {
    const { flush } = await setup();
    flush(ctx({ deadline: '2026-10-13T15:00:00Z' }));
    const section = screen.getByRole('region', { name: 'Vertretung' });
    expect(within(section).getByText(/Du kannst dich für diese Sitzung vertreten lassen/)).toBeInTheDocument();
    expect(within(section).getByText(/^Einrichtbar bis .*13\.10\.2026/)).toBeInTheDocument();
    expect(within(section).getByRole('button', { name: 'Vertretung einrichten' })).toBeInTheDocument();
  });

  it('offers the setup with the deadline as a box of the participant view', async () => {
    const { flush } = await setup('box');
    flush(ctx({ deadline: '2026-10-13T15:00:00Z' }));
    const box = screen.getByRole('region', { name: 'Vertretung' });
    expect(within(box).getByRole('heading', { name: 'Vertretung' })).toBeInTheDocument();
    expect(within(box).getByText(/^Einrichtbar bis .*13\.10\.2026/)).toBeInTheDocument();
    expect(within(box).getByRole('button', { name: 'Vertretung einrichten' })).toBeInTheDocument();
  });

  it('says that only a substitute is left after the deadline', async () => {
    const { flush } = await setup('box');
    flush(ctx({ deadline: '2026-10-13T15:00:00Z', deadlinePassed: true, recipients: [recipient({ viaPool: true })] }));
    expect(screen.getByText(/Bis Sitzungsbeginn ist nur noch eine Stellvertretung möglich/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Vertretung einrichten' })).toBeInTheDocument();
  });

  it.each(['section', 'box'] as const)(
    'closes the setup after the deadline when no substitute is left (%s)',
    async (variant) => {
      const { flush } = await setup(variant);
      flush(ctx({ deadlinePassed: true, recipients: [recipient()] }));
      expect(screen.getByText(/Die Frist ist abgelaufen — nur noch Stellvertreter/)).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Vertretung einrichten' })).toBeNull();
    },
  );

  it('offers no setup once the meeting started', async () => {
    const { flush } = await setup('box');
    flush(ctx({ meetingStarted: true, incoming: [delegation({ direction: 'incoming', delegateVoting: true })] }));
    expect(screen.queryByRole('button', { name: 'Vertretung einrichten' })).toBeNull();
    expect(screen.getByText('Du vertrittst Jonas Weber in dieser Sitzung.')).toBeInTheDocument();
    expect(screen.getByText('mit Stimmrecht')).toBeInTheDocument();
  });

  it('shows the incoming delegations in the sheet', async () => {
    const { flush } = await setup();
    flush(ctx({ canDelegate: false, incoming: [delegation({ direction: 'incoming' })] }));
    expect(screen.getByText('Du vertrittst Jonas Weber in dieser Sitzung.')).toBeInTheDocument();
    expect(screen.queryByText('mit Stimmrecht')).toBeNull();
  });

  it.each(['section', 'box'] as const)(
    'shows the own delegation with its voting right and its pool origin (%s)',
    async (variant) => {
      const { flush } = await setup(variant);
      flush(ctx({ myDelegation: delegation({ delegateVoting: true, viaPool: true }) }));
      expect(screen.getByText('Du wirst vertreten von Max Mitglied.')).toBeInTheDocument();
      expect(screen.getByText('mit Stimmrecht')).toBeInTheDocument();
      expect(screen.getByText('Stellvertretung')).toBeInTheDocument();
    },
  );

  it('names nobody with a dash when the server sends no name', async () => {
    const { flush } = await setup();
    flush(ctx({
      myDelegation: delegation({ delegateName: null, revocable: false }),
      incoming: [delegation({ id: 'd-2', delegatorName: null, direction: 'incoming' })],
    }));
    expect(screen.getByText('Du wirst vertreten von —.')).toBeInTheDocument();
    expect(screen.getByText('Du vertrittst — in dieser Sitzung.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Vertretung widerrufen' })).toBeNull();
  });

  it('revokes the own delegation and reads the context again', async () => {
    const { flush, http, changed } = await setup('box');
    const own = delegation();
    flush(ctx({ myDelegation: own }));
    await userEvent.click(screen.getByRole('button', { name: 'Vertretung widerrufen' }));
    // A second click while the revoke runs sends nothing.
    await userEvent.click(screen.getByRole('button', { name: 'Vertretung widerrufen' }));
    const del = http.expectOne(`${BASE}/delegations/d-1`);
    expect(del.request.method).toBe('DELETE');
    del.flush(null);
    http.expectOne(CONTEXT_URL).flush(ctx());
    expect(toast.success).toHaveBeenCalledWith('Vertretung widerrufen.');
    expect(changed).toHaveBeenCalledWith({ kind: 'revoked', delegation: own });
  });

  it('reports a failed revoke', async () => {
    const { flush, http, changed } = await setup();
    flush(ctx({ myDelegation: delegation() }));
    await userEvent.click(screen.getByRole('button', { name: 'Vertretung widerrufen' }));
    http.expectOne(`${BASE}/delegations/d-1`).flush({}, { status: 409, statusText: 'Conflict' });
    expect(toast.error).toHaveBeenCalledWith('Widerruf fehlgeschlagen.');
    expect(changed).not.toHaveBeenCalled();
  });

  it('opens the dialog, creates the delegation and reads the context again', async () => {
    const { flush, http, changed, fixture } = await setup('box');
    flush(ctx());
    await userEvent.click(screen.getByRole('button', { name: 'Vertretung einrichten' }));
    const dialog = screen.getByRole('dialog', { name: 'Vertretung einrichten' });
    expect(within(dialog).getByText('Sitzung · Di., 13.10.2026')).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('radio', { name: /Max Mitglied/ }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Vertretung einrichten' }));
    http.expectOne((r) => r.method === 'POST').flush(delegation());
    fixture.detectChanges();
    expect(screen.queryByRole('dialog')).toBeNull();
    http.expectOne(CONTEXT_URL).flush(ctx({ myDelegation: delegation() }));
    expect(changed).toHaveBeenCalledWith({ kind: 'created' });
  });

  it('closes the dialog on cancel', async () => {
    const { flush, fixture } = await setup();
    flush(ctx());
    await userEvent.click(screen.getByRole('button', { name: 'Vertretung einrichten' }));
    const cancel = within(screen.getByRole('dialog')).getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(cancel[cancel.length - 1]);
    fixture.detectChanges();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('ignores a failed reload', async () => {
    const { flush, http, fixture, contextChange } = await setup();
    flush(ctx());
    contextChange.mockReset();
    (fixture.componentInstance as MeetingDelegationCardComponent).reload();
    http.expectOne(CONTEXT_URL).flush({}, { status: 500, statusText: 'Error' });
    expect(contextChange).not.toHaveBeenCalled();
  });
});
