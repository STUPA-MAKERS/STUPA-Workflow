import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { CardComponent } from '@shared/ui/card/card.component';

/**
 * Generischer Platzhalter für noch nicht implementierte Feature-Routen
 * (T-30…T-36). Liest den Titel aus `route.data.title`.
 */
@Component({
  selector: 'app-placeholder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CardComponent, BadgeComponent],
  template: `
    <app-card [heading]="title()">
      <app-badge variant="info">In Arbeit</app-badge>
      <p class="ph__text">
        Dieser Bereich wird in einem späteren Task umgesetzt. Das Skelett (Routing,
        Design-System, API-Client) steht bereit.
      </p>
    </app-card>
  `,
  styles: [
    `
      .ph__text {
        margin-top: var(--space-3);
        color: var(--color-text-muted);
        max-width: 40rem;
      }
    `,
  ],
})
export class PlaceholderComponent {
  private readonly route = inject(ActivatedRoute);
  readonly fallback = input('Bereich');
  readonly title = toSignal(
    this.route.data.pipe(map((d) => (d['title'] as string | undefined) ?? this.fallback())),
    { initialValue: this.fallback() },
  );
}
