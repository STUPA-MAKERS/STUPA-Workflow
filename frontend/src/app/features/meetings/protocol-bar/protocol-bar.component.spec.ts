import { render, screen, within } from '@testing-library/angular';
import { of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import userEvent from '@testing-library/user-event';
import type { Meeting, Protocol } from '@core/api/models';
import { meeting, protocol } from '../../../../testing/meeting-fixtures';
import { signal } from '@angular/core';
import { MeetingSessionService } from '../meeting-session.service';
import { ProtocolBarComponent } from './protocol-bar.component';

const closed = (over: Partial<Meeting> = {}) => meeting({ status: 'closed', ...over });
const final = (over: Partial<Protocol> = {}) => protocol({ status: 'final', isFinal: true, isLocked: true, ...over });

function fakeSession() {
  return {
    publicationSaving: signal(false),
    draftSending: signal(false),
    approvalSaving: signal(false),
    reopenSaving: signal(false),
    reopenProtocol: jest.fn(),
    setPublicWithheld: jest.fn(),
    sendProtocolDraft: jest.fn(),
    setProtocolApproval: jest.fn(),
  };
}

/** The bar on the meeting page (with its session), or elsewhere (`session: false`). */
async function setup(m: Meeting, p: Protocol, opts: { session?: boolean; compact?: boolean; meetings?: Meeting[] } = {}) {
  const finalize = jest.fn();
  const session = fakeSession();
  const api = { listMeetings: jest.fn(() => of(opts.meetings ?? [])) };
  const view = await render(ProtocolBarComponent, {
    inputs: { meeting: m, protocol: p, compact: opts.compact ?? false },
    on: { finalize },
    providers: [
      ...(opts.session === false ? [] : [{ provide: MeetingSessionService, useValue: session }]),
      { provide: ApiClient, useValue: api },
    ],
  });
  const labels = () => view.fixture.componentInstance.menuItems().map((i) => i.label);
  const select = async (label: string) => {
    const item = view.fixture.componentInstance.menuItems().find((i) => i.label === label);
    if (!item) throw new Error(`no item ${label}`);
    view.fixture.componentInstance.select(item.id);
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    view.fixture.detectChanges();
  };
  return { ...view, finalize, session, api, labels, select };
}

/** § 001304: the protocol part of the meeting head. */
describe('ProtocolBarComponent', () => {
  it('offers the finalize of a draft to a holder of the right as the one head action', async () => {
    const { finalize, labels } = await setup(closed(), protocol());
    await userEvent.click(screen.getByRole('button', { name: 'Finalisieren & senden' }));
    expect(finalize).toHaveBeenCalled();
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(labels()).not.toContain('Finalisieren & senden');
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('offers no finalize while the meeting is live', async () => {
    const { labels } = await setup(meeting(), protocol());
    expect(screen.queryByRole('button', { name: 'Finalisieren & senden' })).toBeNull();
    expect(labels()).toEqual([]);
  });

  it('shows the finalize disabled with the missing right to a writer, and nothing to a reader', async () => {
    const { fixture } = await setup(closed({ canFinalize: false }), protocol());
    const button = screen.getByRole('button', { name: 'Finalisieren & senden' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', expect.stringContaining('Gremien-Recht „Protokoll finalisieren & senden“'));
    fixture.componentRef.setInput('meeting', closed({ canFinalize: false, canWrite: false }));
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Finalisieren & senden' })).toBeNull();
  });

  it('puts the head action first in the menu on a phone', async () => {
    const { fixture, finalize, labels, select } = await setup(closed(), protocol(), { compact: true });
    expect(screen.queryByRole('button', { name: 'Finalisieren & senden' })).toBeNull();
    expect(labels()[0]).toBe('Finalisieren & senden');
    await select('Finalisieren & senden');
    expect(finalize).toHaveBeenCalled();
    fixture.componentRef.setInput('protocol', final({ pdfUrl: '/p.pdf' }));
    fixture.detectChanges();
    expect(labels()[0]).toBe('PDF');
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('shows no action while the PDF renders', async () => {
    const { labels } = await setup(closed(), protocol({ status: 'rendering', isLocked: true }));
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
    expect(labels()).toEqual([]);
  });

  it('links the PDF of a final protocol in the head and the public one in the menu', async () => {
    const { fixture, labels } = await setup(
      closed(),
      final({ pdfUrl: '/p.pdf', publicPdfUrl: '/pub.pdf', sentAt: '2026-10-16T08:00:00Z' }),
    );
    expect(screen.getByRole('link', { name: 'PDF intern' })).toHaveAttribute('href', '/p.pdf');
    expect(screen.getByRole('link', { name: 'PDF intern' })).toHaveAttribute('target', '_blank');
    expect(labels()).toContain('PDF öffentlich');
    expect(labels()).not.toContain('PDF intern');
    expect(screen.queryByRole('button', { name: 'Finalisieren & senden' })).toBeNull();
    fixture.componentRef.setInput('protocol', final({ pdfUrl: '/p.pdf' }));
    fixture.detectChanges();
    expect(screen.getByRole('link', { name: 'PDF' })).toHaveAttribute('href', '/p.pdf');
    expect(labels()).not.toContain('PDF öffentlich');
  });

  /** § 000950 (draftPdf): every reader of a closed meeting opens the draft as a PDF. */
  it('offers the draft PDF in both variants in the menu', async () => {
    const { fixture, labels } = await setup(closed({ canFinalize: false, canWrite: false }), protocol(), { session: false });
    expect(labels()).toEqual(['PDF intern', 'PDF öffentlich']);
    fixture.componentRef.setInput('meeting', meeting());
    fixture.detectChanges();
    expect(labels()).toEqual([]);
  });

  describe('draft mail and approval', () => {
    /** § 000925 */
    it('sends the draft to the members after a confirmation', async () => {
      const { session, select } = await setup(closed(), protocol());
      await select('Entwurf senden');
      const confirm = screen.getByRole('dialog', { name: 'Entwurf senden?' });
      expect(confirm).toHaveTextContent('Wasserzeichen „Entwurf“');
      expect(session.sendProtocolDraft).not.toHaveBeenCalled();
      await userEvent.click(within(confirm).getByRole('button', { name: 'Senden' }));
      expect(session.sendProtocolDraft).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole('dialog', { name: 'Entwurf senden?' })).toBeNull();
    });

    /** §F/meetings/protocols/000937 (draftSentAt) */
    it('names the date of the last send in the confirmation of a second send', async () => {
      const { session, select } = await setup(closed(), protocol({ draftSentAt: '2026-11-03T18:30:00Z' }));
      await select('Entwurf senden');
      const confirm = screen.getByRole('dialog', { name: 'Entwurf senden?' });
      expect(confirm).toHaveTextContent('Der Entwurf ging zuletzt am 3. November 2026 an die Mitglieder des Gremiums.');
      expect(confirm).not.toHaveTextContent('Wasserzeichen');
      await userEvent.click(within(confirm).getByRole('button', { name: 'Senden' }));
      expect(session.sendProtocolDraft).toHaveBeenCalledTimes(1);
    });

    it('keeps the draft on "Abbrechen", and offers no send to a reader or for a live meeting', async () => {
      const { session, fixture, select, labels } = await setup(closed(), protocol());
      await select('Entwurf senden');
      await userEvent.click(within(screen.getByRole('dialog', { name: 'Entwurf senden?' })).getByRole('button', { name: 'Abbrechen' }));
      expect(session.sendProtocolDraft).not.toHaveBeenCalled();
      fixture.componentRef.setInput('meeting', closed({ canWrite: false, canFinalize: false }));
      fixture.detectChanges();
      expect(labels()).not.toContain('Entwurf senden');
      fixture.componentRef.setInput('meeting', meeting());
      fixture.detectChanges();
      expect(labels()).not.toContain('Entwurf senden');
    });

    /** § 000924 */
    it('marks a final protocol as approved by the next meeting of the Gremium', async () => {
      const own = closed({ id: 'm-1', gremiumId: 'g-1', date: '2026-10-15' });
      const meetings = [
        meeting({ id: 'm-0', title: '32. Sitzung', date: '2026-10-01' }),
        meeting({ id: 'm-3', title: '35. Sitzung', date: '2026-11-12' }),
        meeting({ id: 'm-2', title: '34. Sitzung', date: '2026-10-29' }),
        own,
      ];
      const { session, api, fixture, select, labels } = await setup(own, final(), { meetings });
      expect(labels()).not.toContain('Entwurf senden');
      await select('Als genehmigt markieren');
      expect(api.listMeetings).toHaveBeenCalledWith('g-1');
      const dialog = screen.getByRole('dialog', { name: 'Als genehmigt markieren' });
      expect(within(dialog).getByLabelText(/Genehmigt in der Sitzung/)).toHaveTextContent('34. Sitzung · 29. Oktober 2026');
      await userEvent.click(within(dialog).getByRole('button', { name: 'Als genehmigt markieren' }));
      expect(session.setProtocolApproval).toHaveBeenCalledWith('m-2');
      fixture.componentRef.setInput('protocol', final({ approvedAt: '2026-10-29T18:00:00Z', approvedMeetingId: 'm-2' }));
      fixture.detectChanges();
      expect(screen.queryByRole('dialog', { name: 'Als genehmigt markieren' })).toBeNull();
      await select('Genehmigung entfernen');
      expect(session.setProtocolApproval).toHaveBeenCalledTimes(1);
      const ask = screen.getByRole('dialog', { name: 'Genehmigung entfernen?' });
      await userEvent.click(within(ask).getByRole('button', { name: 'Entfernen' }));
      expect(session.setProtocolApproval).toHaveBeenLastCalledWith(null);
    });

    it('offers no mark without the right', async () => {
      const { fixture, labels } = await setup(closed({ canFinalize: false }), final({ approvedAt: '2026-10-29T18:00:00Z' }));
      expect(labels()).not.toContain('Genehmigung entfernen');
      fixture.componentRef.setInput('protocol', final());
      fixture.detectChanges();
      expect(labels()).not.toContain('Als genehmigt markieren');
    });

    /** § 000983 (reopenProtocol) */
    it('sets a final protocol back to draft after a confirmation, and not an approved one', async () => {
      const { session, fixture, select, labels } = await setup(closed(), final());
      await select('Zurück in Entwurf');
      expect(session.reopenProtocol).not.toHaveBeenCalled();
      const ask = screen.getByRole('dialog', { name: 'Protokoll zurück in den Entwurf setzen?' });
      await userEvent.click(within(ask).getByRole('button', { name: 'Zurück in Entwurf' }));
      expect(session.reopenProtocol).toHaveBeenCalledTimes(1);
      fixture.componentRef.setInput('protocol', final({ approvedAt: '2026-10-29T18:00:00Z' }));
      fixture.detectChanges();
      expect(labels()).not.toContain('Zurück in Entwurf');
      fixture.componentRef.setInput('protocol', final());
      fixture.componentRef.setInput('meeting', closed({ canFinalize: false }));
      fixture.detectChanges();
      expect(labels()).not.toContain('Zurück in Entwurf');
    });

    it('closes the pick on "Abbrechen"', async () => {
      const { session, select } = await setup(closed(), final());
      await select('Als genehmigt markieren');
      await userEvent.click(within(screen.getByRole('dialog', { name: 'Als genehmigt markieren' })).getByRole('button', { name: 'Abbrechen' }));
      expect(screen.queryByRole('dialog', { name: 'Als genehmigt markieren' })).toBeNull();
      expect(session.setProtocolApproval).not.toHaveBeenCalled();
    });
  });

  describe('public gremium', () => {
    const pub = (over: Partial<Protocol> = {}) => final({ gremiumProtocolsPublic: true, ...over });

    it('offers to hold a public protocol back', async () => {
      const { session, select } = await setup(closed(), pub());
      await select('Nicht veröffentlichen');
      expect(session.setPublicWithheld).toHaveBeenCalledWith(true);
    });

    it('publishes a held-back protocol again', async () => {
      const { session, select } = await setup(closed(), pub({ publicWithheld: true }));
      await select('Veröffentlichen');
      expect(session.setPublicWithheld).toHaveBeenCalledWith(false);
    });

    it('offers no switch without the right', async () => {
      const { labels } = await setup(closed({ canFinalize: false }), pub());
      expect(labels()).not.toContain('Nicht veröffentlichen');
    });

    it('offers no switch for a private gremium', async () => {
      const { labels } = await setup(closed(), pub({ gremiumProtocolsPublic: false }));
      expect(labels()).not.toContain('Nicht veröffentlichen');
    });

    it('offers no switch outside the meeting page (no session)', async () => {
      const { labels } = await setup(closed(), pub(), { session: false });
      expect(labels()).not.toContain('Nicht veröffentlichen');
    });
  });
});
