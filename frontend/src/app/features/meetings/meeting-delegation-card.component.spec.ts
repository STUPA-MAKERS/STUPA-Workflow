import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render } from '@testing-library/angular';
import { API_BASE_URL } from '@core/api/api.config';
import type {
  Delegation,
  DelegationRecipient,
  MeetingDelegationContext,
} from '@core/api/delegations.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { MeetingDelegationCardComponent } from './meeting-delegation-card.component';

const BASE = '/api';

function recipient(over: Partial<DelegationRecipient> = {}): DelegationRecipient {
  return {
    principalId: 'r-1',
    displayName: 'Recipient One',
    viaPool: false,
    isMember: true,
    ...over,
  };
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
    delegatorName: 'Delegator',
    delegateId: 'r-1',
    delegateName: 'Recipient One',
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

interface CardInternals {
  ctx: ReturnType<typeof Object>;
  dialogOpen: { (): boolean; set(v: boolean): void };
  busy: { (): boolean; set(v: boolean): void };
  delegateId: { (): string; set(v: string): void };
  delegateVoting: { (): boolean; set(v: boolean): void };
  query: { (): string; set(v: string): void };
  searched: { (): DelegationRecipient[] | null; set(v: DelegationRecipient[] | null): void };
  visible(): boolean;
  canCreate(): boolean;
  recipientOptions(): { value: string; label: string }[];
  selectedRecipient(): DelegationRecipient | null;
  openDialog(): void;
  search(q: string): void;
  create(): void;
  revoke(d: Delegation): void;
}

const toast = {
  success: jest.fn(),
  error: jest.fn(),
  info: jest.fn(),
};

async function setup(meetingId = 'm-1') {
  toast.success.mockReset();
  toast.error.mockReset();
  const view = await render(MeetingDelegationCardComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
      { provide: ToastService, useValue: toast },
    ],
    inputs: { meetingId },
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const cmp = view.fixture.componentInstance as unknown as CardInternals;
  return { ...view, http, cmp };
}

/** Den initialen Kontext-GET (vom effect) mit `body` beantworten. */
function flushContext(http: HttpTestingController, body: MeetingDelegationContext | null): void {
  const req = http.expectOne(`${BASE}/delegations/meetings/m-1/context`);
  if (body) req.flush(body);
  else req.flush({ detail: 'no' }, { status: 403, statusText: 'Forbidden' });
}

describe('MeetingDelegationCardComponent', () => {
  it('loads the meeting context on init and keeps the card hidden when delegation is off', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ allowVoteDelegation: false }));
    expect(cmp.visible()).toBe(false);
    http.verify();
  });

  it('shows the card when the user may delegate', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx());
    expect(cmp.visible()).toBe(true);
    expect(cmp.canCreate()).toBe(true);
  });

  it('shows the card when an outgoing delegation exists even without create rights', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ canDelegate: false, myDelegation: delegation() }));
    expect(cmp.visible()).toBe(true);
    expect(cmp.canCreate()).toBe(false);
  });

  it('shows the card when an incoming delegation exists', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ canDelegate: false, incoming: [delegation({ direction: 'incoming' })] }));
    expect(cmp.visible()).toBe(true);
  });

  it('hides the card and disables create when context fails to load', async () => {
    const { http, cmp } = await setup();
    flushContext(http, null);
    expect(cmp.ctx()).toBeNull();
    expect(cmp.visible()).toBe(false);
    expect(cmp.canCreate()).toBe(false);
    expect(cmp.recipientOptions()).toEqual([]);
    expect(cmp.selectedRecipient()).toBeNull();
  });

  it('blocks creation once the meeting has started', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ meetingStarted: true }));
    expect(cmp.canCreate()).toBe(false);
  });

  it('keeps the window open before the deadline', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ deadline: '2026-06-30T00:00:00Z', deadlinePassed: false }));
    expect(cmp.canCreate()).toBe(true);
  });

  it('closes the window after the deadline when no pool recipient is left', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ deadlinePassed: true, recipients: [recipient({ viaPool: false })] }));
    expect(cmp.canCreate()).toBe(false);
  });

  it('keeps the window open after the deadline if a pool recipient remains', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ deadlinePassed: true, recipients: [recipient({ viaPool: true })] }));
    expect(cmp.canCreate()).toBe(true);
  });

  it('builds recipient options from the context, appending a pool suffix', async () => {
    const { http, cmp } = await setup();
    flushContext(
      http,
      ctx({
        recipients: [
          recipient({ principalId: 'r-1', displayName: 'Alice', viaPool: false }),
          recipient({ principalId: 'r-2', displayName: 'Bob', viaPool: true }),
          recipient({ principalId: 'r-3', displayName: null, viaPool: false }),
        ],
      }),
    );
    const opts = cmp.recipientOptions();
    expect(opts[0]).toEqual({ value: 'r-1', label: 'Alice' });
    // Pool-Empfänger trägt das Suffix.
    expect(opts[1].label).toContain('Bob');
    expect(opts[1].label).not.toBe('Bob');
    // Ohne displayName fällt das Label auf die principalId zurück.
    expect(opts[2].label).toBe('r-3');
  });

  it('resolves the selected recipient from the context list', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ recipients: [recipient({ principalId: 'r-9' })] }));
    expect(cmp.selectedRecipient()).toBeNull();
    cmp.delegateId.set('r-9');
    expect(cmp.selectedRecipient()?.principalId).toBe('r-9');
  });

  it('opens the dialog and resets all dialog state', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx());
    cmp.delegateId.set('r-1');
    cmp.delegateVoting.set(true);
    cmp.query.set('foo');
    cmp.searched.set([recipient()]);
    cmp.openDialog();
    expect(cmp.dialogOpen()).toBe(true);
    expect(cmp.delegateId()).toBe('');
    expect(cmp.delegateVoting()).toBe(false);
    expect(cmp.query()).toBe('');
    expect(cmp.searched()).toBeNull();
  });

  it('debounces server-side name search and stores the results', async () => {
    jest.useFakeTimers();
    try {
      const { http, cmp } = await setup();
      flushContext(http, ctx({ delegationAllowExternal: true }));
      cmp.search('al');
      cmp.search('ali'); // distinctUntilChanged + debounce → nur die letzte zählt
      // RxJS debounceTime(250) nutzt setTimeout — über jest-Fake-Timer vorspulen.
      await jest.advanceTimersByTimeAsync(260);
      const req = http.expectOne(`${BASE}/delegations/meetings/m-1/recipients?q=ali`);
      expect(req.request.method).toBe('GET');
      const results = [
        recipient({ principalId: 'ext-1', displayName: 'Extern', isMember: false }),
      ];
      req.flush(results);
      expect(cmp.searched()).toEqual(results);
      // recipientOptions/selectedRecipient ziehen jetzt aus den Suchergebnissen.
      expect(cmp.recipientOptions()[0].value).toBe('ext-1');
      cmp.delegateId.set('ext-1');
      expect(cmp.selectedRecipient()?.isMember).toBe(false);
      http.verify();
    } finally {
      jest.useRealTimers();
    }
  });

  it('sets the query signal synchronously on search', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ delegationAllowExternal: true }));
    cmp.search('foo');
    expect(cmp.query()).toBe('foo');
  });

  it('does nothing on create without a selected recipient', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx());
    cmp.create(); // delegateId leer → kein Request
    http.verify();
    expect(cmp.busy()).toBe(false);
  });

  it('does nothing on create while busy', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx());
    cmp.delegateId.set('r-1');
    cmp.busy.set(true);
    cmp.create();
    http.verify();
  });

  it('creates a delegation, toasts success and reloads the context', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx());
    cmp.delegateId.set('r-1');
    cmp.delegateVoting.set(true);
    cmp.openDialog();
    cmp.delegateId.set('r-1');
    cmp.create();
    const req = http.expectOne(`${BASE}/delegations`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ meetingId: 'm-1', delegateId: 'r-1', delegateVoting: false });
    req.flush(delegation());
    expect(cmp.busy()).toBe(false);
    expect(cmp.dialogOpen()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
    // reload() lädt den Kontext erneut.
    http.expectOne(`${BASE}/delegations/meetings/m-1/context`).flush(ctx({ myDelegation: delegation() }));
    expect(cmp.ctx()?.myDelegation).not.toBeNull();
  });

  it('shows the server detail message when create fails', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx());
    cmp.delegateId.set('r-1');
    cmp.create();
    http
      .expectOne(`${BASE}/delegations`)
      .flush({ detail: 'Frist abgelaufen' }, { status: 409, statusText: 'Conflict' });
    expect(cmp.busy()).toBe(false);
    expect(toast.error).toHaveBeenCalledWith('Frist abgelaufen');
  });

  it('falls back to a generic message when create fails without a detail', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx());
    cmp.delegateId.set('r-1');
    cmp.create();
    http
      .expectOne(`${BASE}/delegations`)
      .flush(null, { status: 500, statusText: 'Server Error' });
    expect(toast.error).toHaveBeenCalledTimes(1);
    // Keine konkrete detail-Meldung → generischer i18n-Key.
    expect(toast.error).not.toHaveBeenCalledWith('Frist abgelaufen');
  });

  it('does nothing on revoke while busy', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx());
    cmp.busy.set(true);
    cmp.revoke(delegation());
    http.verify();
  });

  it('revokes a delegation, toasts success and reloads', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ myDelegation: delegation() }));
    cmp.revoke(delegation({ id: 'd-9' }));
    const req = http.expectOne(`${BASE}/delegations/d-9`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
    expect(cmp.busy()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
    http.expectOne(`${BASE}/delegations/meetings/m-1/context`).flush(ctx());
  });

  it('toasts an error when revoke fails', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ myDelegation: delegation() }));
    cmp.revoke(delegation({ id: 'd-9' }));
    http.expectOne(`${BASE}/delegations/d-9`).flush(null, { status: 500, statusText: 'err' });
    expect(cmp.busy()).toBe(false);
    expect(toast.error).toHaveBeenCalled();
  });

  it('ignores a context reload error after revoke', async () => {
    const { http, cmp } = await setup();
    flushContext(http, ctx({ myDelegation: delegation() }));
    cmp.revoke(delegation({ id: 'd-9' }));
    http.expectOne(`${BASE}/delegations/d-9`).flush(null);
    // reload() schluckt Fehler still.
    http
      .expectOne(`${BASE}/delegations/meetings/m-1/context`)
      .flush(null, { status: 500, statusText: 'err' });
    expect(toast.success).toHaveBeenCalled();
  });
});
