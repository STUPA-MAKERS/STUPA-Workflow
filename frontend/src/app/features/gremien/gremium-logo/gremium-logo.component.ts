import { ChangeDetectionStrategy, Component, computed, effect, input, signal } from '@angular/core';
import { variantInitials } from '../../../pages/admin/cd-variants/cd-variants.util';

/** The edge of the square: 40px in a row, 48px in the header, 40px in the phone header. */
export type GremiumLogoSize = 'md' | 'lg';

/**
 * The square logo of a gremium: the square logo of its CD variant
 * (`GET /api/gremien/{id}/logo`) on white, else the initials of the gremium, by the
 * rule of the CD variants page (`variantInitials`: "STUPA" → "ST").
 *
 * The image is decorative: the name of the gremium stands beside it. A logo that does not
 * load (404, network) falls back to the initials; a new URL tries again.
 */
@Component({
  selector: 'app-gremium-logo',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    'aria-hidden': 'true',
    '[class.glo--lg]': "size() === 'lg'",
    '[class.glo--img]': 'showImage()',
  },
  templateUrl: './gremium-logo.component.html',
  styleUrl: './gremium-logo.component.scss',
})
export class GremiumLogoComponent {
  readonly name = input.required<string>();
  readonly logoUrl = input<string | null>(null);
  readonly size = input<GremiumLogoSize>('md');

  private readonly failed = signal(false);

  readonly initials = computed(() => variantInitials(this.name()));
  readonly showImage = computed(() => !!this.logoUrl() && !this.failed());

  constructor() {
    // A new logo URL gets a new try.
    effect(() => {
      this.logoUrl();
      this.failed.set(false);
    });
  }

  onError(): void {
    this.failed.set(true);
  }
}
