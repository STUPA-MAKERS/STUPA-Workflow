import type { PersonRef } from '@core/api/models';

/** A person the composer offers after "@": someone who can read the thread. */
export interface ChatPerson {
  readonly principalId: string;
  readonly displayName: string;
}

/** The people of a reference list that have an id and a name. */
export function chatPeople(refs: readonly PersonRef[] | null | undefined): ChatPerson[] {
  return (refs ?? []).flatMap((r) =>
    r.principalId && r.displayName
      ? [{ principalId: r.principalId, displayName: r.displayName }]
      : [],
  );
}
