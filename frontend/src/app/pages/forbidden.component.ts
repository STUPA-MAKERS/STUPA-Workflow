import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/**
 * 403-Seite (#71). Ziel des `authGuard`, wenn der geladene Principal die für die
 * Route geforderte Permission **wirklich** nicht hat — statt einer stillen
 * Dashboard-Umleitung. Erscheint also erst nach echter Perm-Auswertung (der Guard
 * lädt den Principal via `ensureLoaded`), nie während des Ladens.
 */
@Component({
  selector: 'app-forbidden',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe],
  template: `
    <section class="fb403">
      <p class="fb403__code">403</p>
      <h1>{{ 'forbidden.heading' | t }}</h1>
      <p class="fb403__body">{{ 'forbidden.body' | t }}</p>
      <a routerLink="/dashboard" class="fb403__back">{{ 'forbidden.back' | t }}</a>
    </section>
  `,
  styles: [
    `
      .fb403 {
        text-align: center;
        padding-block: var(--space-12);
      }
      .fb403__code {
        font-size: var(--fs-3xl);
        font-weight: var(--fw-bold);
        color: var(--color-danger);
      }
      .fb403__body {
        color: var(--color-text-muted);
        margin-block: var(--space-3) var(--space-5);
      }
      .fb403__back {
        display: inline-flex;
        padding: var(--space-3) var(--space-5);
        font-weight: var(--fw-semibold);
        color: var(--color-text);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        text-decoration: none;
      }
      .fb403__back:hover {
        background: var(--color-surface-sunken);
      }
    `,
  ],
})
export class ForbiddenComponent {}
