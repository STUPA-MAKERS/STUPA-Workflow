import type { Provider } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { ToastService } from '@stupa-makers/ui-kit';
import { MediaApiService } from '@shared/markdown/media-api.service';
import { MarkdownImageUploadDirective } from '@shared/markdown/markdown-image-upload.directive';
import { renderDeferred } from '../../../../testing/defer';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { AgendaItem, Meeting, Protocol } from '@core/api/models';
import { MarkdownEditorComponent } from '@stupa-makers/ui-kit/markdown-editor';
import { AGENDA, meeting, protocol } from '../../../../testing/meeting-fixtures';
import { type SaveState, TopSheetComponent } from './top-sheet.component';
import { NO_LINKED_TODOS } from '../../../../testing/todo-fixtures';

interface Inputs {
  meeting: Meeting;
  protocol: Protocol | null;
  top: AgendaItem | null;
  topIndex: number;
  editable: boolean;
  canEdit: boolean;
  saveState: SaveState;
  revision: number;
  follow: boolean;
  canRename: boolean;
  renamingTopId: string | null;
}

async function setup(over: Partial<Inputs> = {}, extraProviders: Provider[] = []) {
  const bodyChange = jest.fn();
  const finalize = jest.fn();
  const startRename = jest.fn();
  const cancelRename = jest.fn();
  const renameTop = jest.fn();
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
    on: { bodyChange, finalize, startRename, cancelRename, renameTop },
    providers: [provideRouter([]), NO_LINKED_TODOS, ...extraProviders],
  });
  await renderDeferred(view.fixture);
  return { ...view, bodyChange, finalize, startRename, cancelRename, renameTop };
}

function editorOf(view: Awaited<ReturnType<typeof setup>>): MarkdownEditorComponent {
  return view.fixture.debugElement.query((d) => d.componentInstance instanceof MarkdownEditorComponent)
    .componentInstance as MarkdownEditorComponent;
}

const ID = '0f8fad5b-d9cb-469f-a165-70867728950e';

describe('TopSheetComponent', () => {
  it('lists the to-dos linked to the item, and leaves them out of the participant view', async () => {
    const { container, fixture } = await setup();
    expect(container.querySelector('app-todo-linked-list')).not.toBeNull();
    fixture.componentRef.setInput('follow', true);
    fixture.detectChanges();
    expect(container.querySelector('app-todo-linked-list')).toBeNull();
  });

  it('names the item, its kind and the save state', async () => {
    await setup();
    expect(screen.getByText('TOP 1')).toBeInTheDocument();
    expect(screen.queryByText(/Freitext/)).toBeNull();
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

  it('inserts a table and an image from the bar and edits the table from its menu', async () => {
    const view = await setup();
    const editor = editorOf(view);
    const table = jest.spyOn(editor, 'insertTable');
    const pick = jest.spyOn(editor, 'pickImage').mockImplementation(() => undefined);
    const command = jest.spyOn(editor, 'tableCommand');
    await userEvent.click(screen.getByRole('button', { name: 'Tabelle einfügen' }));
    expect(table).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Bild einfügen' }));
    expect(pick).toHaveBeenCalled();
    editor.inTable.set(true);
    view.fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Tabelle bearbeiten' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Zeile einfügen' }));
    expect(command).toHaveBeenCalledWith('addRowAfter');
    editor.inTable.set(false);
    view.fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Tabelle bearbeiten' })).toBeNull();
  });

  it('uploads an image of the editor through the media service and reports an error', async () => {
    const upload = jest
      .fn()
      .mockReturnValueOnce(of({ id: ID, url: `/api/media/images/${ID}`, mime: 'image/png', width: 1, height: 1, size: 1 }))
      .mockReturnValueOnce(throwError(() => ({ status: 413 })));
    const view = await setup({}, [{ provide: MediaApiService, useValue: { uploadImage: upload } }]);
    const uploader = editorOf(view).imageUpload();
    expect(uploader).not.toBeNull();
    const png = new File(['x'], 'Foto.der.Sitzung.png', { type: 'image/png' });
    await expect(uploader!(png)).resolves.toEqual({ src: `/api/media/images/${ID}`, alt: 'Foto.der.Sitzung' });
    const toast = TestBed.inject(ToastService);
    const error = jest.spyOn(toast, 'error');
    await expect(uploader!(png)).rejects.toEqual({ status: 413 });
    expect(error).toHaveBeenCalled();
  });

  it('gives a reader no image upload', async () => {
    const view = await setup({ editable: false });
    expect(editorOf(view).imageUpload()).toBeNull();
  });

  it('passes the edits of the text on', async () => {
    const view = await setup();
    editorOf(view).valueChange.emit('Neu.');
    expect(view.bodyChange).toHaveBeenCalledWith({ itemId: 't-1', body: 'Neu.' });
  });

  it('passes no change of a reader on, also when the editor emits one', async () => {
    const view = await setup({ editable: false });
    editorOf(view).valueChange.emit('Alter Text');
    expect(view.bodyChange).not.toHaveBeenCalled();
  });

  describe('view of the text', () => {
    it('switches to the Markdown source and back', async () => {
      const view = await setup({ top: { ...AGENDA[0], body: '**Hallo**' } });
      const formatted = screen.getByRole('radio', { name: 'Formatiert' });
      expect(formatted).toHaveAttribute('aria-checked', 'true');
      await userEvent.click(screen.getByRole('radio', { name: 'Markdown' }));
      const area = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Markdown' });
      expect(area.value).toBe('**Hallo**');
      await userEvent.type(area, '!');
      expect(view.bodyChange).toHaveBeenLastCalledWith({ itemId: 't-1', body: '**Hallo**!' });
      await userEvent.click(formatted);
      expect(screen.queryByRole('textbox', { name: 'Markdown' })).toBeNull();
      await renderDeferred(view.fixture);
      expect(editorOf(view)).toBeTruthy();
    });

    it('formats the Markdown source from the bar', async () => {
      const view = await setup({ top: { ...AGENDA[0], body: 'Wort' } });
      await userEvent.click(screen.getByRole('radio', { name: 'Markdown' }));
      const area = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Markdown' });
      area.setSelectionRange(0, 4);
      await userEvent.click(screen.getByRole('button', { name: 'Fett' }));
      expect(area.value).toBe('**Wort**');
      expect(view.bodyChange).toHaveBeenLastCalledWith({ itemId: 't-1', body: '**Wort**' });
      expect(screen.getByRole('button', { name: 'Fett' })).toHaveAttribute('aria-pressed', 'false');
    });

    it('inserts a table and opens the file dialog in the Markdown source', async () => {
      const view = await setup({ top: { ...AGENDA[0], body: 'Text' } });
      await userEvent.click(screen.getByRole('radio', { name: 'Markdown' }));
      const area = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Markdown' });
      area.setSelectionRange(4, 4);
      await userEvent.click(screen.getByRole('button', { name: 'Tabelle einfügen' }));
      expect(area.value).toBe('Text\n\n|  |  |  |\n| --- | --- | --- |\n|  |  |  |\n|  |  |  |\n');
      expect(view.bodyChange).toHaveBeenLastCalledWith({ itemId: 't-1', body: area.value });
      const directive = view.fixture.debugElement
        .query((d) => d.injector.get(MarkdownImageUploadDirective, null) !== null)
        .injector.get(MarkdownImageUploadDirective);
      const pick = jest.spyOn(directive, 'pick').mockImplementation(() => undefined);
      await userEvent.click(screen.getByRole('button', { name: 'Bild einfügen' }));
      expect(pick).toHaveBeenCalled();
      expect(screen.queryByRole('button', { name: 'Tabelle bearbeiten' })).toBeNull();
    });

    it('keeps the Markdown source of a reader read only', async () => {
      const view = await setup({ editable: false, top: { ...AGENDA[0], body: 'Text' } });
      await userEvent.click(screen.getByRole('radio', { name: 'Markdown' }));
      const area = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Markdown' });
      expect(area.readOnly).toBe(true);
      const cmp = view.fixture.componentInstance as unknown as {
        toggleFormat(f: string): void;
      };
      cmp.toggleFormat('bold');
      (cmp as unknown as { insertTable(): void }).insertTable();
      area.dispatchEvent(new Event('input'));
      expect(area.value).toBe('Text');
      expect(view.bodyChange).not.toHaveBeenCalled();
    });
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

  it('reminds the minute-taker of a public gremium that the text goes public', async () => {
    const notice = 'Dieses Protokoll wird öffentlich. Keine Namen Dritter im Freitext.';
    const view = await setup({ protocol: protocol({ gremiumProtocolsPublic: true }) });
    expect(screen.getByText(notice)).toBeInTheDocument();
    // A non-public item never goes public, a reader writes nothing.
    view.fixture.componentRef.setInput('top', { ...AGENDA[0], nonPublic: true });
    view.fixture.detectChanges();
    expect(screen.queryByText(notice)).toBeNull();
    view.fixture.componentRef.setInput('top', AGENDA[0]);
    view.fixture.componentRef.setInput('editable', false);
    view.fixture.detectChanges();
    expect(screen.queryByText(notice)).toBeNull();
  });

  it('shows no public notice for a gremium without the public page', async () => {
    await setup();
    expect(screen.queryByText(/Dieses Protokoll wird öffentlich/)).toBeNull();
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
    expect(screen.queryByText(/noch kein Protokoll/)).toBeNull();
  });

  it('prepares the text of an item of a planned meeting without a protocol', async () => {
    await setup({ protocol: null, meeting: meeting({ status: 'planned' }) });
    expect(screen.getByRole('toolbar', { name: 'Format' })).toBeInTheDocument();
    expect(screen.queryByText(/noch kein Protokoll/)).toBeNull();
    // No protocol yet, so no notice of the public protocol page and no protocol state.
    expect(screen.queryByText('Entwurf')).toBeNull();
  });

  it('names an untitled item', async () => {
    await setup({ top: { ...AGENDA[0], title: null } });
    expect(screen.getByRole('heading', { level: 1, name: 'Unbenannter TOP' })).toBeInTheDocument();
  });

  describe('participant view (follow)', () => {
    const member = (over: Partial<Meeting> = {}) =>
      meeting({ canWrite: false, isProtokollant: false, protokollantName: 'Mara Keller', currentAgendaItemId: 't-1', ...over });

    it('reads the text without a protocol, marks the item of the room and names the keeper', async () => {
      const view = await setup({ follow: true, protocol: null, editable: false, canEdit: false, meeting: member() });
      expect(screen.getByText('Jetzt')).toBeInTheDocument();
      expect(screen.getByText('Mara Keller führt das Protokoll')).toBeInTheDocument();
      const editor = editorOf(view);
      expect(editor.disabled()).toBe(true);
      expect(editor.value()).toBe('Eröffnet.');
      expect(editor.placeholder()).toBe('Noch kein Text zu diesem TOP.');
      // No format bar, no save state, no foot, no note about a missing protocol.
      expect(screen.queryByRole('toolbar')).toBeNull();
      expect(screen.queryByText('Entwurf')).toBeNull();
      expect(screen.queryByText(/Das Protokoll entsteht/)).toBeNull();
    });

    it('marks no item of the room in another item, a planned or a closed meeting', async () => {
      const { fixture } = await setup({ follow: true, protocol: null, meeting: member(), top: AGENDA[1], topIndex: 1 });
      expect(screen.queryByText('Jetzt')).toBeNull();
      fixture.componentRef.setInput('meeting', member({ status: 'closed' }));
      fixture.componentRef.setInput('top', AGENDA[0]);
      fixture.detectChanges();
      expect(screen.queryByText('Jetzt')).toBeNull();
      expect(screen.queryByText('Mara Keller führt das Protokoll')).toBeNull();
      fixture.componentRef.setInput('meeting', member({ currentAgendaItemId: null }));
      fixture.detectChanges();
      expect(screen.queryByText('Jetzt')).toBeNull();
    });

    it('shows the new text of the same item after a read of the agenda', async () => {
      const { fixture, container } = await setup({ follow: true, protocol: null, editable: false, canEdit: false, meeting: member() });
      expect(container.querySelector('.ProseMirror')?.textContent).toContain('Eröffnet.');
      fixture.componentRef.setInput('top', { ...AGENDA[0], body: 'Eröffnet. Die Sitzung ist beschlussfähig.' });
      fixture.detectChanges();
      expect(container.querySelector('.ProseMirror')?.textContent).toContain('Die Sitzung ist beschlussfähig.');
    });

    it('keeps the document of the minute-taker while the text changes', async () => {
      const view = await setup();
      const editor = editorOf(view);
      const key = editor.docKey();
      view.fixture.componentRef.setInput('top', { ...AGENDA[0], body: 'Eröffnet und getippt.' });
      view.fixture.detectChanges();
      expect(editor.docKey()).toBe(key);
      view.fixture.componentRef.setInput('revision', 1);
      view.fixture.detectChanges();
      expect(editor.docKey()).not.toBe(key);
    });

    it('names no keeper when nobody keeps the minutes', async () => {
      await setup({ follow: true, protocol: null, meeting: member({ protokollantName: null }) });
      expect(screen.queryByText(/führt das Protokoll/)).toBeNull();
    });
  });

  describe('rename by a click on the title', () => {
    /** Open the field: the click starts the rename, the parent then names the item. */
    async function openField(view: Awaited<ReturnType<typeof setup>>) {
      await userEvent.click(screen.getByRole('button', { name: 'TOP umbenennen: Begrüßung' }));
      expect(view.startRename).toHaveBeenCalledWith(AGENDA[0]);
      view.fixture.componentRef.setInput('renamingTopId', AGENDA[0].id);
      view.fixture.componentRef.setInput('renameDraft', 'Begrüßung');
      view.fixture.detectChanges();
      return screen.getByRole('textbox', { name: 'TOP umbenennen' });
    }

    it('opens the focused title field and saves on Enter once', async () => {
      const view = await setup({ canRename: true });
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Begrüßung');
      const field = await openField(view);
      expect(field).toHaveFocus();
      expect(field).toHaveValue('Begrüßung');
      await userEvent.type(field, '!{Enter}');
      expect(view.renameTop).toHaveBeenCalledTimes(1);
      expect(view.renameTop).toHaveBeenCalledWith(AGENDA[0]);
      expect(screen.queryByRole('textbox', { name: 'TOP umbenennen' })).toBeNull();
    });

    it('saves on blur and keeps the old title on Escape', async () => {
      const view = await setup({ canRename: true });
      let field = await openField(view);
      field.blur();
      view.fixture.detectChanges();
      expect(view.renameTop).toHaveBeenCalledTimes(1);
      view.fixture.componentRef.setInput('renamingTopId', null);
      view.fixture.detectChanges();
      field = await openField(view);
      await userEvent.type(field, '{Escape}');
      expect(view.cancelRename).toHaveBeenCalledTimes(1);
      expect(view.renameTop).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Begrüßung');
    });

    it('closes the field when the rename ends elsewhere', async () => {
      const view = await setup({ canRename: true });
      await openField(view);
      view.fixture.componentRef.setInput('renamingTopId', null);
      view.fixture.detectChanges();
      expect(screen.queryByRole('textbox', { name: 'TOP umbenennen' })).toBeNull();
      expect(view.renameTop).not.toHaveBeenCalled();
    });

    it('shows no field for a rename from the agenda pane', async () => {
      await setup({ canRename: true, renamingTopId: AGENDA[0].id });
      expect(screen.queryByRole('textbox', { name: 'TOP umbenennen' })).toBeNull();
    });

    it.each<[string, Partial<Inputs>]>([
      ['an application item', { canRename: true, top: AGENDA[2], topIndex: 2 }],
      ['a reader', {}],
      ['the participant view', { canRename: true, follow: true }],
    ])('keeps a plain title for %s', async (_name, over) => {
      await setup(over);
      expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /TOP umbenennen/ })).toBeNull();
    });
  });
});
