import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import type { Meeting, Protocol } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ButtonComponent, IconComponent, type IconName } from '@stupa-makers/ui-kit';

/** The state line of the bar. */
interface BarState {
  icon: IconName;
  tone: 'muted' | 'accent';
  label: TranslationKey;
  text: TranslationKey;
}

/**
 * The protocol bar on top of the sheet of a closed meeting (boards
 * Sitzung-Protokoll-Entwurf and Sitzung-Geschlossen).
 *
 * - Draft: "Entwurf · Das Protokoll ist noch nicht versandt." and "Finalisieren &
 *   versenden" for a holder of `canFinalize` (write access plus the gremium right
 *   `protocol.finalize`, O2). Without the right the bar says what is missing.
 * - Rendering: the worker renders and sends the PDF.
 * - Final: "Final · Das Protokoll ist final und wurde versandt." and the PDF links
 *   ("PDF intern", "PDF öffentlich" when an item is non-public).
 *
 * The finalize is a step of its own after the close (O13); a live meeting has no bar.
 */
@Component({
  selector: 'app-protocol-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, IconComponent],
  templateUrl: './protocol-bar.component.html',
  styleUrl: './protocol-bar.component.scss',
})
export class ProtocolBarComponent {
  readonly meeting = input.required<Meeting>();
  readonly protocol = input.required<Protocol>();
  readonly finalizing = input(false);

  readonly finalize = output<void>();

  protected readonly state = computed<BarState>(() => {
    const p = this.protocol();
    if (p.isFinal) {
      return {
        icon: 'check',
        tone: 'accent',
        label: 'meetings.protocol.final',
        text: p.sentAt ? 'meetings.protocolBar.finalSent' : 'meetings.protocolBar.final',
      };
    }
    if (p.status === 'rendering') {
      return {
        icon: 'clock',
        tone: 'muted',
        label: 'meetings.protocol.rendering',
        text: 'meetings.protocolBar.rendering',
      };
    }
    return { icon: 'edit', tone: 'muted', label: 'meetings.protocol.draft', text: 'meetings.protocolBar.draft' };
  });

  /** Finalize: a closed meeting, a draft and the right (O2, O13). */
  protected readonly canFinalize = computed(() => {
    const m = this.meeting();
    const p = this.protocol();
    return m.status === 'closed' && m.canFinalize && p.status === 'draft';
  });

  /** A writer without the right learns why there is no finalize. */
  protected readonly needsRight = computed(() => {
    const m = this.meeting();
    return this.protocol().status === 'draft' && m.canWrite && !m.canFinalize;
  });
}
