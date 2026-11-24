import { inject, type Provider } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { VOTING_API, type VotingApi } from '@stupa-makers/ui-kit/views/voting';

/** The voting port of the kit views over the API client of the app. */
export function appVotingApi(api: ApiClient): VotingApi {
  return {
    castBallot: (voteId, choice, asDelegation) => api.castBallot(voteId, choice, asDelegation),
    drawLot: (voteId) => api.drawElectionLot(voteId),
    nextRound: (voteId) => api.nextElectionRound(voteId),
  };
}

/** Provides {@link VOTING_API} for the voting views of the kit. */
export function provideVotingApi(): Provider {
  return { provide: VOTING_API, useFactory: () => appVotingApi(inject(ApiClient)) };
}

/** The route of a meeting, for the meeting line of the vote panel. */
export const meetingLink = (meetingId: string): readonly unknown[] => ['/meetings', meetingId];

/** The route of an application, for a vote without a meeting. */
export const applicationLink = (applicationId: string): readonly unknown[] => [
  '/applications',
  applicationId,
];
