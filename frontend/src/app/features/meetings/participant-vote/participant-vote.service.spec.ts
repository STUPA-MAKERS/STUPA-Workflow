import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import type { Meeting, MeetingVote, Vote } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { RailStatusService } from '../../../layout/rail-status.service';
import { ParticipantVoteService } from './participant-vote.service';

function row(over: Partial<MeetingVote> = {}): MeetingVote {
  return {
    id: 'v1',
    applicationId: null,
    agendaItemId: 't-1',
    title: null,
    question: 'Frage?',
    options: ['yes', 'no', 'abstain'],
    status: 'open',
    result: null,
    counts: null,
    leading: null,
    closesAt: null,
    voted: 5,
    present: 9,
    revealed: false,
    failedReason: null,
    ...over,
  };
}

function vote(over: Partial<Vote> = {}): Vote {
  return {
    id: 'v1',
    applicationId: null,
    meetingId: 'm1',
    agendaItemId: 't-1',
    question: 'Frage?',
    eligibleGroup: 'g1',
    config: { options: ['yes', 'no', 'abstain'], majorityRule: 'simple' },
    status: 'open',
    opensAt: null,
    closesAt: null,
    result: null,
    secret: false,
    tally: { counts: {}, eligible: 9, voted: 3, present: 9, revealed: false, quorumMet: true, leading: null },
    canCast: true,
    myBallot: { cast: false, choice: null },
    representedCast: false,
    ...over,
  };
}

const STATUS: VoteDelegationStatus = {
  blocked: false,
  delegatedToName: null,
  exercising: false,
  delegatedByName: null,
};

function setup(opts: { votes?: Vote[]; status?: VoteDelegationStatus | Error } = {}) {
  const queue = [...(opts.votes ?? [vote()])];
  const api = {
    getVote: jest.fn(() => of(queue.length > 1 ? queue.shift()! : queue[0])),
    castBallot: jest.fn(() => of({ status: 'cast' })),
  };
  const delegations = {
    voteStatus: jest.fn(() =>
      opts.status instanceof Error ? throwError(() => opts.status) : of(opts.status ?? STATUS),
    ),
  };
  const toast = { error: jest.fn() };
  const rail = { refresh: jest.fn() };
  TestBed.configureTestingModule({
    providers: [
      ParticipantVoteService,
      { provide: ApiClient, useValue: api },
      { provide: DelegationsApiService, useValue: delegations },
      { provide: ToastService, useValue: toast },
      { provide: RailStatusService, useValue: rail },
    ],
  });
  const svc = TestBed.inject(ParticipantVoteService);
  const set = (r: MeetingVote | null, meeting: Partial<Meeting> = { canVote: true }) => {
    svc.meeting.set(meeting as Meeting);
    svc.row.set(r);
    TestBed.tick();
  };
  return { svc, api, delegations, toast, rail, set };
}

describe('ParticipantVoteService', () => {
  it('reads the vote and the delegation state once per id and status', () => {
    const { svc, api, delegations, set } = setup();
    set(row());
    expect(api.getVote).toHaveBeenCalledWith('v1', { quiet: true });
    expect(delegations.voteStatus).toHaveBeenCalledWith('v1');
    set(row({ voted: 6 }));
    expect(api.getVote).toHaveBeenCalledTimes(1);
    // The turnout of the live row replaces the turnout of the read; the counts stay hidden.
    expect(svc.vote()?.tally.voted).toBe(6);
    expect(svc.vote()?.tally.counts).toEqual({});
    set(row({ voted: 9, revealed: true, counts: { yes: 9 } }));
    expect(svc.vote()?.tally.counts).toEqual({ yes: 9 });
    set(row({ voted: 9, revealed: true, counts: null }));
    expect(svc.vote()?.tally.counts).toEqual({});
  });

  it('reads the vote again when its status changes, and shows the read after the close', () => {
    const closed = vote({ status: 'closed', result: 'passed' });
    const { svc, api, delegations, set } = setup({ votes: [vote(), closed] });
    set(row());
    set(row({ status: 'closed' }));
    expect(api.getVote).toHaveBeenCalledTimes(2);
    // The same vote again: the delegation state stays.
    expect(delegations.voteStatus).toHaveBeenCalledTimes(1);
    expect(svc.vote()).toEqual(closed);
    expect(svc.notice()).toBeNull();
  });

  it('forgets the vote when the view has none', () => {
    const { svc, api, set } = setup();
    set(row());
    set(null);
    expect(svc.vote()).toBeNull();
    set(row());
    expect(api.getVote).toHaveBeenCalledTimes(2);
  });

  it('shows nothing for a read of another vote', () => {
    const { svc, set } = setup({ votes: [vote({ id: 'other' })] });
    set(row());
    expect(svc.vote()).toBeNull();
  });

  it('gives the own row to a person who may cast, else a note', () => {
    const { svc, set } = setup({ votes: [vote({ canCast: false })] });
    set(row());
    expect(svc.own()).toBeNull();
    expect(svc.notice()).toBe('Du bist nicht stimmberechtigt.');
  });

  it('takes the own row away when the meeting says the person may not vote', () => {
    const { svc, set } = setup();
    set(row(), { canVote: false });
    expect(svc.own()).toBeNull();
  });

  it('keeps a missing own ballot as not cast', () => {
    const { svc, set } = setup({ votes: [vote({ myBallot: undefined })] });
    set(row());
    expect(svc.own()).toEqual({ cast: false, choice: null });
  });

  it('gives the row of the represented member and its state', () => {
    const { svc, set } = setup({
      votes: [vote({ representedCast: true })],
      status: { ...STATUS, exercising: true, delegatedByName: 'Jonas Weber' },
    });
    set(row());
    expect(svc.proxyName()).toBe('Jonas Weber');
    expect(svc.proxyCast()).toBe(true);
  });

  it('names an unnamed represented member with a question mark', () => {
    const { svc, set } = setup({ status: { ...STATUS, exercising: true, delegatedByName: null } });
    set(row());
    expect(svc.proxyName()).toBe('?');
  });

  it('says who holds the voting right when the person handed it over', () => {
    const { svc, set } = setup({ status: { ...STATUS, blocked: true, delegatedToName: 'Emma Vogel' } });
    set(row());
    expect(svc.own()).toBeNull();
    expect(svc.notice()).toContain('Emma Vogel');
  });

  it('names nobody when the holder of the voting right has no name', () => {
    const { svc, set } = setup({ status: { ...STATUS, blocked: true } });
    set(row());
    expect(svc.notice()).toContain('?');
  });

  it('survives a failed read of the delegation state', () => {
    const { svc, set } = setup({ status: new Error('x') });
    set(row());
    expect(svc.delegation()).toBeNull();
  });

  it('ignores a late delegation state of a vote that is gone', () => {
    const late = new Subject<VoteDelegationStatus>();
    const { svc, delegations, set } = setup({ votes: [vote(), vote({ id: 'v2' })] });
    delegations.voteStatus.mockReturnValueOnce(late);
    set(row());
    set(row({ id: 'v2' }));
    late.next({ ...STATUS, exercising: true, delegatedByName: 'Alt' });
    expect(svc.proxyName()).toBeNull();
  });

  it('casts over REST and reads the vote again after a ballot', () => {
    const { svc, api, rail, set } = setup();
    set(row());
    svc.caster('yes', true).subscribe();
    expect(api.castBallot).toHaveBeenCalledWith('v1', 'yes', true);
    svc.onCastDone();
    expect(rail.refresh).toHaveBeenCalled();
    expect(api.getVote).toHaveBeenCalledTimes(2);
  });

  it('casts on no vote without a read', () => {
    const { svc, api } = setup();
    svc.caster('yes', false).subscribe();
    expect(api.castBallot).toHaveBeenCalledWith('', 'yes', false);
    svc.onCastDone();
    expect(api.getVote).not.toHaveBeenCalled();
  });

  it('hides a refused row on a 403 and reads the delegation state again', () => {
    const { svc, toast, delegations, set } = setup({
      status: { ...STATUS, exercising: true, delegatedByName: 'Jonas Weber' },
    });
    set(row());
    svc.onCastFailed({ asDelegation: false, alreadyVoted: false, error: { status: 403 } });
    expect(svc.own()).toBeNull();
    expect(toast.error).toHaveBeenCalledWith('Du bist für diese Abstimmung nicht stimmberechtigt.');
    expect(delegations.voteStatus).toHaveBeenCalledTimes(2);
    svc.onCastFailed({ asDelegation: true, alreadyVoted: false, error: { status: 403 } });
    expect(svc.proxyName()).toBeNull();
  });

  it('reports a 409 and reads the vote again', () => {
    const { svc, toast, api, set } = setup();
    set(row());
    svc.onCastFailed({ asDelegation: false, alreadyVoted: true, error: { status: 409 } });
    expect(toast.error).toHaveBeenLastCalledWith('Du hast bereits abgestimmt.');
    svc.onCastFailed({ asDelegation: false, alreadyVoted: false, error: { status: 409 } });
    expect(toast.error).toHaveBeenLastCalledWith('Die Abstimmung ist nicht mehr offen.');
    expect(api.getVote).toHaveBeenCalledTimes(3);
  });

  it('reports any other refusal with the reason of the server', () => {
    const { svc, toast } = setup();
    svc.onCastFailed({ asDelegation: false, alreadyVoted: false, error: { status: 500, error: { detail: 'kaputt' } as never } });
    expect(toast.error).toHaveBeenLastCalledWith('kaputt');
    svc.onCastFailed({ asDelegation: false, alreadyVoted: false, error: {} });
    expect(toast.error).toHaveBeenLastCalledWith('Stimme konnte nicht gezählt werden.');
  });

  it('survives a failed read of the vote', () => {
    const { svc, api, set } = setup();
    api.getVote.mockReturnValueOnce(throwError(() => new Error('x')) as never);
    set(row());
    expect(svc.vote()).toBeNull();
  });
});
