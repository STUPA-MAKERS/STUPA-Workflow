import { computed, signal } from '@angular/core';
import { FormGroup } from '@angular/forms';
import { render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { ToastService } from '@stupa-makers/ui-kit';
import { provideFormly } from '@shared/formly/formly.providers';
import {
  DraftAttachmentsService,
  type DraftFile,
  type PendingUpload,
} from '../draft-attachments.service';
import { DraftFilesComponent } from './draft-files.component';
import { FormlyDraftFilesType } from './formly-draft-files.type';

function draft(id: string, extra: Partial<DraftFile> = {}): DraftFile {
  return {
    id,
    filename: `${id}.pdf`,
    mime: 'application/pdf',
    size: 212 * 1024,
    scanned: false,
    isComparisonOffer: false,
    scanState: 'scanning',
    fieldKey: null,
    ...extra,
  };
}

function fakeDrafts(files: DraftFile[] = [], pending: PendingUpload[] = []) {
  const list = signal(files);
  const usable = computed(() => list().filter((f) => !f.failed));
  return {
    files: list,
    pending: signal(pending),
    busy: signal(pending.length > 0),
    limits: signal({ maxFileBytes: 10 * 1024 * 1024, maxDraftFiles: 20, maxDraftBytes: 50 * 1024 * 1024 }),
    count: computed(() => usable().length),
    bytes: computed(() => usable().reduce((s, f) => s + f.size, 0)),
    filesOf: (key: string | null) => list().filter((f) => f.fieldKey === key),
    upload: jest.fn(async (fs: File[]) => {
      const added = fs.map((f, i) => draft(`n${i}`, { filename: f.name }));
      list.update((l) => [...l, ...added]);
      return { uploaded: added, failed: [{ filename: 'bad.exe', reason: 'apply.files.error.type' }] };
    }),
    remove: jest.fn(async (id: string) => {
      list.update((l) => l.filter((f) => f.id !== id));
      return id !== 'keep';
    }),
  };
}

async function setup(
  inputs: Record<string, unknown> = {},
  drafts = fakeDrafts(),
  changed = jest.fn(),
) {
  const toast = { error: jest.fn(), show: jest.fn(), success: jest.fn() };
  const view = await render(DraftFilesComponent, {
    inputs: { heading: 'Anhänge', ...inputs },
    on: { changed },
    providers: [
      { provide: DraftAttachmentsService, useValue: drafts },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, drafts, toast, changed };
}

describe('DraftFilesComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('lists the files with size, scan state, tag and a remove button', async () => {
    await setup(
      { summary: true },
      fakeDrafts([
        draft('a', { isComparisonOffer: true }),
        draft('b', { scanState: 'clean', scanned: true, size: 2 * 1024 * 1024 }),
        draft('c', { failed: true, size: 512 }),
      ]),
    );
    expect(screen.getByRole('heading', { name: 'Anhänge' })).toBeInTheDocument();
    expect(screen.getByText('2 von 20 Dateien · 2,2 MB von 50 MB')).toBeInTheDocument();
    expect(screen.getByText('212 KB')).toBeInTheDocument();
    expect(screen.getByText('In Prüfung')).toBeInTheDocument();
    expect(screen.getByText('Gescannt')).toBeInTheDocument();
    expect(screen.getByText('Nicht mehr vorhanden')).toBeInTheDocument();
    expect(screen.getAllByText('Vergleichsangebot')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'a.pdf entfernen' })).toBeInTheDocument();
    expect(
      screen.getByText('PDF, Bilder, Word, Excel, PowerPoint, OpenDocument · bis 10 MB je Datei'),
    ).toBeInTheDocument();
    // No checkbox without `comparison`.
    expect(screen.queryByRole('checkbox')).toBeNull();
  });

  it('shows only the files of its field and the pending uploads', async () => {
    await setup(
      { fieldKey: 'offer', required: true, error: 'Bitte lade mindestens eine Datei hoch.' },
      fakeDrafts(
        [draft('a', { fieldKey: 'offer' }), draft('b')],
        [{ key: 1, filename: 'up.pdf', size: 2048, fieldKey: 'offer' }, { key: 2, filename: 'other.pdf', size: 1, fieldKey: null }],
      ),
    );
    expect(screen.getByText('a.pdf')).toBeInTheDocument();
    expect(screen.queryByText('b.pdf')).toBeNull();
    expect(screen.getByText('up.pdf')).toBeInTheDocument();
    expect(screen.queryByText('other.pdf')).toBeNull();
    expect(screen.getByText(/Wird hochgeladen/)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Bitte lade mindestens eine Datei hoch.');
    expect(screen.getByText('*')).toBeInTheDocument();
    // The summary is the general block's.
    expect(screen.queryByText(/von 20 Dateien/)).toBeNull();
  });

  it('uploads picked files as comparison offers when the box is set', async () => {
    const { drafts, toast, changed, container } = await setup({ comparison: true });
    await userEvent.click(screen.getByRole('checkbox', { name: 'Als Vergleichsangebot hochladen' }));
    const input = container.querySelector('input[type=file]') as HTMLInputElement;
    await userEvent.upload(input, new File(['x'], 'Angebot.pdf', { type: 'application/pdf' }));
    await waitFor(() => expect(drafts.upload).toHaveBeenCalled());
    expect(drafts.upload.mock.calls[0][1]).toEqual({ fieldKey: null, isComparisonOffer: true });
    await waitFor(() => expect(changed).toHaveBeenCalledWith(['n0']));
    expect(toast.error).toHaveBeenCalledWith('bad.exe: Dieser Dateityp ist nicht erlaubt.');
  });

  it('removes a file and reports a refused delete', async () => {
    const { drafts, toast, changed } = await setup(
      {},
      fakeDrafts([draft('a'), draft('keep'), draft('x', { failed: true })]),
    );
    await userEvent.click(screen.getByRole('button', { name: 'a.pdf entfernen' }));
    expect(drafts.remove).toHaveBeenCalledWith('a');
    expect(changed).toHaveBeenLastCalledWith(['keep']);
    await userEvent.click(screen.getByRole('button', { name: 'keep.pdf entfernen' }));
    expect(toast.error).toHaveBeenCalledWith('Die Datei konnte nicht entfernt werden.');
  });

  it('names a dropped file of a wrong type', async () => {
    const { toast, fixture } = await setup();
    (fixture.componentInstance as unknown as { onRejected(f: File[]): void }).onRejected([
      new File(['x'], 'tool.exe'),
    ]);
    expect(toast.error).toHaveBeenCalledWith('tool.exe: Dieser Dateityp ist nicht erlaubt.');
  });
});

describe('FormlyDraftFilesType', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('keeps the ids of its field as the value and shows the required error', async () => {
    const drafts = fakeDrafts();
    const form = new FormGroup({});
    const model: Record<string, unknown> = {};
    const fields: FormlyFieldConfig[] = [
      { key: 'receipt', type: FormlyDraftFilesType, props: { label: 'Beleg', required: true } },
    ];
    const { fixture, container } = await render(FormlyForm, {
      inputs: { form, fields, model },
      providers: [
        provideFormly(),
        { provide: DraftAttachmentsService, useValue: drafts },
        { provide: ToastService, useValue: { error: jest.fn() } },
      ],
    });
    expect(screen.getByRole('heading', { name: /Beleg/ })).toBeInTheDocument();
    expect(form.valid).toBe(false);
    form.markAllAsTouched();
    fixture.detectChanges();
    expect(await screen.findByRole('alert')).toHaveTextContent('Bitte lade mindestens eine Datei hoch.');

    drafts.upload.mockImplementationOnce(async (fs: File[]) => {
      const added = fs.map(() => draft('r1', { fieldKey: 'receipt' }));
      drafts.files.update((l) => [...l, ...added]);
      return { uploaded: added, failed: [] };
    });
    const input = container.querySelector('input[type=file]') as HTMLInputElement;
    await userEvent.upload(input, new File(['x'], 'Beleg.pdf', { type: 'application/pdf' }));
    await waitFor(() => expect(model['receipt']).toEqual(['r1']));
    expect(form.valid).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: 'r1.pdf entfernen' }));
    await waitFor(() => expect(model['receipt']).toBeNull());
  });

  it('works without a key and a label', async () => {
    const fields: FormlyFieldConfig[] = [{ type: FormlyDraftFilesType }];
    await render(FormlyForm, {
      inputs: { form: new FormGroup({}), fields, model: {} },
      providers: [
        provideFormly(),
        { provide: DraftAttachmentsService, useValue: fakeDrafts() },
        { provide: ToastService, useValue: { error: jest.fn() } },
      ],
    });
    expect(screen.getByRole('heading')).toHaveTextContent('');
  });
});
