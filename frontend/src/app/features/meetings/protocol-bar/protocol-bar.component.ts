import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import type { Meeting, Protocol } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ButtonComponent, IconComponent, type IconName } from '@stupa-makers/ui-kit';
import { MeetingSessionService } from '../meeting-session.service';

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
 * - Final, gremium publishes its protocols: "Öffentlich" or "Nicht veröffentlicht",
 *   and for a holder of `canFinalize` the switch between the two (the protocol is held
 *   back from the public protocol page, or published again).
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

  /** The page session: it saves the publication. Absent outside the meeting page. */
  private readonly session = inject(MeetingSessionService, { optional: true });
  protected readonly publicationSaving = computed(
    () => this.session?.publicationSaving() ?? false,
  );

  /** A final protocol of a gremium that publishes its protocols. */
  protected readonly publication = computed<'public' | 'withheld' | null>(() => {
    const p = this.protocol();
    if (!p.isFinal || !p.gremiumProtocolsPublic) return null;
    return p.publicWithheld ? 'withheld' : 'public';
  });

  /** The switch between "public" and "withheld": a holder of `canFinalize` (O2). */
  protected readonly canPublish = computed(
    () => this.publication() !== null && !!this.meeting().canFinalize && this.session !== null,
  );

  protected togglePublication(): void {
    this.session?.setPublicWithheld(this.publication() !== 'withheld');
  }

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
