import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { AuthService } from '@core/auth/auth.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CardComponent } from '@shared/ui';

/**
 * »Meine Gremien« (#5). Nutzerseitige Übersicht der Gremien, in denen der
 * angemeldete Principal über eine (gültige) Rollenzuweisung Mitglied ist —
 * gelesen aus `auth.gremien()` (Backend `GET /auth/me` → `gremien`). Ersetzt die
 * fehlplatzierte Delegations-Verwaltung im Admin-Bereich als Mitglieder-Sicht.
 */
@Component({
  selector: 'app-my-gremien',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, CardComponent],
  template: `
    <section class="mg">
      <header class="mg__head">
        <h1>{{ 'myGremien.title' | t }}</h1>
        <p class="mg__sub">{{ 'myGremien.subtitle' | t }}</p>
      </header>

      @if (gremien().length === 0) {
        <p class="mg__empty">{{ 'myGremien.empty' | t }}</p>
      } @else {
        <div class="mg__grid">
          @for (g of gremien(); track g.id) {
            <app-card [heading]="g.name">
              <span class="mg__slug">{{ g.slug }}</span>
            </app-card>
          }
        </div>
      }
    </section>
  `,
  styles: [
    `
      .mg {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .mg__sub {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .mg__empty {
        color: var(--color-text-muted);
      }
      .mg__grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
        gap: var(--space-4);
      }
      .mg__slug {
        color: var(--color-text-muted);
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-sm);
      }
    `,
  ],
})
export class MyGremienComponent {
  private readonly auth = inject(AuthService);
  protected readonly gremien = this.auth.gremien;
}
