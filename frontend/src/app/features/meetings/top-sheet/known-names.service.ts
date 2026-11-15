import { Injectable, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import type { Uuid } from '@core/api/models';
import type { KnownName } from '@stupa-makers/ui-kit/markdown-editor';

/**
 * The known names of a meeting for the automatic blackout in the protocol editor
 * (000969, 000970). The list loads once per meeting, at the first call, and the call
 * gives an empty list until it is there.
 */
@Injectable({ providedIn: 'root' })
export class KnownNamesService {
  private readonly api = inject(ApiClient);
  private readonly loaded = signal<{ readonly id: Uuid; readonly list: readonly KnownName[] } | null>(null);
  /** The meeting whose names load or loaded, so each meeting loads once. */
  private loading: Uuid | null = null;

  /** The known names of the meeting, or an empty list while they load. */
  names(meetingId: Uuid): readonly KnownName[] {
    const loaded = this.loaded();
    if (loaded?.id === meetingId) return loaded.list;
    if (this.loading !== meetingId) {
      this.loading = meetingId;
      this.api.getKnownNames(meetingId).subscribe({
        next: (list) => this.loaded.set({ id: meetingId, list }),
        error: () => (this.loading = null),
      });
    }
    return [];
  }
}
