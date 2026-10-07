import { render, screen } from '@testing-library/angular';
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
  it('offers the finalize of a draft to a holder of the right (O2, O13)', async () => {
    const { finalize } = await setup(closed(), protocol());
    expect(screen.getByRole('status')).toHaveTextContent('Entwurf · Das Protokoll ist noch nicht versandt.');
    await userEvent.click(screen.getByRole('button', { name: 'Finalisieren & versenden' }));
    expect(finalize).toHaveBeenCalled();
  });

  it('offers no finalize while the meeting is live', async () => {
    await setup(meeting(), protocol());
    expect(screen.queryByRole('button', { name: 'Finalisieren & versenden' })).toBeNull();
  });

  it('says what is missing to a writer without the right, and nothing to a reader', async () => {
    const { fixture } = await setup(closed({ canFinalize: false }), protocol());
    expect(screen.queryByRole('button', { name: 'Finalisieren & versenden' })).toBeNull();
    expect(screen.getByText(/Gremien-Recht „Protokoll finalisieren & versenden“/)).toBeInTheDocument();
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

  it('links the PDFs of a final protocol', async () => {
    const { fixture } = await setup(
      closed(),
      protocol({ status: 'final', isFinal: true, isLocked: true, pdfUrl: '/p.pdf', publicPdfUrl: '/pub.pdf', sentAt: '2026-10-16T08:00:00Z' }),
    );
    expect(screen.getByRole('status')).toHaveTextContent('Final · Das Protokoll ist final und wurde versandt.');
    expect(screen.getByRole('link', { name: 'PDF intern' })).toHaveAttribute('href', '/p.pdf');
    expect(screen.getByRole('link', { name: 'PDF öffentlich' })).toHaveAttribute('href', '/pub.pdf');
    expect(screen.getByRole('link', { name: 'PDF intern' })).toHaveAttribute('target', '_blank');
    expect(screen.queryByRole('button', { name: 'Finalisieren & versenden' })).toBeNull();
    // Nothing redacted and not sent yet: one PDF, and the bar does not claim a mail.
    fixture.componentRef.setInput('protocol', protocol({ status: 'final', isFinal: true, isLocked: true, pdfUrl: '/p.pdf' }));
    fixture.detectChanges();
    expect(screen.getByRole('status')).toHaveTextContent('Final · Das Protokoll ist final.');
    expect(screen.getByRole('link', { name: 'PDF' })).toHaveAttribute('href', '/p.pdf');
    expect(screen.queryByRole('link', { name: 'PDF öffentlich' })).toBeNull();
  });

  describe('public gremium', () => {
    const final = (over: Partial<Protocol> = {}) =>
      protocol({ status: 'final', isFinal: true, isLocked: true, gremiumProtocolsPublic: true, ...over });

    async function withSession(m: Meeting, p: Protocol) {
      const session = { publicationSaving: signal(false), setPublicWithheld: jest.fn() };
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
