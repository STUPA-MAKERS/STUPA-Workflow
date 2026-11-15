import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import type { Meeting, Protocol, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { longDate } from '@shared/date-format';
import { ButtonComponent, ConfirmDialogComponent, IconComponent, type IconName } from '@stupa-makers/ui-kit';
import { MeetingSessionService } from '../meeting-session.service';
import { ProtocolApprovalDialogComponent } from '../protocol-approval-dialog/protocol-approval-dialog.component';

/** The state line of the bar. */
interface BarState {
  readonly icon: IconName;
  readonly tone: 'muted' | 'accent';
  readonly label: TranslationKey;
  readonly text: TranslationKey;
}

/**
 * The protocol bar on top of the sheet of a closed meeting.
 *
 * - Draft: "Entwurf · Das Protokoll ist noch nicht versandt." and "Finalisieren &
 *   versenden" for a holder of `canFinalize` (write access plus the gremium right
 *   `protocol.finalize`). Without the right the bar says what is missing.
 * - Rendering: the worker renders and sends the PDF.
 * - Final: "Final · Das Protokoll ist final und wurde versandt." and the PDF links
 *   ("PDF intern", "PDF öffentlich" when an item is non-public).
 * - Final, gremium publishes its protocols: "Öffentlich" or "Nicht veröffentlicht",
 *   and for a holder of `canFinalize` the switch between the two (the protocol is held
 *   back from the public protocol page, or published again).
 * - Draft, with write access: "Entwurf senden" sends the PDF with the watermark "Entwurf"
 *   to the members, after a confirmation. The protocol stays a draft (§ 000925). A
 *   second send names the date of the last one in the confirmation (§ 000937).
 * - Draft: "PDF intern" and "PDF öffentlich" open the draft as a PDF
 *   with the watermark "Entwurf". The server renders it for this read and stores
 *   nothing (§ 000950).
 * - Final, for a holder of `canFinalize`: "Als genehmigt markieren" asks for the meeting
 *   that approved the protocol. With the mark the bar names that meeting and offers
 *   "Genehmigung entfernen", which asks before it removes the mark (§ 000924).
 *
 * The finalize is a step of its own after the close; a live meeting has no bar.
 */
@Component({
  selector: 'app-protocol-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, ConfirmDialogComponent, IconComponent, ProtocolApprovalDialogComponent],
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

  /** The switch between "public" and "withheld": a holder of `canFinalize`. */
  protected readonly canPublish = computed(
    () => this.publication() !== null && !!this.meeting().canFinalize && this.session !== null,
  );

  private readonly i18n = inject(I18nService);
  protected readonly draftSending = computed(() => this.session?.draftSending() ?? false);
  protected readonly approvalSaving = computed(() => this.session?.approvalSaving() ?? false);
  /** The confirmation of "Entwurf senden" is open. */
  protected readonly confirmDraft = signal(false);
  /** The confirmation text: a second send names the date of the last one (§ 000937). */
  protected readonly draftBody = computed(() => {
    const last = this.protocol().draftSentAt;
    return last
      ? this.i18n.translate('meetings.draftMail.again', {
          date: longDate(last, this.i18n.formatLocale()),
        })
      : this.i18n.translate('meetings.draftMail.body');
  });
  /** The dialog "Als genehmigt markieren" is open. */
  protected readonly approvalOpen = signal(false);
  /** The confirmation of "Genehmigung entfernen" is open. */
  protected readonly confirmUnapprove = signal(false);

  /** "Entwurf senden": a closed meeting, a draft and write access. */
  protected readonly canSendDraft = computed(() => {
    const m = this.meeting();
    return m.status === 'closed' && !!m.canWrite && this.protocol().status === 'draft' && this.session !== null;
  });

  /** The two PDF links of a draft of a closed meeting (§ 000950). */
  protected readonly draftPdf = computed(() => {
    const p = this.protocol();
    if (p.status !== 'draft' || this.meeting().status !== 'closed') return null;
    const base = `/api/protocols/${p.id}/draft-pdf`;
    return { internal: base, public: `${base}?variant=public` };
  });

  /** The mark and its removal: a final protocol and the right to finalize. */
  protected readonly canApprove = computed(
    () => this.protocol().isFinal && !!this.meeting().canFinalize && this.session !== null,
  );

  /** "Zurück in Entwurf": a final protocol without the mark and the right to finalize (§ 000983). */
  protected readonly canReopen = computed(() => this.canApprove() && !this.protocol().approvedAt);
  protected readonly reopenSaving = computed(() => this.session?.reopenSaving() ?? false);
  /** The confirmation of "Zurück in Entwurf" is open. */
  protected readonly confirmReopen = signal(false);

  /** "Genehmigt in der Sitzung … am …", or '' without the mark. */
  protected readonly approvedText = computed(() => {
    const p = this.protocol();
    if (!p.approvedAt) return '';
    const date = longDate(p.approvedMeetingDate ?? '', this.i18n.formatLocale());
    const meeting = [p.approvedMeetingTitle, date].filter(Boolean).join(' · ');
    return meeting
      ? this.i18n.translate('meetings.protocolBar.approvedIn', { meeting })
      : this.i18n.translate('meetings.protocolBar.approved');
  });

  constructor() {
    // The dialog closes when the server stored the mark.
    effect(() => {
      if (this.protocol().approvedAt) this.approvalOpen.set(false);
    });
  }

  protected sendDraft(): void {
    this.confirmDraft.set(false);
    this.session?.sendProtocolDraft();
  }

  protected unapprove(): void {
    this.confirmUnapprove.set(false);
    this.approve(null);
  }

  protected reopen(): void {
    this.confirmReopen.set(false);
    this.session?.reopenProtocol();
  }

  protected approve(meetingId: Uuid | null): void {
    this.session?.setProtocolApproval(meetingId);
  }

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
    return {
      icon: 'edit',
      tone: 'muted',
      label: 'meetings.protocol.draft',
      text: p.sentAt ? 'meetings.protocolBar.draftAgain' : 'meetings.protocolBar.draft',
    };
  });

  /** Finalize: a closed meeting, a draft and the right. */
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
