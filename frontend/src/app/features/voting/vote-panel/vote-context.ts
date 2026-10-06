import { type Observable, forkJoin, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import type { ApiClient } from '@core/api/api-client.service';
import type { Meeting, Uuid } from '@core/api/models';

/** Where a vote takes place: its meeting and the number of its agenda item. */
export interface VoteContext {
  meeting: Meeting | null;
  /** The 1-based number of the agenda item in the agenda order ("TOP 3"), or `null`. */
  position: number | null;
}

export const NO_CONTEXT: VoteContext = { meeting: null, position: null };

/**
 * Load the meeting of a vote and the number of its agenda item.
 *
 * Both reads are quiet and may fail: an external substitute or a reader of a standalone
 * vote may not read the meeting or its agenda. The page then shows the vote without the
 * line "34. Sitzung · TOP 3".
 */
export function loadVoteContext(
  api: ApiClient,
  meetingId: Uuid | null | undefined,
  agendaItemId: Uuid | null | undefined,
): Observable<VoteContext> {
  if (!meetingId) return of(NO_CONTEXT);
  const meeting = api.getMeeting(meetingId, { quiet: true }).pipe(catchError(() => of(null)));
  const agenda = agendaItemId
    ? api.listAgenda(meetingId, { quiet: true }).pipe(catchError(() => of([])))
    : of([]);
  return forkJoin({ meeting, agenda }).pipe(
    map(({ meeting, agenda }) => {
      const ordered = [...agenda].sort((a, b) => a.position - b.position);
      const index = ordered.findIndex((item) => item.id === agendaItemId);
      return { meeting, position: index >= 0 ? index + 1 : null };
    }),
  );
}
