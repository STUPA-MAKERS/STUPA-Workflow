import type { Meeting, Protocol } from '@core/api/models';

import { protocolActions, protocolMenuItems } from './protocol-actions.util';

const meeting = (over: Partial<Meeting> = {}): Meeting =>
  ({ id: 'm1', status: 'closed', canWrite: true, canFinalize: true, ...over }) as Meeting;
const protocol = (over: Partial<Protocol> = {}): Protocol =>
  ({ id: 'p1', status: 'draft', isFinal: false, pdfUrl: null, publicPdfUrl: null, approvedAt: null, ...over }) as Protocol;
const t = (key: string): string => key;
const ids = (m: Meeting, p: Protocol, onPage: boolean, compact: boolean): string[] =>
  protocolMenuItems(protocolActions(m, p, onPage), p, compact, t).map((i) => i.id);

/** Spec 001304: the protocol actions in the head and the "Protokoll" section of the menu. */
describe('protocolActions', () => {
  it('lets a finalizer of a closed meeting finalize a draft and read both draft PDFs', () => {
    const a = protocolActions(meeting(), protocol(), true);
    expect(a.canFinalize).toBe(true);
    expect(a.needsRight).toBe(false);
    expect(a.canSendDraft).toBe(true);
    expect(a.draftPdf).toEqual({ internal: '/api/protocols/p1/draft-pdf', public: '/api/protocols/p1/draft-pdf?variant=public' });
    expect(a.finalPdf).toBeNull();
    expect(a.publication).toBeNull();
  });

  it('shows a writer without the right the finalize as disabled', () => {
    const a = protocolActions(meeting({ canFinalize: false }), protocol(), true);
    expect(a.canFinalize).toBe(false);
    expect(a.needsRight).toBe(true);
    expect(ids(meeting({ canFinalize: false }), protocol(), true, true)[0]).toBe('protocol.finalize');
    const item = protocolMenuItems(a, protocol(), true, t)[0];
    expect(item.disabledReason).toBe('meetings.protocolBar.needsRight');
  });

  it('gives a live meeting no draft PDF and no draft mail', () => {
    const a = protocolActions(meeting({ status: 'live' }), protocol(), true);
    expect(a.draftPdf).toBeNull();
    expect(a.canSendDraft).toBe(false);
    expect(a.canFinalize).toBe(false);
  });

  it('gives a reader off the page only the PDFs', () => {
    const p = protocol({ status: 'final', isFinal: true, pdfUrl: '/x.pdf', publicPdfUrl: '/y.pdf', gremiumProtocolsPublic: true });
    const a = protocolActions(meeting(), p, false);
    expect(a.canApprove).toBe(false);
    expect(a.canReopen).toBe(false);
    expect(a.canPublish).toBe(false);
    expect(a.finalPdf).toEqual({ url: '/x.pdf', label: 'meetings.protocolBar.pdfInternal' });
    expect(ids(meeting(), p, false, false)).toEqual(['protocol.pdfPublic']);
  });

  it('names the PDF of a final protocol without a public variant "PDF"', () => {
    const p = protocol({ status: 'final', isFinal: true, pdfUrl: '/x.pdf' });
    expect(protocolActions(meeting(), p, true).finalPdf?.label).toBe('meetings.protocolBar.pdf');
  });

  it('has no final PDF while the file is missing', () => {
    expect(protocolActions(meeting(), protocol({ status: 'final', isFinal: true }), true).finalPdf).toBeNull();
  });

  it('orders the phone section: PDF first, then approve, reopen and withhold', () => {
    const p = protocol({ status: 'final', isFinal: true, pdfUrl: '/x.pdf', gremiumProtocolsPublic: true, publicWithheld: false });
    expect(ids(meeting(), p, true, true)).toEqual(['protocol.pdf', 'protocol.approve', 'protocol.reopen', 'protocol.withhold']);
    expect(ids(meeting(), p, true, false)).toEqual(['protocol.approve', 'protocol.reopen', 'protocol.withhold']);
  });

  it('offers the removal of the mark and "publish" for an approved, withheld protocol', () => {
    const p = protocol({
      status: 'final',
      isFinal: true,
      pdfUrl: '/x.pdf',
      approvedAt: '2026-11-01T10:00:00Z',
      gremiumProtocolsPublic: true,
      publicWithheld: true,
    });
    const a = protocolActions(meeting(), p, true);
    expect(a.publication).toBe('withheld');
    expect(a.canReopen).toBe(false);
    expect(ids(meeting(), p, true, false)).toEqual(['protocol.unapprove', 'protocol.publish']);
  });

  it('shows the state of publication without the switch to a viewer without the right', () => {
    const p = protocol({ status: 'final', isFinal: true, gremiumProtocolsPublic: true, publicWithheld: false });
    const a = protocolActions(meeting({ canFinalize: false }), p, true);
    expect(a.publication).toBe('public');
    expect(a.canPublish).toBe(false);
    expect(ids(meeting({ canFinalize: false }), p, true, false)).toEqual([]);
  });
});
