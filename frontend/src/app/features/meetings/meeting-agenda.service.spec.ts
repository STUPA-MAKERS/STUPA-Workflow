import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { AgendaItem } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { MeetingAgendaService } from './meeting-agenda.service';

const item = (body: string): AgendaItem => ({
  id: 't-1',
  applicationId: null,
  title: 'Anschaffung',
  body,
  position: 0,
});

// A read of the agenda that started before a save must not set the text of the
// minute-taker back. The next insert (a vote result) appends to that text, so an older
// text from the server would replace what the minute-taker typed last.
describe('MeetingAgendaService — text of the minute-taker', () => {
  let svc: MeetingAgendaService;
  let reads: Subject<AgendaItem[]>[];
  let saves: Subject<AgendaItem[]>[];

  beforeEach(() => {
    jest.useFakeTimers();
    reads = [];
    saves = [];
    const api = {
      listAgenda: jest.fn(() => {
        const s = new Subject<AgendaItem[]>();
        reads.push(s);
        return s;
      }),
      setAgendaBody: jest.fn(() => {
        const s = new Subject<AgendaItem[]>();
        saves.push(s);
        return s;
      }),
    };
    TestBed.configureTestingModule({
      providers: [
        MeetingAgendaService,
        { provide: ApiClient, useValue: api },
        { provide: ToastService, useValue: { error: jest.fn() } },
      ],
    });
    svc = TestBed.inject(MeetingAgendaService);
    svc.agenda.set([item('')]);
  });

  afterEach(() => jest.useRealTimers());

  const body = (): string | null | undefined => svc.agenda()[0]?.body;

  it('keeps the newer local text when an older read of the agenda arrives', () => {
    svc.onTopBodyChange('m-1', 't-1', 'Erster Satz.');
    jest.advanceTimersByTime(1000);
    // The save broadcasts meeting_state, and the page reads the agenda again.
    svc.load('m-1');
    svc.onTopBodyChange('m-1', 't-1', 'Erster Satz. Mein liebevoller Satz.');
    saves[0].next([item('Erster Satz.')]);
    reads[0].next([item('Erster Satz.')]);
    expect(body()).toBe('Erster Satz. Mein liebevoller Satz.');

    // The pending save confirms the newest text; then the server text counts again.
    jest.advanceTimersByTime(1000);
    saves[1].next([item('Erster Satz. Mein liebevoller Satz.')]);
    svc.load('m-1');
    reads[1].next([item('Vom Server')]);
    expect(body()).toBe('Vom Server');
  });

  it('keeps the local text after a failed save', () => {
    svc.onTopBodyChange('m-1', 't-1', 'Ungespeichert');
    jest.advanceTimersByTime(1000);
    saves[0].error(new Error('offline'));
    svc.load('m-1');
    reads[0].next([item('')]);
    expect(body()).toBe('Ungespeichert');
    expect(svc.saveState()).toBe('error');
  });

  it('drops the local text when no meeting can take the save', () => {
    svc.onTopBodyChange('m-1', 't-1', 'Entwurf');
    svc.flushPendingBody(null);
    svc.load('m-1');
    reads[0].next([item('Vom Server')]);
    expect(body()).toBe('Vom Server');
  });
});
