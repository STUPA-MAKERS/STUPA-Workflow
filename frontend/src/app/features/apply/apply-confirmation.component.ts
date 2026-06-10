import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { CardComponent } from '@shared/ui/card/card.component';

/**
 * Bestätigungsseite nach dem Absenden (T-30, flows §1). Bestätigt den Eingang
 * und weist auf die Magic-Link-Mail hin (Bearbeitung/Status ohne Login).
 */
@Component({
  selector: 'app-apply-confirmation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, BadgeComponent, CardComponent, TranslatePipe],
  template: `
    <section class="done">
      <app-card [heading]="'apply.confirm.heading' | t">
        <div class="done__top">
          <span class="done__mail" aria-hidden="true">✉</span>
          <app-badge variant="warning">{{ 'apply.confirm.badge' | t }}</app-badge>
        </div>
        <p class="done__text">{{ 'apply.confirm.body' | t }}</p>
        <p class="done__expiry" role="note">{{ 'apply.confirm.expiry' | t }}</p>
        @if (applicationId()) {
          <p class="done__ref">
            {{ 'apply.confirm.ref' | t }} <code>{{ applicationId() }}</code>
          </p>
        }
        <p class="done__hint">{{ 'apply.confirm.hint' | t }}</p>
        <a card-footer routerLink="/" class="done__home">{{ 'apply.confirm.home' | t }}</a>
      </app-card>
    </section>
  `,
  styles: [
    `
      .done {
        max-width: 36rem;
        margin: 0 auto;
      }
      .done__top {
        display: flex;
        align-items: center;
        gap: var(--space-3);
      }
      .done__mail {
        font-size: 1.5rem;
        line-height: 1;
        color: var(--color-primary);
      }
      .done__text {
        margin-top: var(--space-4);
        color: var(--color-text);
        line-height: 1.55;
      }
      /* Verwurf-Hinweis hervorheben: abgesetzte Akzent-Leiste + dezenter Grund. */
      .done__expiry {
        margin-top: var(--space-4);
        padding: var(--space-3) var(--space-4);
        border-left: 3px solid var(--color-warning, var(--color-primary));
        border-radius: var(--radius-sm);
        background: var(--color-surface-sunken);
        color: var(--color-text);
        font-size: var(--fs-sm);
      }
      .done__ref {
        margin-top: var(--space-4);
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
      .done__hint {
        margin-top: var(--space-2);
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
      .done__home {
        color: var(--color-primary);
        font-weight: var(--fw-semibold);
        text-decoration: none;
      }
      .done__home:hover {
        text-decoration: underline;
      }
    `,
  ],
})
export class ApplyConfirmationComponent {
  private readonly route = inject(ActivatedRoute);

  readonly applicationId = toSignal(
    this.route.queryParamMap.pipe(map((p) => p.get('id'))),
    { initialValue: null },
  );
}
