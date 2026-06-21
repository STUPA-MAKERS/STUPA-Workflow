import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { BadgeComponent } from '@stupa-makers/ui-kit';
import { CardComponent } from '@stupa-makers/ui-kit';

/**
 * Bestätigungsseite nach dem Absenden (T-30, flows §1). Bestätigt den Eingang
 * und weist auf die Magic-Link-Mail hin (Bearbeitung/Status ohne Login).
 */
@Component({
  selector: 'app-apply-confirmation',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, BadgeComponent, CardComponent, TranslatePipe],
  templateUrl: './apply-confirmation.component.html',
  styleUrl: './apply-confirmation.component.scss',
})
export class ApplyConfirmationComponent {
  private readonly route = inject(ActivatedRoute);

  readonly applicationId = toSignal(
    this.route.queryParamMap.pipe(map((p) => p.get('id'))),
    { initialValue: null },
  );
}
