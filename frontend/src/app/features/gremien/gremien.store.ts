import { Injectable, InjectionToken, computed, inject, signal } from '@angular/core';
import { forkJoin } from 'rxjs';
import { GremienApiService, type GremiumOverview } from '@core/api/gremien.service';
import type { Uuid } from '@core/api/models';
import { type Team, TeamsApiService } from '@core/api/teams.service';

/** The clock of the tab "Gremien" (the default ranges). A spec replaces it. */
export const GREMIEN_NOW = new InjectionToken<() => Date>('GREMIEN_NOW', {
  providedIn: 'root',
  factory: () => () => new Date(),
});

/**
 * The teams (`GET /teams`) and the gremien that the caller sees (`GET /committees/overview`),
 * shared by the list pane and the open team (spec 003072). `GremienComponent` provides it, so
 * the detail reads the row of its team and of the Gremium of an inherent team (role, counts,
 * quorum, next meeting) without a second request.
 */
@Injectable()
export class GremienStore {
  private readonly api = inject(GremienApiService);
  private readonly teamsApi = inject(TeamsApiService);

  readonly items = signal<readonly GremiumOverview[]>([]);
  /** Every team by name, with the rights of the caller. */
  readonly teams = signal<readonly Team[]>([]);
  readonly loading = signal(true);
  readonly error = signal(false);
  /** True after the first answer, also after a failed one. */
  readonly loaded = signal(false);

  /** A refresh runs while the rows show (pull to refresh). */
  readonly refreshing = signal(false);

  readonly byId = computed(() => new Map(this.items().map((g) => [g.id, g])));
  readonly teamById = computed(() => new Map(this.teams().map((t) => [t.id, t])));

  private read() {
    return forkJoin({ rows: this.api.overview(), teams: this.teamsApi.list() });
  }

  load(): void {
    this.loading.set(true);
    this.error.set(false);
    this.read().subscribe({
      next: ({ rows, teams }) => {
        this.items.set(rows);
        this.teams.set(teams);
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

  /**
   * Load the list again while the rows show, without the placeholder of `load`. A failed
   * refresh keeps the rows. Before the first answer it is a plain `load`.
   */
  refresh(): void {
    if (!this.loaded() || this.error()) {
      this.load();
      return;
    }
    this.refreshing.set(true);
    this.read().subscribe({
      next: ({ rows, teams }) => {
        this.items.set(rows);
        this.teams.set(teams);
        this.refreshing.set(false);
      },
      error: () => this.refreshing.set(false),
    });
  }

  find(id: Uuid | null): GremiumOverview | null {
    return id ? (this.byId().get(id) ?? null) : null;
  }

  team(id: Uuid | null): Team | null {
    return id ? (this.teamById().get(id) ?? null) : null;
  }

  /** The inherent team of a Gremium. */
  teamOfGremium(gremiumId: Uuid | null): Team | null {
    return gremiumId ? (this.teams().find((t) => t.gremiumId === gremiumId) ?? null) : null;
  }

  /** The sub-teams of a team, by name. */
  subTeams(teamId: Uuid | null): readonly Team[] {
    return teamId ? this.teams().filter((t) => t.parentId === teamId) : [];
  }

  /** Read the list again after a write of a team (create, rename, members). */
  reloadTeams(): void {
    this.teamsApi.list().subscribe({ next: (teams) => this.teams.set(teams), error: () => undefined });
  }
}
