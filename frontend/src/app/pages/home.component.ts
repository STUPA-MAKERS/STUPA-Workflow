import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CardComponent } from '@shared/ui/card/card.component';

/** Öffentliche Startseite (Skelett). */
@Component({
  selector: 'app-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, CardComponent],
  template: `
    <section class="hero">
      <p class="hero__eyebrow">{{ 'app.title' | t }}</p>
      <h1 class="hero__title">{{ 'home.heading' | t }}</h1>
      <p class="hero__subtitle">{{ 'home.subtitle' | t }}</p>
      <a routerLink="/apply" class="hero__cta">{{ 'home.cta' | t }}</a>
    </section>

    <div class="grid">
      <app-card heading="Anträge">
        <p>{{ 'home.subtitle' | t }}</p>
      </app-card>
      <app-card heading="Live-Vote">
        <p>{{ 'nav.voting' | t }}</p>
      </app-card>
      <app-card heading="Budget">
        <p>{{ 'nav.budget' | t }}</p>
      </app-card>
    </div>
  `,
  styles: [
    `
      .hero {
        padding-block: var(--space-10) var(--space-8);
        max-width: 46rem;
      }
      .hero__eyebrow {
        color: var(--color-primary);
        font-weight: var(--fw-semibold);
        font-size: var(--fs-sm);
        letter-spacing: 0.05em;
        text-transform: uppercase;
      }
      .hero__title {
        margin-block: var(--space-3);
      }
      .hero__subtitle {
        color: var(--color-text-muted);
        font-size: var(--fs-lg);
        margin-bottom: var(--space-6);
      }
      .hero__cta {
        display: inline-flex;
        align-items: center;
        padding: var(--space-4) var(--space-6);
        font-size: var(--fs-lg);
        font-weight: var(--fw-semibold);
        color: var(--color-on-primary);
        background: var(--color-primary);
        border-radius: var(--radius-md);
        text-decoration: none;
        transition: background-color var(--motion-fast) var(--ease-standard);
      }
      .hero__cta:hover {
        background: var(--color-primary-hover);
      }
      .grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
        gap: var(--space-5);
      }
    `,
  ],
})
export class HomeComponent {}
