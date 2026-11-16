import type { TranslationKey } from '@core/i18n/translations';

import type { BallotFailure } from './ballot.component';

/** The refusals of a cast that have their own text, by the code of the server. */
const REFUSAL_TEXT: Readonly<Record<string, TranslationKey>> = {
  vote_as_unit: 'voting.cast.toast.asUnit',
  delegation_not_in_election: 'voting.cast.toast.noDelegationInElection',
};

/** The text of a refused cast that has its own text, else null. */
export function castRefusalText(failure: BallotFailure): TranslationKey | null {
  return REFUSAL_TEXT[failure.error.error?.code ?? ''] ?? null;
}
