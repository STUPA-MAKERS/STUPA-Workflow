import { render, screen, within } from '@testing-library/angular';
import { of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import userEvent from '@testing-library/user-event';
import type { Meeting, Protocol } from '@core/api/models';
import { meeting, protocol } from '../../../../testing/meeting-fixtures';
import { signal } from '@angular/core';
import { MeetingSessionService } from '../meeting-session.service';
import { ProtocolBarComponent } from './protocol-bar.component';

async function setup(m: Meeting, p: Protocol, finalizing = false) {
  const finalize = jest.fn();
  const view = await render(ProtocolBarComponent, {
    inputs: { meeting: m, protocol: p, finalizing },
    on: { finalize },
  });
  return { ...view, finalize };
}

const closed = (over: Partial<Meeting> = {}) => meeting({ status: 'closed', ...over });

describe('ProtocolBarComponent', () => {
  it('offers the finalize of a draft to a holder of the right', async () => {
    const { finalize } = await setup(closed(), protocol());
    expect(screen.getByRole('status')).toHaveTextContent('Entwurf · Das Protokoll ist noch nicht versandt.');
    await userEvent.click(screen.getByRole('button', { name: 'Finalisieren & senden' }));
    expect(finalize).toHaveBeenCalled();
  });

  it('offers no finalize while the meeting is live', async () => {
    await setup(meeting(), protocol());
    expect(screen.queryByRole('button', { name: 'Finalisieren & senden' })).toBeNull();
  });

  it('says what is missing to a writer without the right, and nothing to a reader', async () => {
    const { fixture } = await setup(closed({ canFinalize: false }), protocol());
    expect(screen.queryByRole('button', { name: 'Finalisieren & senden' })).toBeNull();
    expect(screen.getByText(/Gremien-Recht „Protokoll finalisieren & senden“/)).toBeInTheDocument();
    fixture.componentRef.setInput('meeting', closed({ canFinalize: false, canWrite: false }));
    fixture.detectChanges();
    expect(screen.queryByText(/Gremien-Recht/)).toBeNull();
  });

  it('shows the render in progress without an action', async () => {
    await setup(closed(), protocol({ status: 'rendering', isLocked: true }));
    expect(screen.getByRole('status')).toHaveTextContent('Wird gerendert … · Das PDF wird erstellt und versandt.');
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
  });

  /**
   * When nothing is redacted and nothing is sent yet, there is one PDF, and the bar does not claim
   * a mail.
   */
  it('links the PDFs of a final protocol', async () => {
    const { fixture } = await setup(
      closed(),
      protocol({ status: 'final', isFinal: true, isLocked: true, pdfUrl: '/p.pdf', publicPdfUrl: '/pub.pdf', sentAt: '2026-10-16T08:00:00Z' }),
    );
    expect(screen.getByRole('status')).toHaveTextContent('Final · Das Protokoll ist final und wurde versandt.');
    expect(screen.getByRole('link', { name: 'PDF intern' })).toHaveAttribute('href', '/p.pdf');
    expect(screen.getByRole('link', { name: 'PDF öffentlich' })).toHaveAttribute('href', '/pub.pdf');
    expect(screen.getByRole('link', { name: 'PDF intern' })).toHaveAttribute('target', '_blank');
    expect(screen.queryByRole('button', { name: 'Finalisieren & senden' })).toBeNull();
    fixture.componentRef.setInput('protocol', protocol({ status: 'final', isFinal: true, isLocked: true, pdfUrl: '/p.pdf' }));
    fixture.detectChanges();
    expect(screen.getByRole('status')).toHaveTextContent('Final · Das Protokoll ist final.');
    expect(screen.getByRole('link', { name: 'PDF' })).toHaveAttribute('href', '/p.pdf');
    expect(screen.queryByRole('link', { name: 'PDF öffentlich' })).toBeNull();
  });

  /** § 000950 (draftPdf): every reader of a closed meeting opens the draft as a PDF. */
  it('links the draft PDF in both variants', async () => {
    const p = protocol();
    const { fixture } = await setup(closed({ canFinalize: false, canWrite: false }), p);
    const base = `/api/protocols/${p.id}/draft-pdf`;
    expect(screen.getByRole('link', { name: 'PDF intern' })).toHaveAttribute('href', base);
    expect(screen.getByRole('link', { name: 'PDF öffentlich' })).toHaveAttribute('href', `${base}?variant=public`);
    fixture.componentRef.setInput('meeting', meeting());
    fixture.detectChanges();
    expect(screen.queryByRole('link')).toBeNull();
  });

  describe('draft mail and approval', () => {
    async function withSession(m: Meeting, p: Protocol, meetings: Meeting[] = []) {
      const session = {
        publicationSaving: signal(false),
        draftSending: signal(false),
        approvalSaving: signal(false),
        setPublicWithheld: jest.fn(),
        sendProtocolDraft: jest.fn(),
        setProtocolApproval: jest.fn(),
      };
      const api = { listMeetings: jest.fn(() => of(meetings)) };
      const view = await render(ProtocolBarComponent, {
        inputs: { meeting: m, protocol: p },
        providers: [
          { provide: MeetingSessionService, useValue: session },
          { provide: ApiClient, useValue: api },
        ],
      });
      return { ...view, session, api };
    }
    const final = (over: Partial<Protocol> = {}) => protocol({ status: 'final', isFinal: true, isLocked: true, ...over });

    /** § 000925 */
    it('sends the draft to the members after a confirmation', async () => {
      const { session, fixture } = await withSession(closed(), protocol());
      await userEvent.click(screen.getByRole('button', { name: 'Entwurf senden' }));
      const confirm = screen.getByRole('dialog', { name: 'Entwurf senden?' });
      expect(confirm).toHaveTextContent('Wasserzeichen „Entwurf“');
      expect(session.sendProtocolDraft).not.toHaveBeenCalled();
      await userEvent.click(within(confirm).getByRole('button', { name: 'Senden' }));
      fixture.detectChanges();
      expect(session.sendProtocolDraft).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole('dialog', { name: 'Entwurf senden?' })).toBeNull();
    });

    /** §F/meetings/protocols/000937 */
    it('names the date of the last send in the confirmation of a second send', async () => {
      const { session } = await withSession(closed(), protocol({ draftSentAt: '2026-11-03T18:30:00Z' }));
      await userEvent.click(screen.getByRole('button', { name: 'Entwurf senden' }));
      const confirm = screen.getByRole('dialog', { name: 'Entwurf senden?' });
      expect(confirm).toHaveTextContent('Der Entwurf ging zuletzt am 3. November 2026 an die Mitglieder des Gremiums.');
      expect(confirm).not.toHaveTextContent('Wasserzeichen');
      await userEvent.click(within(confirm).getByRole('button', { name: 'Senden' }));
      expect(session.sendProtocolDraft).toHaveBeenCalledTimes(1);
    });

    it('keeps the draft on "Abbrechen", and offers no send to a reader or for a live meeting', async () => {
      const { session, fixture } = await withSession(closed(), protocol());
      await userEvent.click(screen.getByRole('button', { name: 'Entwurf senden' }));
      await userEvent.click(within(screen.getByRole('dialog', { name: 'Entwurf senden?' })).getByRole('button', { name: 'Abbrechen' }));
      fixture.detectChanges();
      expect(session.sendProtocolDraft).not.toHaveBeenCalled();
      fixture.componentRef.setInput('meeting', closed({ canWrite: false, canFinalize: false }));
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Entwurf senden' })).toBeNull();
      fixture.componentRef.setInput('meeting', meeting());
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Entwurf senden' })).toBeNull();
    });

    /** § 000924 */
    it('marks a final protocol as approved by the next meeting of the Gremium', async () => {
      const own = closed({ id: 'm-1', gremiumId: 'g-1', date: '2026-10-15' });
      const others = [
        meeting({ id: 'm-0', title: '32. Sitzung', date: '2026-10-01' }),
        meeting({ id: 'm-3', title: '35. Sitzung', date: '2026-11-12' }),
        meeting({ id: 'm-2', title: '34. Sitzung', date: '2026-10-29' }),
        own,
      ];
      const { session, api, fixture } = await withSession(own, final(), others);
      expect(screen.queryByRole('button', { name: 'Entwurf senden' })).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Als genehmigt markieren' }));
      fixture.detectChanges();
      expect(api.listMeetings).toHaveBeenCalledWith('g-1');
      const dialog = screen.getByRole('dialog', { name: 'Als genehmigt markieren' });
      expect(within(dialog).getByLabelText(/Genehmigt in der Sitzung/)).toHaveTextContent('34. Sitzung · 29. Oktober 2026');
      await userEvent.click(within(dialog).getByRole('button', { name: 'Als genehmigt markieren' }));
      expect(session.setProtocolApproval).toHaveBeenCalledWith('m-2');
      fixture.componentRef.setInput(
        'protocol',
        final({ approvedAt: '2026-10-29T18:00:00Z', approvedMeetingId: 'm-2', approvedMeetingTitle: '34. Sitzung', approvedMeetingDate: '2026-10-29' }),
      );
      fixture.detectChanges();
      expect(screen.queryByRole('dialog', { name: 'Als genehmigt markieren' })).toBeNull();
      expect(screen.getByRole('status')).toHaveTextContent('Genehmigt in: 34. Sitzung · 29. Oktober 2026.');
      await userEvent.click(screen.getByRole('button', { name: 'Genehmigung entfernen' }));
      fixture.detectChanges();
      expect(session.setProtocolApproval).toHaveBeenCalledTimes(1);
      const ask = screen.getByRole('dialog', { name: 'Genehmigung entfernen?' });
      await userEvent.click(within(ask).getByRole('button', { name: 'Entfernen' }));
      expect(session.setProtocolApproval).toHaveBeenLastCalledWith(null);
    });

    it('names the mark without its meeting, and offers no mark without the right', async () => {
      const { fixture } = await withSession(closed({ canFinalize: false }), final({ approvedAt: '2026-10-29T18:00:00Z' }));
      expect(screen.getByRole('status')).toHaveTextContent('Genehmigt.');
      expect(screen.queryByRole('button', { name: 'Genehmigung entfernen' })).toBeNull();
      fixture.componentRef.setInput('protocol', final());
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Als genehmigt markieren' })).toBeNull();
    });

    it('closes the pick on "Abbrechen"', async () => {
      const { session, fixture } = await withSession(closed(), final());
      await userEvent.click(screen.getByRole('button', { name: 'Als genehmigt markieren' }));
      fixture.detectChanges();
      await userEvent.click(within(screen.getByRole('dialog', { name: 'Als genehmigt markieren' })).getByRole('button', { name: 'Abbrechen' }));
      fixture.detectChanges();
      expect(screen.queryByRole('dialog', { name: 'Als genehmigt markieren' })).toBeNull();
      expect(session.setProtocolApproval).not.toHaveBeenCalled();
    });
  });

  describe('public gremium', () => {
    const final = (over: Partial<Protocol> = {}) =>
      protocol({ status: 'final', isFinal: true, isLocked: true, gremiumProtocolsPublic: true, ...over });

    async function withSession(m: Meeting, p: Protocol) {
      const session = {
        publicationSaving: signal(false),
        draftSending: signal(false),
        approvalSaving: signal(false),
        setPublicWithheld: jest.fn(),
      };
      await render(ProtocolBarComponent, {
        inputs: { meeting: m, protocol: p },
        providers: [{ provide: MeetingSessionService, useValue: session }],
      });
      return session;
    }

    it('says that a final protocol is public and offers to hold it back', async () => {
      const session = await withSession(closed(), final());
      expect(screen.getByRole('status')).toHaveTextContent('Öffentlich unter „Öffentliche Protokolle“.');
      await userEvent.click(screen.getByRole('button', { name: 'Nicht veröffentlichen' }));
      expect(session.setPublicWithheld).toHaveBeenCalledWith(true);
    });

    it('publishes a held-back protocol again', async () => {
      const session = await withSession(closed(), final({ publicWithheld: true }));
      expect(screen.getByRole('status')).toHaveTextContent('Nicht veröffentlicht.');
      await userEvent.click(screen.getByRole('button', { name: 'Veröffentlichen' }));
      expect(session.setPublicWithheld).toHaveBeenCalledWith(false);
    });

    it('offers no switch without the right, and nothing for a private gremium', async () => {
      await withSession(closed({ canFinalize: false }), final());
      expect(screen.queryByRole('button', { name: 'Nicht veröffentlichen' })).toBeNull();
      expect(screen.getByRole('status')).toHaveTextContent('Öffentlich');
    });

    it('shows no publication line for a gremium without the public page', async () => {
      await setup(closed(), final({ gremiumProtocolsPublic: false }));
      expect(screen.queryByText(/Öffentlich unter/)).toBeNull();
      expect(screen.queryByRole('button', { name: 'Nicht veröffentlichen' })).toBeNull();
    });

    it('offers no switch outside the meeting page (no session)', async () => {
      await setup(closed(), final());
      expect(screen.queryByRole('button', { name: 'Nicht veröffentlichen' })).toBeNull();
    });
  });
});
