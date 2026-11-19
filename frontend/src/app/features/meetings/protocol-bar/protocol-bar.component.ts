import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import type { Meeting, Protocol, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { longDate } from '@shared/date-format';
import { ButtonComponent, ButtonGroupComponent, ButtonLinkComponent, ConfirmDialogComponent, IconComponent } from '@stupa-makers/ui-kit';
import { FileOpenService } from '@shared/viewer/file-open.service';
import { MeetingSessionService } from '../meeting-session.service';
import { type ProtocolAction, protocolActions, protocolMenuItems } from './protocol-actions.util';
import { ProtocolApprovalDialogComponent } from '../protocol-approval-dialog/protocol-approval-dialog.component';

/**
 * The protocol of a closed meeting in the head of the meeting page (spec 001304).
 *
 * The status of the head names the state of the protocol (`protocolStatus`), so this
 * component draws no state line. It draws the one protocol action of the head and the
 * dialogs, and it gives the session menu its "Protokoll" section (`menuItems`, `select`).
 *
 * - The head action: "Finalisieren & senden" for a draft and a holder of `canFinalize`
 *   (write access plus the gremium right `protocol.finalize`). A writer without the right
 *   sees the button disabled, with the missing right as its reason. A final protocol shows
 *   "PDF" (or "PDF intern" when a public variant exists). On a phone the head has no action
 *   (spec 000197), so the action is the first item of the section.
 * - Draft: "Entwurf senden" sends the PDF with the watermark "Entwurf" to the members,
 *   after a confirmation. The protocol stays a draft (§ 000925). A second send names the
 *   date of the last one in the confirmation (§ 000937). "PDF intern" and "PDF öffentlich"
 *   open the draft as a PDF with the watermark "Entwurf". The server renders it for this
 *   read and stores nothing (§ 000950).
 * - Final: "PDF öffentlich" when an item is non-public. For a holder of `canFinalize`
 *   "Als genehmigt markieren" asks for the meeting that approved the protocol, and with the
 *   mark "Genehmigung entfernen" asks before it removes the mark (§ 000924). Without the
 *   mark "Zurück in Entwurf" asks before it sets the protocol back (§ 000983).
 * - Final, gremium publishes its protocols: for a holder of `canFinalize`
 *   "Nicht veröffentlichen" or "Veröffentlichen" (the protocol is held back from the public
 *   protocol page, or published again).
 *
 * The finalize is a step of its own after the close; a live meeting has no protocol actions.
 */
@Component({
  selector: 'app-protocol-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ButtonComponent,
    ButtonGroupComponent,
    ButtonLinkComponent,
    ConfirmDialogComponent,
    IconComponent,
    ProtocolApprovalDialogComponent,
  ],
  templateUrl: './protocol-bar.component.html',
  styleUrl: './protocol-bar.component.scss',
})
export class ProtocolBarComponent {
  readonly meeting = input.required<Meeting>();
  readonly protocol = input.required<Protocol>();
  readonly finalizing = input(false);
  /** A phone: the head has no action, so the head action is an item of the menu. */
  readonly compact = input(false);

  readonly finalize = output<void>();

  /** The page session: it saves the publication. Absent outside the meeting page. */
  private readonly session = inject(MeetingSessionService, { optional: true });

  /** What the viewer can do (spec 001304): shared with the session menu of the page. */
  private readonly actions = computed(() => protocolActions(this.meeting(), this.protocol(), this.session !== null));
  protected readonly publication = computed(() => this.actions().publication);
  protected readonly canFinalize = computed(() => this.actions().canFinalize);
  protected readonly needsRight = computed(() => this.actions().needsRight);
  protected readonly finalPdf = computed(() => this.actions().finalPdf);
  private readonly draftPdf = computed(() => this.actions().draftPdf);

  private readonly i18n = inject(I18nService);
  private readonly files = inject(FileOpenService);
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

  /**
   * A PDF link opens the PDF in the file viewer (spec 001080). A click with a modifier
   * keeps the new tab of the link.
   */
  protected openPdf(event: MouseEvent, url: string, label: TranslationKey): void {
    this.files.click(event, this.pdfFile(url, label));
  }

  private pdfFile(url: string, label: TranslationKey) {
    return { name: `${this.meeting().title} · ${this.i18n.translate(label)}`, url, kind: 'pdf' as const };
  }

  /** The confirmation of "Zurück in Entwurf" is open. */
  protected readonly confirmReopen = signal(false);

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

  /** The "Protokoll" section of the session menu, as the page builds it. */
  readonly menuItems = computed(() =>
    protocolMenuItems(this.actions(), this.protocol(), this.compact(), (key) => this.i18n.translate(key)),
  );

  /** Runs an item of the "Protokoll" section. Returns false for an id of another section. */
  select(id: string): boolean {
    const p = this.protocol();
    switch (id as ProtocolAction) {
      case 'protocol.finalize':
        this.finalize.emit();
        return true;
      case 'protocol.pdf': {
        const pdf = this.finalPdf();
        if (pdf) this.files.open(this.pdfFile(pdf.url, pdf.label));
        return true;
      }
      case 'protocol.pdfPublic':
        if (p.publicPdfUrl) this.files.open(this.pdfFile(p.publicPdfUrl, 'meetings.protocolBar.pdfPublic'));
        return true;
      case 'protocol.draftPdf': {
        const draft = this.draftPdf();
        if (draft) this.files.open(this.pdfFile(draft.internal, 'meetings.protocolBar.pdfInternal'));
        return true;
      }
      case 'protocol.draftPdfPublic': {
        const draft = this.draftPdf();
        if (draft) this.files.open(this.pdfFile(draft.public, 'meetings.protocolBar.pdfPublic'));
        return true;
      }
      case 'protocol.sendDraft':
        this.confirmDraft.set(true);
        return true;
      case 'protocol.approve':
        this.approvalOpen.set(true);
        return true;
      case 'protocol.unapprove':
        this.confirmUnapprove.set(true);
        return true;
      case 'protocol.reopen':
        this.confirmReopen.set(true);
        return true;
      case 'protocol.publish':
      case 'protocol.withhold':
        this.togglePublication();
        return true;
      default:
        return false;
    }
  }
}
