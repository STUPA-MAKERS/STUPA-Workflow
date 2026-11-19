/**
 * The files of a cost position (spec 001730).
 *
 * The `positions` field type is shared, but the upload of a file belongs to the page
 * that shows the form: the apply wizard keeps its files as drafts. A page that offers
 * files per position provides this token. The field then shows the component of the
 * token below each position, with the inputs `fieldKey`, `positionId` and `heading`, and
 * reports a removed position, so the page can drop its files. Without the token a
 * position has no files block.
 */
import { InjectionToken, type Type } from '@angular/core';

/** What a page gives the `positions` field for the files of its positions. */
export interface PositionFiles {
  /** The component that lists and uploads the files of one position. */
  readonly component: Type<unknown>;
  /** The applicant removed this position: its files go too. */
  removed(fieldKey: string, positionId: string): void;
}

export const POSITION_FILES = new InjectionToken<PositionFiles>('POSITION_FILES');

/** A new id for a position: stable while the answer lives, unique on the page. */
export function newPositionId(): string {
  return `p-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
