import { Injectable, InjectionToken, computed, inject, signal } from '@angular/core';
import { GremienApiService, type GremiumOverview } from '@core/api/gremien.service';
import type { Uuid } from '@core/api/models';

/** The clock of the tab "Gremien" (the default ranges). A spec replaces it. */
export const GREMIEN_NOW = new InjectionToken<() => Date>('GREMIEN_NOW', {
  providedIn: 'root',
  factory: () => () => new Date(),
});

/**
 * The list of the gremien that the caller sees (`GET /gremien/overview`), shared by the
 * list pane and the open gremium. `GremienComponent` provides it, so the detail reads the
 * row of its gremium (role, counts, quorum, next meeting) without a second request.
 */
@Injectable()
export class GremienStore {
  private readonly api = inject(GremienApiService);

  readonly items = signal<readonly GremiumOverview[]>([]);
  readonly loading = signal(true);
  readonly error = signal(false);
  /** True after the first answer, also after a failed one. */
  readonly loaded = signal(false);

  readonly byId = computed(() => new Map(this.items().map((g) => [g.id, g])));

  load(): void {
    this.loading.set(true);
    this.error.set(false);
    this.api.overview().subscribe({
      next: (rows) => {
        this.items.set(rows);
        this.loading.set(false);
        this.loaded.set(true);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
        this.loaded.set(true);
      },
    });
  }

  find(id: Uuid | null): GremiumOverview | null {
    return id ? (this.byId().get(id) ?? null) : null;
  }
}
