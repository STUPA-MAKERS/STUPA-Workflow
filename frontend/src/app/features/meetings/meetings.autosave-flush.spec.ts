import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { render } from '@testing-library/angular';
import { of } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import type { MeetingOutWire, ProtocolOutWire } from '@core/api/models';
import { WsService } from '@core/ws/ws.service';
import { MeetingsComponent } from './meetings.component';

// Fokus-Suite für AUD-012: Beim Wechsel des im Editor gewählten TOP darf eine
// noch ausstehende debounced Auto-Speicherung des vorherigen TOP-Textes NICHT
// still verloren gehen, sondern muss sofort an den Server gefeuert werden.

const MEETING: MeetingOutWire = {
  id: 'm-1',
  title: 'StuPa-Sitzung',
  status: 'live',
  date: '2026-06-12',
  startTime: '17:00',
  endTime: null,
  activeApplicationId: null,
  gremiumId: null,
  protocolId: 'p-1',
  canControl: true,
  canManage: true,
  canWrite: true,
  canManageVotes: true,
  canVote: false,
  votes: [],
  createdAt: '2026-06-12T17:00:00Z',
};

const PROTOCOL: ProtocolOutWire = {
  id: 'p-1',
  meetingId: 'm-1',
  markdown: '# Protokoll',
  status: 'draft',
  pdfUrl: null,
  sentAt: null,
};

const AGENDA_ITEM = (over: Record<string, unknown> = {}) => ({
  id: 't-1',
  applicationId: null,
  title: 'Begrüßung',
  body: '',
  position: 0,
  nonPublic: false,
  ...over,
});

class FakeWs {
  connectMeeting() {
    return { messages$: of(), send: () => {}, close: () => {} };
  }
}

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return {
    can: (p: string) => set.has(p),
    canAny: (...p: string[]) => p.some((x) => set.has(x)),
    userId: (() => 'pr-1') as unknown as AuthService['userId'],
    gremien: (() => []) as unknown as AuthService['gremien'],
    sessionManageGremien: (() => []) as unknown as AuthService['sessionManageGremien'],
    inSubstitutePool: (() => false) as unknown as AuthService['inSubstitutePool'],
  };
}

type Cmp = InstanceType<typeof MeetingsComponent>;

async function loaded() {
  const view = await render(MeetingsComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(['meeting.manage', 'protocol.write']) },
      { provide: WsService, useValue: new FakeWs() },
      { provide: Router, useValue: { navigate: jest.fn(() => Promise.resolve(true)) } },
      {
        provide: ActivatedRoute,
        useValue: { paramMap: of(convertToParamMap({ id: 'm-1' })) },
      },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  http.match((r) => r.url.endsWith('/gremium')).forEach((req) => req.flush([]));
  http.match((r) => r.url.endsWith('/gremien')).forEach((req) => req.flush([]));
  http.expectOne('/api/meetings/m-1').flush(MEETING);
  http.expectOne('/api/meetings/m-1/protocol').flush(PROTOCOL);
  http.expectOne('/api/meetings/m-1/attendance').flush([]);
  http.expectOne('/api/meetings/m-1/agenda').flush([]);
  http.expectOne('/api/meetings/m-1/agenda/assignable').flush([]);
  http
    .match((r) => r.url.endsWith('/api/delegations/meetings/m-1/context'))
    .forEach((req) =>
      req.flush({
        meetingId: 'm-1',
        gremiumId: 'g-1',
        allowVoteDelegation: false,
        votingDelegationEnabled: false,
        delegationAllowExternal: false,
        deadline: null,
        deadlinePassed: false,
        meetingStarted: false,
        canDelegate: false,
        myDelegation: null,
        incoming: [],
        recipients: [],
      }),
    );
  const cmp = view.fixture.componentInstance as Cmp;
  return { ...view, http, cmp };
}

describe('MeetingsComponent — AUD-012 autosave flush on TOP switch', () => {
  it('flushes the pending TOP body save before switching TOPs (no silent loss)', async () => {
    jest.useFakeTimers();
    try {
      const { cmp, http } = await loaded();
      cmp.agenda.set([
        AGENDA_ITEM(),
        AGENDA_ITEM({ id: 't-2', position: 1 }),
      ] as never);

      // Im TOP t-1 tippen, aber NICHT bis zum Ende der Debounce warten.
      cmp.onTopBodyChange('t-1', 'Wichtiges Protokoll');
      expect(cmp.saveState()).toBe('idle');
      // Optimistisch lokal gehalten, damit der Text im UI nicht verschwindet.
      expect(cmp.agenda().find((a) => a.id === 't-1')?.body).toBe('Wichtiges Protokoll');

      // Innerhalb des Debounce-Fensters zu t-2 wechseln → MUSS t-1 speichern.
      cmp.selectTop('t-2');
      const req = http.expectOne('/api/meetings/m-1/agenda/t-1');
      expect(req.request.method).toBe('PATCH');
      expect(req.request.body).toEqual({ body: 'Wichtiges Protokoll' });
      req.flush([AGENDA_ITEM({ body: 'Wichtiges Protokoll' })]);
      expect(cmp.selectedTopId()).toBe('t-2');

      // Kein nachlaufender Timer mehr (sonst doppelter / verspäteter Save).
      jest.advanceTimersByTime(5000);
      http.verify();
    } finally {
      jest.useRealTimers();
    }
  });

  it('switching TOPs without a pending edit fires no extra save', async () => {
    const { cmp, http } = await loaded();
    cmp.agenda.set([
      AGENDA_ITEM(),
      AGENDA_ITEM({ id: 't-2', position: 1 }),
    ] as never);
    cmp.selectTop('t-2');
    expect(cmp.selectedTopId()).toBe('t-2');
    http.verify();
  });
});
