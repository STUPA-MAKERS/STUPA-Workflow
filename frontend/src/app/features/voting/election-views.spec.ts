import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import type { ElectionConfig, ElectionResult, MeetingVote, Vote } from '@core/api/models';
import { vote as meetingVote } from '../../../testing/meeting-fixtures';
import { type BeamerVote, MeetingBeamerComponent } from '../meetings/meeting-beamer.component';
import { VoteCardComponent } from '../meetings/vote-card/vote-card.component';
import { VotePanelComponent } from './vote-panel/vote-panel.component';

const ELECTION: ElectionConfig = {
  seats: 1,
  candidates: [
    { id: 'c1', name: 'Anna' },
    { id: 'c2', name: 'Ben' },
  ],
  secret: true,
};
const TIE: ElectionResult = {
  counts: { c1: 4, c2: 4 },
  abstentions: 1,
  ballots: 9,
  elected: [],
  lot: { among: ['c1', 'c2'], seats: 1, drawn: null },
};

function card(over: Partial<MeetingVote> = {}): MeetingVote {
  return meetingVote({
    question: 'Wahl der Sitzungsleitung',
    options: ['c1', 'c2', 'abstain'],
    secret: true,
    kind: 'election',
    election: ELECTION,
    round: 1,
    ...over,
  });
}

describe('election views (F2)', () => {
  it('the meeting card: the election ballot for a voter', async () => {
    await render(VoteCardComponent, {
      inputs: { vote: card({ status: 'open' }), meetingStatus: 'live', canVote: true, canManage: false },
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    expect(screen.getByText('Wahl · 1 Posten')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Anna' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Enthaltung' })).toBeInTheDocument();
  });

  it('the meeting card: casts the list and reports a refused ballot', async () => {
    const view = await render(VoteCardComponent, {
      inputs: { vote: card({ status: 'open', id: 'e1' }), meetingStatus: 'live', canVote: true },
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    await userEvent.click(screen.getByRole('radio', { name: 'Ben' }));
    await userEvent.click(screen.getByRole('button', { name: 'Stimme abgeben: Ben' }));
    const req = http.expectOne('/api/votes/e1/ballot');
    expect(req.request.body).toEqual({ choice: ['c2'], asDelegation: false });
    req.flush({ code: 'vote_not_open', detail: 'Nicht offen' }, { status: 409, statusText: 'Conflict' });
    const toasts = view.fixture.debugElement.injector.get(ToastService).toasts().map((t) => t.message);
    expect(toasts).toContain('Aktion fehlgeschlagen.: Nicht offen');
  });

  it('the meeting card: a 409 already_voted says so', async () => {
    const view = await render(VoteCardComponent, {
      inputs: { vote: card({ status: 'open', id: 'e2' }), meetingStatus: 'live', canVote: true },
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    await userEvent.click(screen.getByRole('radio', { name: 'Anna' }));
    await userEvent.click(screen.getByRole('button', { name: 'Stimme abgeben: Anna' }));
    http.expectOne('/api/votes/e2/ballot').flush({ code: 'already_voted' }, { status: 409, statusText: 'Conflict' });
    const toasts = view.fixture.debugElement.injector.get(ToastService).toasts().map((t) => t.message);
    expect(toasts).toContain('Du hast bereits abgestimmt.');
  });

  it('the meeting card: the closed tie with the lot for the manager', async () => {
    const changed = jest.fn();
    const view = await render(VoteCardComponent, {
      inputs: {
        vote: card({ id: 'e1', status: 'closed', result: 'tie', counts: { c1: 4, c2: 4, abstain: 1 }, electionResult: TIE }),
        meetingStatus: 'live',
        canManage: true,
      },
      on: { electionChanged: changed },
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    expect(screen.getByText('Los steht aus')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Los ziehen' }));
    await userEvent.click(screen.getByRole('button', { name: 'Jetzt Los ziehen' }));
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http.expectOne('/api/votes/e1/draw-lot').flush({ id: 'e1' });
    expect(changed).toHaveBeenCalledWith({ id: 'e1' });
  });

  it('the vote panel: the rules of an election and the result', async () => {
    const v: Vote = {
      id: 'e1',
      applicationId: null,
      meetingId: 'm1',
      question: 'Wahl der Sitzungsleitung',
      eligibleGroup: 'g1',
      config: { options: ['c1', 'c2', 'abstain'], majorityRule: 'simple', secret: true },
      status: 'closed',
      opensAt: null,
      closesAt: null,
      result: 'elected',
      secret: true,
      tally: { counts: { c1: 5, c2: 3, abstain: 1 }, eligible: 9, voted: 9, quorumMet: true, leading: null },
      kind: 'election',
      election: ELECTION,
      electionResult: { counts: { c1: 5, c2: 3 }, abstentions: 1, ballots: 9, elected: ['c1'] },
      round: 2,
    };
    await render(VotePanelComponent, {
      inputs: { vote: v, caster: () => of({}) },
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    expect(screen.getByText('Stichwahl (2. Wahlgang) · 1 Posten · geheime Abstimmung')).toBeInTheDocument();
    expect(screen.getByText('Gewählt: Anna')).toBeInTheDocument();
  });

  it('the beamer: the bars of an election and the status', async () => {
    const beamer: BeamerVote = {
      question: 'Wahl der Sitzungsleitung',
      options: ['c1', 'c2', 'abstain'],
      status: 'closed',
      majorityRule: 'simple',
      secret: true,
      quorum: null,
      quorumMet: true,
      voted: 9,
      present: 9,
      counts: { c1: 4, c2: 4, abstain: 1 },
      result: 'tie',
      failedReason: null,
      election: ELECTION,
      electionResult: TIE,
      round: 1,
    };
    const view = await render(MeetingBeamerComponent, {
      inputs: { logoSrc: 'x.svg', vote: beamer },
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    expect(screen.getByText('Los steht aus')).toBeInTheDocument();
    expect(screen.getByText('Gleichstand: das Los steht aus · 9 Stimmen')).toBeInTheDocument();
    // The beamer shows no action.
    expect(screen.queryByRole('button', { name: 'Los ziehen' })).toBeNull();
    view.fixture.componentRef.setInput('vote', {
      ...beamer,
      status: 'open',
      result: null,
      counts: null,
      voted: 1,
      secret: false,
    });
    view.fixture.detectChanges();
    expect(screen.getByText(/Wahl · 1 Posten · offene Abstimmung/)).toBeInTheDocument();
  });

  it('the vote panel: an open election names no secrecy', async () => {
    const v: Vote = {
      id: 'e3',
      applicationId: null,
      meetingId: 'm1',
      question: 'Wahl der Kassenprüfung',
      eligibleGroup: 'g1',
      config: { options: ['c1', 'c2', 'abstain'], majorityRule: 'simple', secret: false },
      status: 'open',
      opensAt: null,
      closesAt: null,
      result: null,
      secret: false,
      tally: { counts: {}, eligible: 9, voted: 0, quorumMet: false, leading: null },
      kind: 'election',
      election: { ...ELECTION, secret: false },
    };
    await render(VotePanelComponent, {
      inputs: { vote: v, caster: () => of({}) },
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    expect(screen.getByText('Wahl · 1 Posten')).toBeInTheDocument();
  });

  it('the beamer: the live bars of an open election without a result yet', async () => {
    const beamer: BeamerVote = {
      question: 'Wahl der Sitzungsleitung',
      options: ['c1', 'c2', 'abstain'],
      status: 'open',
      majorityRule: 'simple',
      secret: false,
      quorum: null,
      quorumMet: true,
      voted: 1,
      present: 9,
      counts: { c1: 1 },
      result: null,
      failedReason: null,
      election: ELECTION,
      round: 1,
    };
    const { container } = await render(MeetingBeamerComponent, {
      inputs: { logoSrc: 'x.svg', vote: beamer },
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    expect(container.querySelector('app-election-result')).not.toBeNull();
    expect(screen.getByLabelText('Anna: 1 Stimmen, 100 %')).toBeInTheDocument();
  });
});
