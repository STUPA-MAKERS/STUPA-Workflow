import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { MeetingGuest } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { meeting } from '../../../testing/meeting-fixtures';
import { LINK, guestRow } from '../../../testing/guest-fixtures';
import { MeetingGuestsService, guestName } from './meeting-guests.service';

describe('MeetingGuestsService', () => {
  let svc: MeetingGuestsService;
  let api: Record<string, jest.Mock>;
  let toast: { success: jest.Mock; error: jest.Mock };
  const PUBLIC = meeting({ publicJoin: true, joinCode: '7KQ4MP' });

  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    api = {
      listMeetingGuests: jest.fn(() =>
        of([
          guestRow(),
          guestRow({ id: 'g-0', requestedAt: '2026-10-06T16:40:00Z' }),
          guestRow({ id: 'g-2', status: 'admitted', admittedAt: '2026-10-06T16:30:00Z' }),
          guestRow({ id: 'g-3', status: 'left', displayName: null, number: 3 }),
          guestRow({ id: 'g-4', status: 'admitted', admittedAt: '2026-10-06T16:20:00Z' }),
          guestRow({ id: 'g-5', status: 'rejected' }),
        ]),
      ),
      getJoinLink: jest.fn(() => of(LINK)),
      decideMeetingGuest: jest.fn((_m: string, id: string, action: string) =>
        of(guestRow({ id, status: action === 'admit' ? 'admitted' : action === 'reject' ? 'rejected' : 'removed' })),
      ),
      renameMeetingGuest: jest.fn((_m: string, id: string, name: string) =>
        of(guestRow({ id, displayName: name })),
      ),
      admitAllMeetingGuests: jest.fn(() => of([guestRow({ status: 'admitted' })])),
      rotateJoinCode: jest.fn(() => of({ ...LINK, joinCode: '9XH2TR' })),
    };
    toast = { success: jest.fn(), error: jest.fn() };
    TestBed.configureTestingModule({
      providers: [
        MeetingGuestsService,
        { provide: ApiClient, useValue: api },
        { provide: ToastService, useValue: toast },
      ],
    });
    svc = TestBed.inject(MeetingGuestsService);
  });

  it('loads the list and the link only for the lead of a public meeting that is open', () => {
    svc.sync(meeting());
    svc.sync(meeting({ publicJoin: true, canManage: false }));
    svc.sync(meeting({ publicJoin: true, status: 'closed' }));
    svc.sync(null);
    expect(api['listMeetingGuests']).not.toHaveBeenCalled();
    svc.sync(PUBLIC);
    expect(api['listMeetingGuests']).toHaveBeenCalledWith('m-1');
    expect(svc.joinLink()).toEqual(LINK);
    expect(svc.pending().map((g) => g.id)).toEqual(['g-0', 'g-1']);
    expect(svc.listed().map((g) => g.id)).toEqual(['g-4', 'g-2', 'g-3']);
    expect(svc.admittedCount()).toBe(2);
    expect(svc.countsFor(PUBLIC)).toEqual({ pending: 2, admitted: 2 });
    expect(svc.countsFor(meeting({ id: 'm-2', pendingGuests: 5, admittedGuests: 1 }))).toEqual({
      pending: 5,
      admitted: 1,
    });
  });

  it('syncs once per meeting and reads the link again for a new code', () => {
    svc.sync(PUBLIC);
    svc.sync(PUBLIC);
    expect(api['listMeetingGuests']).toHaveBeenCalledTimes(1);
    svc.sync({ ...PUBLIC, joinCode: '9XH2TR' });
    expect(api['getJoinLink']).toHaveBeenCalledTimes(2);
    svc.sync(meeting({ publicJoin: false }));
    expect(svc.meetingId()).toBeNull();
    expect(svc.guests()).toEqual([]);
  });

  it('drops a late answer of a meeting that is no longer open', () => {
    let deliver: (rows: MeetingGuest[]) => void = () => {};
    api['listMeetingGuests'].mockReturnValue({
      subscribe: (o: { next: (r: MeetingGuest[]) => void }) => (deliver = o.next),
    });
    api['getJoinLink'].mockReturnValue({ subscribe: () => {} });
    svc.sync(PUBLIC);
    svc.sync(null);
    deliver([guestRow()]);
    expect(svc.guests()).toEqual([]);
    svc.reload();
    expect(api['listMeetingGuests']).toHaveBeenCalledTimes(1);
  });

  it('keeps silent when a read fails', () => {
    api['listMeetingGuests'].mockReturnValue(throwError(() => new Error('x')));
    api['getJoinLink'].mockReturnValue(throwError(() => new Error('x')));
    svc.sync(PUBLIC);
    expect(svc.guests()).toEqual([]);
    expect(svc.joinLink()).toBeNull();
  });

  it('applies the lead events: a new or changed request, and a voided one', () => {
    svc.apply(guestRow({ id: 'g-9' }));
    expect(svc.guests()).toEqual([]);
    svc.sync(PUBLIC);
    svc.apply(guestRow({ id: 'g-9' }));
    expect(svc.guests().some((g) => g.id === 'g-9')).toBe(true);
    svc.apply(guestRow({ id: 'g-9', status: 'expired' }));
    expect(svc.guests().some((g) => g.id === 'g-9')).toBe(false);
  });

  it('admits, rejects, removes and renames a guest', () => {
    svc.sync(PUBLIC);
    svc.admit(guestRow());
    expect(api['decideMeetingGuest']).toHaveBeenCalledWith('m-1', 'g-1', 'admit');
    svc.reject(guestRow({ id: 'g-0' }));
    expect(api['decideMeetingGuest']).toHaveBeenCalledWith('m-1', 'g-0', 'reject');
    svc.remove(guestRow({ id: 'g-2', status: 'admitted' }));
    expect(api['decideMeetingGuest']).toHaveBeenCalledWith('m-1', 'g-2', 'remove');
    svc.rename(guestRow({ id: 'g-2', status: 'admitted' }), '  Neu Name ');
    expect(api['renameMeetingGuest']).toHaveBeenCalledWith('m-1', 'g-2', 'Neu Name');
    expect(svc.guests().find((g) => g.id === 'g-2')?.displayName).toBe('Neu Name');
    // A short or an unchanged name sends nothing.
    svc.rename(guestRow(), 'J');
    svc.rename(guestRow(), 'Jana Roth');
    expect(api['renameMeetingGuest']).toHaveBeenCalledTimes(1);
  });

  it('does nothing without a meeting or while an action runs', () => {
    svc.admit(guestRow());
    svc.rename(guestRow(), 'Neu');
    svc.admitAll();
    svc.rotate();
    expect(api['decideMeetingGuest']).not.toHaveBeenCalled();
    svc.sync(PUBLIC);
    api['decideMeetingGuest'].mockReturnValue({ subscribe: () => {} });
    svc.admit(guestRow());
    svc.reject(guestRow());
    svc.admitAll();
    svc.rename(guestRow(), 'Neu Name');
    expect(api['decideMeetingGuest']).toHaveBeenCalledTimes(1);
    expect(api['admitAllMeetingGuests']).not.toHaveBeenCalled();
  });

  it('admits every open request at once', () => {
    svc.sync(PUBLIC);
    svc.admitAll();
    expect(api['admitAllMeetingGuests']).toHaveBeenCalledWith('m-1');
    expect(toast.success).toHaveBeenCalledWith('1 Gäste zugelassen.');
    // Nothing open: nothing to send.
    svc.guests.set([]);
    svc.admitAll();
    expect(api['admitAllMeetingGuests']).toHaveBeenCalledTimes(1);
  });

  it('reports a refused action and reads the list again', () => {
    svc.sync(PUBLIC);
    api['decideMeetingGuest'].mockReturnValue(
      throwError(() => ({ error: { code: 'guest_not_pending', detail: 'schon entschieden' } })),
    );
    svc.admit(guestRow());
    expect(toast.error).toHaveBeenCalledWith('Aktion fehlgeschlagen.: schon entschieden');
    expect(api['listMeetingGuests']).toHaveBeenCalledTimes(2);
    expect(svc.busy()).toBeNull();
  });

  it('rotates the join code, drops the open requests and reports a refusal', () => {
    svc.sync(PUBLIC);
    svc.rotate();
    expect(svc.joinLink()?.joinCode).toBe('9XH2TR');
    expect(svc.pending()).toEqual([]);
    expect(toast.success).toHaveBeenCalled();
    // Same code from the meeting again: no second link read.
    svc.sync({ ...PUBLIC, joinCode: '9XH2TR' });
    expect(api['getJoinLink']).toHaveBeenCalledTimes(1);
    api['rotateJoinCode'].mockReturnValue(throwError(() => ({ error: {} })));
    svc.rotate();
    expect(toast.error).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
    expect(svc.rotating()).toBe(false);
  });

  it('ignores a second rotation while one runs', () => {
    svc.sync(PUBLIC);
    api['rotateJoinCode'].mockReturnValue({ subscribe: () => {} });
    svc.rotate();
    svc.rotate();
    expect(api['rotateJoinCode']).toHaveBeenCalledTimes(1);
  });

  it('names a pseudonymized guest "Gast n"', () => {
    const t = (_k: string, p?: Record<string, string | number>) => `Gast ${p?.['n']}`;
    expect(guestName({ displayName: null, number: 4 }, t)).toBe('Gast 4');
    expect(guestName({ displayName: 'Ali', number: 4 }, t)).toBe('Ali');
  });
});
