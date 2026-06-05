import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
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
  imports: [RouterLink, BadgeComponent, CardComponent],
  template: `
    <section class="done">
      <app-card heading="Antrag eingegangen">
        <app-badge variant="success">Eingereicht</app-badge>
        <p class="done__text">
          Vielen Dank! Dein Antrag wurde aufgenommen. Wir haben dir eine E-Mail mit einem
          persönlichen Link gesendet — darüber kannst du den <strong>Status verfolgen</strong> und
          deinen Antrag bei Bedarf <strong>bearbeiten</strong>, ohne dich anzumelden.
        </p>
        @if (applicationId()) {
          <p class="done__ref">
            Vorgangsnummer: <code>{{ applicationId() }}</code>
          </p>
        }
        <p class="done__hint">
          Keine Mail erhalten? Prüfe den Spam-Ordner. Der Link ist zeitlich begrenzt gültig.
        </p>
        <a card-footer routerLink="/" class="done__home">Zur Startseite</a>
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
