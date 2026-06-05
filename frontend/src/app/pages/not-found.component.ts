import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/** 404-Seite. */
@Component({
  selector: 'app-not-found',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe],
  template: `
    <section class="nf">
      <p class="nf__code">404</p>
      <h1>{{ 'notFound.heading' | t }}</h1>
      <p class="nf__body">{{ 'notFound.body' | t }}</p>
      <a routerLink="/" class="nf__back">{{ 'notFound.back' | t }}</a>
    </section>
  `,
  styles: [
    `
      .nf {
        text-align: center;
        padding-block: var(--space-12);
      }
      .nf__code {
        font-size: var(--fs-3xl);
        font-weight: var(--fw-bold);
        color: var(--color-primary);
      }
      .nf__body {
        color: var(--color-text-muted);
        margin-block: var(--space-3) var(--space-5);
      }
      .nf__back {
        display: inline-flex;
        padding: var(--space-3) var(--space-5);
        font-weight: var(--fw-semibold);
        color: var(--color-text);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        text-decoration: none;
      }
      .nf__back:hover {
        background: var(--color-surface-sunken);
      }
    `,
  ],
})
export class NotFoundComponent {}
