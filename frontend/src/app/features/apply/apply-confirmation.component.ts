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
        <app-badge variant="success">{{ 'apply.confirm.badge' | t }}</app-badge>
        <p class="done__text">{{ 'apply.confirm.body' | t }}</p>
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
        max-width: 40rem;
        margin: 0 auto;
      }
      .done__text {
        margin-top: var(--space-3);
        color: var(--color-text);
      }
      .done__ref {
        margin-top: var(--space-4);
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
      .done__hint {
        margin-top: var(--space-3);
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
