/** The one count of present members of a meeting (spec 000946). */

import type { Attendance, Meeting } from '@core/api/models';

type Counted = Pick<Meeting, 'presentCount' | 'eligibleCount' | 'presentSeats'>;

/**
 * The present count that the head, the attendance list and the votes show: the value
 * fixed at the close, else the present members with a voting right plus the pool seats.
 */
export function presentCount(meeting: Counted | null | undefined, rows: readonly Attendance[]): number {
  return (
    meeting?.presentCount ??
    rows.filter((a) => a.status === 'present' && a.canVote).length + (meeting?.presentSeats ?? 0)
  );
}

/** The members with a voting right: the value fixed at the close, else the rows of now. */
export function eligibleCount(meeting: Counted | null | undefined, rows: readonly Attendance[]): number {
  return meeting?.eligibleCount ?? rows.filter((a) => a.canVote).length;
}
