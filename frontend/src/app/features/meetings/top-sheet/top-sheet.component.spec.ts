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
    on: { bodyChange },
    providers: [provideRouter([])],
  });
  return { ...view, bodyChange };
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

  it('offers the PDFs of a final protocol and hides the save state', async () => {
    await setup({
      editable: false,
      meeting: meeting({ status: 'closed' }),
      protocol: protocol({ status: 'final', isFinal: true, isLocked: true, pdfUrl: '/p.pdf', publicPdfUrl: '/pub.pdf' }),
    });
    expect(screen.getByText('Final')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Internes Protokoll' })).toHaveAttribute('href', '/p.pdf');
    expect(screen.getByRole('link', { name: 'Öffentliches Protokoll' })).toHaveAttribute('href', '/pub.pdf');
    expect(screen.queryByText('Gespeichert')).toBeNull();
    expect(screen.getByText('Das Protokoll ist final und wurde versandt.')).toBeInTheDocument();
  });

  it('offers one PDF link when nothing is redacted', async () => {
    await setup({ protocol: protocol({ status: 'final', isFinal: true, isLocked: true, pdfUrl: '/p.pdf' }) });
    expect(screen.getByRole('link', { name: 'PDF öffnen' })).toBeInTheDocument();
  });

  it('says what the render and the finalize need', async () => {
    const { fixture } = await setup({ protocol: protocol({ status: 'rendering', isLocked: true }) });
    expect(screen.getByText('Wird gerendert …')).toBeInTheDocument();
    fixture.componentRef.setInput('protocol', protocol());
    fixture.detectChanges();
    expect(screen.getByText(/finalisierst du das Protokoll als eigenen Schritt/)).toBeInTheDocument();
    fixture.componentRef.setInput('meeting', meeting({ status: 'closed' }));
    fixture.detectChanges();
    expect(screen.getByText(/Prüfe das Protokoll und finalisiere es/)).toBeInTheDocument();
    fixture.componentRef.setInput('meeting', meeting({ status: 'closed', canFinalize: false }));
    fixture.detectChanges();
    expect(screen.getByText(/Gremien-Recht „Protokoll finalisieren“/)).toBeInTheDocument();
    fixture.componentRef.setInput('meeting', meeting({ canFinalize: false, canWrite: false }));
    fixture.detectChanges();
    expect(screen.queryByText(/Gremien-Recht/)).toBeNull();
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
