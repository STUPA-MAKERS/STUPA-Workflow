import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { AgendaItem, Meeting, Protocol } from '@core/api/models';
import { MarkdownEditorComponent } from '@stupa-makers/ui-kit/markdown-editor';
import { AGENDA, meeting, protocol } from '../../../../testing/meeting-fixtures';
import { type SaveState, TopSheetComponent } from './top-sheet.component';

interface Inputs {
  meeting: Meeting;
  protocol: Protocol | null;
  top: AgendaItem | null;
  topIndex: number;
  editable: boolean;
  canEdit: boolean;
  saveState: SaveState;
  revision: number;
}

async function setup(over: Partial<Inputs> = {}) {
  const bodyChange = jest.fn();
  const finalize = jest.fn();
  const view = await render(TopSheetComponent, {
    inputs: {
      meeting: meeting(),
      protocol: protocol(),
      top: AGENDA[0],
      topIndex: 0,
      editable: true,
      canEdit: true,
      saveState: 'saved',
      revision: 0,
      ...over,
    },
    on: { bodyChange, finalize },
    providers: [provideRouter([])],
  });
  return { ...view, bodyChange, finalize };
}

function editorOf(view: Awaited<ReturnType<typeof setup>>): MarkdownEditorComponent {
  return view.fixture.debugElement.query((d) => d.componentInstance instanceof MarkdownEditorComponent)
    .componentInstance as MarkdownEditorComponent;
}

describe('TopSheetComponent', () => {
  it('names the item, its kind and the save state', async () => {
    await setup();
    expect(screen.getByText(/TOP 1 · Freitext/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Begrüßung' })).toBeInTheDocument();
    expect(screen.getByText('Gespeichert')).toBeInTheDocument();
    expect(screen.getByText('Entwurf')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Antrag öffnen/ })).toBeNull();
  });

  it('opens the application in a new tab and shows its state and the NÖ flag', async () => {
    await setup({ top: AGENDA[2], topIndex: 2 });
    expect(screen.getByText(/TOP 3 · Antrag/)).toHaveTextContent('Abstimmung');
    expect(screen.getByText(/Nicht öffentlich \(NÖ\)/)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /Antrag öffnen/ });
    expect(link).toHaveAttribute('href', '/applications/app-1');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('reports saving and a failed save', async () => {
    const { fixture } = await setup({ saveState: 'saving' });
    expect(screen.getByText('Wird gespeichert …')).toBeInTheDocument();
    fixture.componentRef.setInput('saveState', 'error');
    fixture.detectChanges();
    expect(screen.getByText('Speichern fehlgeschlagen')).toBeInTheDocument();
    fixture.componentRef.setInput('saveState', 'idle');
    fixture.detectChanges();
    expect(screen.queryByText('Speichern fehlgeschlagen')).toBeNull();
  });

  it('formats the text from the bar and shows the active format', async () => {
    const view = await setup();
    const editor = editorOf(view);
    const toggle = jest.spyOn(editor, 'toggleFormat').mockImplementation(() => undefined);
    const bar = screen.getByRole('toolbar', { name: 'Format' });
    expect(bar).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Fett' }));
    expect(toggle).toHaveBeenCalledWith('bold');
    await userEvent.click(screen.getByRole('button', { name: 'Überschrift' }));
    await userEvent.click(screen.getByRole('button', { name: 'Kursiv' }));
    await userEvent.click(screen.getByRole('button', { name: 'Liste' }));
    expect(toggle).toHaveBeenCalledTimes(4);
    editor.activeFormats.set(new Set(['italic']));
    view.fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Kursiv' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Fett' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('passes the edits of the text on', async () => {
    const view = await setup();
    editorOf(view).valueChange.emit('Neu.');
    expect(view.bodyChange).toHaveBeenCalledWith({ itemId: 't-1', body: 'Neu.' });
  });

  it('shows no format bar to a reader and names the minute-taker', async () => {
    await setup({ editable: false, canEdit: false });
    expect(screen.queryByRole('toolbar', { name: 'Format' })).toBeNull();
    expect(screen.getByText(/Pia Protokoll führt das Protokoll/)).toBeInTheDocument();
  });

  it('carries the state, the finalize and the PDFs of a closed meeting in the protocol bar', async () => {
    const { fixture, finalize, container } = await setup({ meeting: meeting({ status: 'closed' }) });
    const bar = screen.getByRole('status');
    expect(bar).toHaveTextContent('Entwurf · Das Protokoll ist noch nicht versandt.');
    // The foot of a live meeting is gone; the bar says it all.
    expect(container.querySelector('.ts__foot')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Finalisieren & versenden' }));
    expect(finalize).toHaveBeenCalled();
    fixture.componentRef.setInput(
      'protocol',
      protocol({ status: 'final', isFinal: true, isLocked: true, pdfUrl: '/p.pdf', publicPdfUrl: '/pub.pdf', sentAt: '2026-10-16T08:00:00Z' }),
    );
    fixture.componentRef.setInput('editable', false);
    fixture.detectChanges();
    expect(screen.getByRole('status')).toHaveTextContent('Final · Das Protokoll ist final und wurde versandt.');
    expect(screen.getByRole('link', { name: 'PDF intern' })).toHaveAttribute('href', '/p.pdf');
    expect(screen.getByRole('link', { name: 'PDF öffentlich' })).toHaveAttribute('href', '/pub.pdf');
    expect(screen.queryByRole('button', { name: 'Finalisieren & versenden' })).toBeNull();
    expect(screen.queryByText('Gespeichert')).toBeNull();
  });

  it('keeps the live foot: the protocol state and who writes', async () => {
    const { fixture, container } = await setup({ protocol: protocol({ status: 'rendering', isLocked: true }) });
    const foot = () => container.querySelector('.ts__foot') as HTMLElement;
    expect(foot().textContent?.trim()).toBe('Wird gerendert …');
    fixture.componentRef.setInput('protocol', protocol());
    fixture.componentRef.setInput('canEdit', false);
    fixture.detectChanges();
    expect(foot()).toHaveTextContent('Entwurf');
    expect(foot()).toHaveTextContent('Pia Protokoll führt das Protokoll — du liest mit.');
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('names every keeper of a closed meeting below the title', async () => {
    const periods = [
      { principalId: 'pr-1', name: 'Pia Protokoll', fromAt: '2026-10-15T16:04:00Z', toAt: '2026-10-15T16:55:00Z', fromAgendaItemId: 't-1', toAgendaItemId: 't-2', fromPosition: 1, toPosition: 2 },
      { principalId: 'pr-2', name: 'Mika Mitglied', fromAt: '2026-10-15T16:55:00Z', toAt: '2026-10-15T19:12:00Z', fromAgendaItemId: 't-2', toAgendaItemId: 't-3', fromPosition: 2, toPosition: 3 },
    ];
    const { fixture } = await setup({ meeting: meeting({ status: 'closed', keeperPeriods: periods }) });
    expect(screen.getByText('Protokoll: Pia Protokoll (TOP 1–2), Mika Mitglied (TOP 2–3)')).toBeInTheDocument();
    // A live meeting names its keeper in the dock, not here.
    fixture.componentRef.setInput('meeting', meeting({ keeperPeriods: periods }));
    fixture.detectChanges();
    expect(screen.queryByText(/^Protokoll: Pia Protokoll \(/)).toBeNull();
  });

  it('gives the vote cards of the text the result of the closed votes of the meeting', async () => {
    const closed = {
      id: 'v-1', applicationId: null, agendaItemId: 't-1', title: null, question: 'Frage?', options: ['yes', 'no', 'abstain'],
      status: 'closed' as const, result: 'rejected', counts: { yes: 2, no: 2, abstain: 0 }, leading: null, closesAt: null,
      voted: 4, present: 4, revealed: true, failedReason: 'majority' as const, majorityRule: 'simple' as const,
      closedAt: '2026-10-15T16:52:00Z',
    };
    const view = await setup({
      meeting: meeting({ votes: [closed] }),
      top: { ...AGENDA[0], body: '> [!abstimmung] **Frage?**\n> yes: 2, no: 2, abstain: 0' },
    });
    const card = view.container.querySelector('.mde__vote') as HTMLElement;
    expect(card.dataset['result']).toBe('rejected');
    expect(card.querySelector('.mde__voteKind')?.textContent).toMatch(/^Beschluss · \d\d:52 · Einfache Mehrheit$/);
    // O18: a tie is a rejection.
    expect(card.querySelector('.mde__voteResult')?.textContent).toBe('Abgelehnt');
  });

  it('explains the empty states', async () => {
    const { fixture } = await setup({ top: null, topIndex: -1 });
    expect(screen.getByText('Noch kein TOP geöffnet')).toBeInTheDocument();
    expect(screen.getByText('Wähle links einen TOP, um seinen Text zu bearbeiten.')).toBeInTheDocument();
    fixture.componentRef.setInput('protocol', null);
    fixture.detectChanges();
    expect(screen.getByText('Für diese Sitzung gibt es noch kein Protokoll.')).toBeInTheDocument();
    fixture.componentRef.setInput('meeting', meeting({ status: 'planned' }));
    fixture.detectChanges();
    expect(screen.getByText(/beim Start der Sitzung angelegt/)).toBeInTheDocument();
  });

  it('names an untitled item', async () => {
    await setup({ top: { ...AGENDA[0], title: null } });
    expect(screen.getByRole('heading', { level: 1, name: 'Unbenannter TOP' })).toBeInTheDocument();
  });
});
