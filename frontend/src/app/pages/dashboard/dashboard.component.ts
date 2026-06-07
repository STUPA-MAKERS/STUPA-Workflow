import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { catchError, of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { CardComponent } from '@shared/ui/card/card.component';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';

interface Section {
  /** Sichtbarkeit: mindestens eine Permission (leer = jede Session). */
  readonly permissions: string[];
  readonly titleKey: TranslationKey;
  readonly route: string;
  /** Liefert die Kennzahl der Kachel (z. B. Anzahl offener Aufgaben). */
  readonly count: () => number | null;
}

/**
 * Rollenbasierte Startseite (overview §4): Kacheln für offene Aufgaben, eigene
 * Anträge/Votes, Sitzungen, Budget, Verwaltung — je nach RBAC-Permission. Die
 * konkreten Feature-Inhalte liefern die Schwester-FE-Tasks (T-30…T-35); hier
 * zählt T-36 den verfügbaren Antrags-Endpunkt aus und gated die Sichtbarkeit.
 */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, CardComponent, BadgeComponent, CapitalizePipe],
  template: `
    <header class="dash__head">
      <h1 class="dash__title">{{ 'dashboard.greeting' | t: { name: auth.displayName() } }}</h1>
      <p class="dash__subtitle">{{ 'dashboard.subtitle' | t }}</p>
      @if (auth.roles().length) {
        <div class="dash__roles">
          @for (role of auth.roles(); track role) {
            <app-badge variant="primary">{{ role | capitalize }}</app-badge>
          }
        </div>
      }
    </header>

    <div class="dash__grid">
      @for (section of visibleSections(); track section.route) {
        <a class="dash__tile" [routerLink]="section.route">
          <app-card [heading]="section.titleKey | t" [interactive]="true">
            <div class="dash__metric">
              @if (loading()) {
                <span class="dash__loading">{{ 'dashboard.loading' | t }}</span>
              } @else if (section.count() !== null) {
                <span class="dash__count">{{ section.count() }}</span>
              } @else {
                <span class="dash__empty">{{ 'dashboard.empty' | t }}</span>
              }
            </div>
            <span card-footer class="dash__link">{{ 'dashboard.viewAll' | t }} →</span>
          </app-card>
        </a>
      }
    </div>
  `,
  styles: [
    `
      .dash__head {
        margin-bottom: var(--space-7);
      }
      .dash__title {
        margin-bottom: var(--space-2);
      }
      .dash__subtitle {
        color: var(--color-text-muted);
        font-size: var(--fs-lg);
      }
      .dash__roles {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-2);
        margin-top: var(--space-4);
      }
      .dash__grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
        gap: var(--space-5);
      }
      .dash__tile {
        text-decoration: none;
        color: inherit;
      }
      .dash__metric {
        min-height: 2.5rem;
        display: flex;
        align-items: center;
      }
      .dash__count {
        font-size: var(--fs-2xl);
        font-weight: var(--fw-bold);
        color: var(--color-primary);
      }
      .dash__empty,
      .dash__loading {
        color: var(--color-text-muted);
      }
      .dash__link {
        color: var(--color-primary);
        font-weight: var(--fw-medium);
        font-size: var(--fs-sm);
      }
    `,
  ],
})
export class DashboardComponent {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiClient);

  /** Eigene/relevante Anträge (Datenquelle für Aufgaben- und Antrags-Kachel). */
  private readonly applications = toSignal(
    this.api.listApplications().pipe(catchError(() => of(null))),
    { initialValue: undefined },
  );

  /** `true`, solange der Antrags-Endpunkt noch nicht geantwortet hat. */
  readonly loading = computed(() => this.applications() === undefined);

  private readonly total = computed(() => this.applications()?.total ?? null);

  private readonly sections: Section[] = [
    {
      permissions: ['application.read'],
      titleKey: 'dashboard.tasks.title',
      route: '/applications',
      count: () => this.total(),
    },
    {
      permissions: ['application.read'],
      titleKey: 'dashboard.applications.title',
      route: '/applications',
      count: () => this.total(),
    },
    {
      permissions: ['vote.cast', 'vote.manage'],
      titleKey: 'dashboard.votes.title',
      route: '/voting',
      count: () => null,
    },
    {
      permissions: ['meeting.manage', 'protocol.write'],
      titleKey: 'dashboard.meetings.title',
      route: '/meetings',
      count: () => null,
    },
    {
      permissions: ['budget.view', 'budget.manage'],
      titleKey: 'dashboard.budget.title',
      route: '/budget',
      count: () => null,
    },
    {
      permissions: ['admin.config'],
      titleKey: 'dashboard.admin.title',
      route: '/admin',
      count: () => null,
    },
  ];

  /** Kacheln, für die der Principal mindestens eine Permission besitzt. */
  readonly visibleSections = computed(() =>
    this.sections.filter((s) => this.auth.canAny(...s.permissions)),
  );
}
