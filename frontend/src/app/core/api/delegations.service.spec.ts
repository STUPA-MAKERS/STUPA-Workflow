import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { USE_MOCK_API } from './api.config';
import {
  DelegationsApiService,
  type Delegation,
  type DelegationInput,
  type DelegationRecipient,
  type DelegationSubstitute,
  type MeetingDelegationContext,
  type SubstituteInput,
  type VoteDelegationStatus,
} from './delegations.service';

function delegation(over: Partial<Delegation> = {}): Delegation {
  return {
    id: 'del-1',
    meetingId: 'm-1',
    meetingTitle: 'Sitzung',
    meetingDate: '2026-06-20',
    gremiumId: 'g-1',
    gremiumName: 'STUPA',
    delegatorId: 'p-1',
    delegatorName: 'Mia',
    delegateId: 'p-2',
    delegateName: 'Max',
    delegateVoting: true,
    viaPool: false,
    createdAt: '2026-06-10T10:00:00Z',
    revocable: true,
    direction: 'outgoing',
    ...over,
  };
}

describe('DelegationsApiService', () => {
  let svc: DelegationsApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    svc = TestBed.inject(DelegationsApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('lists delegations without a meeting filter (no params)', (done) => {
    const body = [delegation()];
    svc.list().subscribe((list) => {
      expect(list).toEqual(body);
      done();
    });
    const req = http.expectOne('/api/delegations');
    expect(req.request.method).toBe('GET');
    expect(req.request.params.keys()).toHaveLength(0);
    req.flush(body);
  });

  it('lists delegations filtered by meetingId (param set)', (done) => {
    svc.list('m-9').subscribe((list) => {
      expect(list).toEqual([]);
      done();
    });
    const req = http.expectOne((r) => r.url === '/api/delegations');
    expect(req.request.params.get('meetingId')).toBe('m-9');
    req.flush([]);
  });

  it('creates a delegation (POST with the input body)', (done) => {
    const input: DelegationInput = { meetingId: 'm-1', delegateId: 'p-2', delegateVoting: true };
    const created = delegation();
    svc.create(input).subscribe((d) => {
      expect(d).toEqual(created);
      done();
    });
    const req = http.expectOne('/api/delegations');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(input);
    req.flush(created);
  });

  it('revokes a delegation by id (DELETE)', (done) => {
    svc.revoke('del-7').subscribe((res) => {
      expect(res).toBeNull();
      done();
    });
    const req = http.expectOne('/api/delegations/del-7');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('fetches the meeting delegation context', (done) => {
    const ctx: MeetingDelegationContext = {
      meetingId: 'm-1',
      gremiumId: 'g-1',
      allowVoteDelegation: true,
      votingDelegationEnabled: true,
      delegationAllowExternal: false,
      deadline: '2026-06-19T23:59:00Z',
      deadlinePassed: false,
      meetingStarted: false,
      canDelegate: true,
      myDelegation: null,
      incoming: [delegation({ direction: 'incoming' })],
      recipients: [],
    };
    svc.meetingContext('m-1').subscribe((c) => {
      expect(c).toEqual(ctx);
      done();
    });
    const req = http.expectOne('/api/delegations/meetings/m-1/context');
    expect(req.request.method).toBe('GET');
    req.flush(ctx);
  });

  it('searches recipients with the q param', (done) => {
    const recipients: DelegationRecipient[] = [
      { principalId: 'p-2', displayName: 'Max', viaPool: false, isMember: true },
    ];
    svc.recipients('m-1', 'ma').subscribe((r) => {
      expect(r).toEqual(recipients);
      done();
    });
    const req = http.expectOne((r) => r.url === '/api/delegations/meetings/m-1/recipients');
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('q')).toBe('ma');
    req.flush(recipients);
  });

  it('fetches the vote delegation status', (done) => {
    const status: VoteDelegationStatus = {
      blocked: true,
      delegatedToName: 'Max',
      exercising: false,
      delegatedByName: null,
    };
    svc.voteStatus('v-1').subscribe((s) => {
      expect(s).toEqual(status);
      done();
    });
    const req = http.expectOne('/api/delegations/votes/v-1/status');
    expect(req.request.method).toBe('GET');
    req.flush(status);
  });

  it('lists substitutes filtered by gremiumId', (done) => {
    const subs: DelegationSubstitute[] = [
      {
        id: 'sub-1',
        gremiumId: 'g-1',
        memberId: null,
        memberName: null,
        substituteId: 'p-3',
        substituteName: 'Erika',
      },
    ];
    svc.substitutes('g-1').subscribe((s) => {
      expect(s).toEqual(subs);
      done();
    });
    const req = http.expectOne((r) => r.url === '/api/delegations/substitutes');
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('gremiumId')).toBe('g-1');
    req.flush(subs);
  });

  it('adds a substitute (POST with the input body)', (done) => {
    const input: SubstituteInput = { gremiumId: 'g-1', memberId: 'p-1', substituteId: 'p-3' };
    const created: DelegationSubstitute = {
      id: 'sub-2',
      gremiumId: 'g-1',
      memberId: 'p-1',
      memberName: 'Mia',
      substituteId: 'p-3',
      substituteName: 'Erika',
    };
    svc.addSubstitute(input).subscribe((s) => {
      expect(s).toEqual(created);
      done();
    });
    const req = http.expectOne('/api/delegations/substitutes');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(input);
    req.flush(created);
  });

  it('removes a substitute by id (DELETE)', (done) => {
    svc.removeSubstitute('sub-9').subscribe((res) => {
      expect(res).toBeNull();
      done();
    });
    const req = http.expectOne('/api/delegations/substitutes/sub-9');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });
});
