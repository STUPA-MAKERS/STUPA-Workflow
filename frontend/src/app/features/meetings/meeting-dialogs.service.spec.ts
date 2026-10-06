import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { USE_MOCK_API } from '@core/api/api.config';
import type { AgendaItem, Meeting } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { WsService } from '@core/ws/ws.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { MeetingAgendaService } from './meeting-agenda.service';
import { MeetingDialogsService } from './meeting-dialogs.service';
import { MeetingSessionService } from './meeting-session.service';
import { MeetingsTimelineService } from './meetings-timeline.service';

const M = (over: Partial<Meeting> = {}): Meeting =>
  ({ id: 'm-1', title: '34. Sitzung', status: 'live', votes: [], ...over }) as Meeting;
const WIRE = { id: 'm-1', title: '34. Sitzung', status: 'live', votes: [], createdAt: 'x' };

function setup() {
  const navigate = jest.fn(() => Promise.resolve(true));
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      MeetingDialogsService,
      MeetingSessionService,
      MeetingAgendaService,
      MeetingsTimelineService,
      { provide: USE_MOCK_API, useValue: true },
      {
        provide: AuthService,
        useValue: {
          can: () => false,
          isAdmin: () => false,
          gremien: () => [],
          inSubstitutePool: () => false,
        },
      },
      { provide: WsService, useValue: {} },
      { provide: Router, useValue: { navigate } },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const svc = TestBed.inject(MeetingDialogsService);
  const session = TestBed.inject(MeetingSessionService);
  const timeline = TestBed.inject(MeetingsTimelineService);
  http.match('/api/meetings/gremien').forEach((r) => r.flush([]));
  const toasts = () => TestBed.inject(ToastService).toasts().map((t) => t.message);
  return { http, svc, session, timeline, navigate, toasts };
}

describe('MeetingDialogsService', () => {
  it('opens and closes the settings and the delete dialog', () => {
    const { svc } = setup();
    svc.openSettings(M());
    expect(svc.settingsMeeting()?.id).toBe('m-1');
    svc.closeSettings();
    expect(svc.settingsMeeting()).toBeNull();
    svc.askDeleteMeeting(M());
    expect(svc.deleteMeeting()?.id).toBe('m-1');
    svc.cancelDelete();
    expect(svc.deleteMeeting()).toBeNull();
  });

  it('puts a saved meeting into the page and the list, but not into another loaded meeting', () => {
    const { svc, session, timeline } = setup();
    timeline.upcomingItems.set([M({ title: 'alt' })]);
    session.meeting.set(M({ id: 'm-2' }));
    svc.openSettings(M());
    svc.settingsSaved(M({ title: 'neu' }));
    expect(svc.settingsMeeting()).toBeNull();
    expect(timeline.upcomingItems()[0].title).toBe('neu');
    expect(session.meeting()?.id).toBe('m-2');
    session.meeting.set(M());
    svc.applyUpdated(M({ title: 'neuer' }));
    expect(session.meeting()?.title).toBe('neuer');
  });

  it('removes a deleted meeting and leaves its page', () => {
    const { svc, session, timeline, navigate } = setup();
    timeline.upcomingItems.set([M()]);
    svc.askDeleteMeeting(M());
    svc.meetingDeleted('m-1');
    expect(svc.deleteMeeting()).toBeNull();
    expect(timeline.upcomingItems()).toEqual([]);
    expect(navigate).not.toHaveBeenCalled();
    session.meeting.set(M());
    svc.meetingDeleted('m-1');
    expect(navigate).toHaveBeenCalledWith(['/meetings']);
  });

  it('takes the closed meeting and the opened vote into the page', () => {
    const { svc, session } = setup();
    session.meeting.set(M());
    svc.closeOpen.set(true);
    svc.meetingClosed(M({ status: 'closed' }));
    expect(svc.closeOpen()).toBe(false);
    expect(session.meeting()?.status).toBe('closed');
    svc.voteItem.set({ id: 't-1' } as AgendaItem);
    svc.voteOpened(M({ votes: [{ id: 'v-1' } as Meeting['votes'][number]] }));
    expect(svc.voteItem()).toBeNull();
    expect(session.meeting()?.votes.length).toBe(1);
  });

  it('names the minute-taker in one PATCH and explains a refusal', () => {
    const { svc, http, toasts } = setup();
    svc.setProtokollant(M({ status: 'planned' }), 'p-1');
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.body).toEqual({ protokollantId: 'p-1' });
    req.flush(WIRE);
    expect(toasts()).toContain('Protokollant gesetzt.');
    svc.setProtokollant(M({ status: 'planned' }), 'p-2');
    http.expectOne('/api/meetings/m-1').flush({ code: 'protokollant_needs_protocol_write' }, { status: 422, statusText: 'x' });
    expect(toasts()).toContain('Diese Person hat im Gremium kein Protokollrecht.');
    svc.setProtokollant(M({ status: 'planned' }), 'p-3');
    http.expectOne('/api/meetings/m-1').flush({ detail: 'gesperrt' }, { status: 409, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.: gesperrt');
    svc.setProtokollant(M({ status: 'planned' }), 'p-4');
    http.expectOne('/api/meetings/m-1').flush(null, { status: 500, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.');
  });

  it('hands the minutes over now or with the next item, and discards a planned handover (Z3)', () => {
    const { svc, http, toasts } = setup();
    const member = { principalId: 'p-2', displayName: 'Mika', email: null, status: null, source: null, note: null, isSelf: false };
    svc.askHandover(member);
    expect(svc.handoverTarget()).toBe(member);
    svc.handOver(M(), 'p-2', 'now');
    expect(svc.handoverSaving()).toBe(true);
    const now = http.expectOne('/api/meetings/m-1/protokollant-handover');
    expect(now.request.body).toEqual({ principalId: 'p-2', mode: 'now' });
    now.flush(WIRE);
    expect(toasts()).toContain('Protokollführung übergeben.');
    // The dialog closes after the handover.
    expect(svc.handoverTarget()).toBeNull();
    expect(svc.handoverSaving()).toBe(false);
    svc.handOver(M(), 'p-2', 'next_item');
    http.expectOne('/api/meetings/m-1/protokollant-handover').flush(WIRE);
    expect(toasts()).toContain('Übergabe mit dem nächsten TOP geplant.');
    svc.cancelHandover(M());
    const cancel = http.expectOne('/api/meetings/m-1/protokollant-handover');
    expect(cancel.request.method).toBe('DELETE');
    cancel.flush(WIRE);
    expect(toasts()).toContain('Geplante Übergabe verworfen.');
    svc.cancelHandover(M());
    http.expectOne('/api/meetings/m-1/protokollant-handover').flush(null, { status: 500, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.');
  });

  it('keeps a refusal the dialog can explain in the dialog (O20, last TOP)', () => {
    const { svc, http, toasts } = setup();
    const member = { principalId: 'p-2', displayName: 'Mika', email: null, status: null, source: null, note: null, isSelf: false };
    for (const [status, code] of [[422, 'protokollant_needs_protocol_write'], [409, 'no_next_item'], [409, 'already_protokollant']] as const) {
      svc.askHandover(member);
      svc.handOver(M(), 'p-2', 'next_item');
      http.expectOne('/api/meetings/m-1/protokollant-handover').flush({ code }, { status, statusText: 'x' });
      expect(svc.handoverRefusal()).toBe(code);
      expect(svc.handoverTarget()).toBe(member);
      expect(svc.handoverSaving()).toBe(false);
    }
    expect(toasts()).toEqual([]);
    // Another refusal is a toast; the dialog stays open.
    svc.handOver(M(), 'p-2', 'now');
    http.expectOne('/api/meetings/m-1/protokollant-handover').flush({ code: 'meeting_not_live', detail: 'nicht live' }, { status: 409, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.: nicht live');
    expect(svc.handoverRefusal()).toBeNull();
    svc.closeHandover();
    expect(svc.handoverTarget()).toBeNull();
  });

  it('names the minute-taker of a planned meeting and explains the O20 refusal as a toast', () => {
    const { svc, http, toasts } = setup();
    svc.setProtokollant(M({ status: 'planned' }), 'p-2');
    http.expectOne('/api/meetings/m-1').flush({ code: 'protokollant_needs_protocol_write' }, { status: 422, statusText: 'x' });
    expect(toasts()).toContain('Diese Person hat im Gremium kein Protokollrecht.');
  });
});
