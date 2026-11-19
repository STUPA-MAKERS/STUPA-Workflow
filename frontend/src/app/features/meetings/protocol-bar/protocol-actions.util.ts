import type { Meeting, Protocol } from '@core/api/models';
import type { TranslationKey } from '@core/i18n/translations';
import type { RowMenuItem } from '@stupa-makers/ui-kit';

/** The ids of the protocol items of the session menu. */
export type ProtocolAction =
  | 'protocol.finalize'
  | 'protocol.pdf'
  | 'protocol.pdfPublic'
  | 'protocol.draftPdf'
  | 'protocol.draftPdfPublic'
  | 'protocol.sendDraft'
  | 'protocol.approve'
  | 'protocol.unapprove'
  | 'protocol.reopen'
  | 'protocol.publish'
  | 'protocol.withhold';

/** What the viewer can do with the protocol of a meeting (spec 001304). */
export interface ProtocolActions {
  /** Finalize: a closed meeting, a draft and the right. */
  readonly canFinalize: boolean;
  /** A writer without the right: the finalize shows disabled, with the missing right. */
  readonly needsRight: boolean;
  /** "Entwurf senden": a closed meeting, a draft and write access (§ 000925). */
  readonly canSendDraft: boolean;
  /** The mark and its removal: a final protocol and the right to finalize (§ 000924). */
  readonly canApprove: boolean;
  /** "Zurück in Entwurf": a final protocol without the mark and the right (§ 000983). */
  readonly canReopen: boolean;
  /** A final protocol of a gremium that publishes its protocols. */
  readonly publication: 'public' | 'withheld' | null;
  /** The switch between "public" and "withheld": a holder of `canFinalize`. */
  readonly canPublish: boolean;
  /** The PDF of a final protocol: the head action, or the first item on a phone. */
  readonly finalPdf: { readonly url: string; readonly label: TranslationKey } | null;
  /** The two PDF links of a draft of a closed meeting (§ 000950). */
  readonly draftPdf: { readonly internal: string; readonly public: string } | null;
}

/**
 * The protocol actions of a viewer. `onPage`: the meeting page with its session, which
 * saves the changes; without it the viewer only reads the PDFs.
 */
export function protocolActions(m: Meeting, p: Protocol, onPage: boolean): ProtocolActions {
  const closed = m.status === 'closed';
  const draft = p.status === 'draft';
  const publication = !p.isFinal || !p.gremiumProtocolsPublic ? null : p.publicWithheld ? 'withheld' : 'public';
  const canApprove = !!p.isFinal && !!m.canFinalize && onPage;
  const base = `/api/protocols/${p.id}/draft-pdf`;
  return {
    canFinalize: closed && !!m.canFinalize && draft,
    needsRight: draft && !!m.canWrite && !m.canFinalize,
    canSendDraft: closed && !!m.canWrite && draft && onPage,
    canApprove,
    canReopen: canApprove && !p.approvedAt,
    publication,
    canPublish: publication !== null && !!m.canFinalize && onPage,
    finalPdf:
      p.isFinal && p.pdfUrl
        ? {
            url: p.pdfUrl,
            label: p.publicPdfUrl ? 'meetings.protocolBar.pdfInternal' : 'meetings.protocolBar.pdf',
          }
        : null,
    draftPdf: draft && closed ? { internal: base, public: `${base}?variant=public` } : null,
  };
}

/**
 * The "Protokoll" section of the session menu (spec 001304). `compact`: a phone, whose
 * head has no action (spec 000197), so the section starts with the head action, the
 * finalize or the PDF of a final protocol.
 */
export function protocolMenuItems(
  a: ProtocolActions,
  p: Protocol,
  compact: boolean,
  t: (key: TranslationKey) => string,
): readonly RowMenuItem[] {
  type Entry = readonly [boolean, RowMenuItem & { readonly id: ProtocolAction }];
  const add = (on: boolean, item: Entry[1]): Entry => [on, item];
  const pub = a.canPublish ? a.publication : null;
  const entries: readonly Entry[] = [
    add(compact && (a.canFinalize || a.needsRight), {
      id: 'protocol.finalize',
      label: t('meetings.protocol.finalize'),
      icon: 'send',
      disabledReason: a.canFinalize ? null : t('meetings.protocolBar.needsRight'),
    }),
    add(compact && a.finalPdf !== null, { id: 'protocol.pdf', label: t(a.finalPdf?.label ?? 'meetings.protocolBar.pdf'), icon: 'file' }),
    add(!!p.isFinal && !!p.publicPdfUrl, { id: 'protocol.pdfPublic', label: t('meetings.protocolBar.pdfPublic'), icon: 'file' }),
    add(a.draftPdf !== null, { id: 'protocol.draftPdf', label: t('meetings.protocolBar.pdfInternal'), icon: 'file' }),
    add(a.draftPdf !== null, { id: 'protocol.draftPdfPublic', label: t('meetings.protocolBar.pdfPublic'), icon: 'file' }),
    add(a.canSendDraft, { id: 'protocol.sendDraft', label: t('meetings.protocolBar.sendDraft'), icon: 'mail' }),
    add(a.canApprove && !p.approvedAt, { id: 'protocol.approve', label: t('meetings.protocolBar.approve'), icon: 'check' }),
    add(a.canApprove && !!p.approvedAt, { id: 'protocol.unapprove', label: t('meetings.protocolBar.unapprove'), icon: 'x' }),
    add(a.canReopen, { id: 'protocol.reopen', label: t('meetings.protocolBar.reopen'), icon: 'edit' }),
    add(pub === 'withheld', { id: 'protocol.publish', label: t('meetings.protocolBar.publish'), icon: 'globe' }),
    add(pub === 'public', { id: 'protocol.withhold', label: t('meetings.protocolBar.withhold'), icon: 'eyeslash' }),
  ];
  return entries.filter(([on]) => on).map(([, item]) => item);
}
