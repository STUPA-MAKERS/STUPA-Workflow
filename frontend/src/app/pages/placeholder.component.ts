import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { CardComponent } from '@shared/ui/card/card.component';

/**
 * Generischer Platzhalter für noch nicht implementierte Feature-Routen
 * (T-30…T-36). Liest den Titel-Key aus `route.data.title` (i18n-Key; unbekannte
 * Werte fallen über die Pipe auf sich selbst zurück).
 */
@Component({
  selector: 'app-placeholder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CardComponent, BadgeComponent, TranslatePipe],
  template: `
    <app-card [heading]="title() | t">
      <app-badge variant="info">{{ 'placeholder.badge' | t }}</app-badge>
      <p class="ph__text">{{ 'placeholder.body' | t }}</p>
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
  /** i18n-Key des Fallback-Titels (überschreibbar). */
  readonly fallback = input<TranslationKey>('placeholder.fallback');
  readonly title = toSignal(
    this.route.data.pipe(
      map((d) => ((d['title'] as TranslationKey | undefined) ?? this.fallback())),
    ),
    { initialValue: this.fallback() },
  );
}
