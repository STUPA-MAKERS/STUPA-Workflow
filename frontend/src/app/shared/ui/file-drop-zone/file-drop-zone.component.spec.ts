import { fireEvent, render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../../testing/a11y';
import { FileDropZoneComponent, acceptsFile } from './file-drop-zone.component';

const pdf = new File(['%PDF'], 'Angebot.pdf', { type: 'application/pdf' });
const png = new File(['png'], 'Foto.PNG', { type: 'image/png' });
const exe = new File(['MZ'], 'setup.exe', { type: 'application/x-msdownload' });
const xml = new File(['<x/>'], 'rechnung.xml', { type: '' });

describe('acceptsFile', () => {
  it('accepts every file for an empty list', () => {
    expect(acceptsFile(exe, '')).toBe(true);
    expect(acceptsFile(exe, ' , ')).toBe(true);
  });

  it('matches extensions, wildcard types and exact types', () => {
    const accept = '.pdf, image/*, application/xml, .XML';
    expect(acceptsFile(pdf, accept)).toBe(true);
    expect(acceptsFile(png, accept)).toBe(true);
    expect(acceptsFile(xml, accept)).toBe(true);
    expect(acceptsFile(exe, accept)).toBe(false);
    expect(acceptsFile(pdf, 'application/pdf')).toBe(true);
    expect(acceptsFile(xml, 'application/xml')).toBe(false);
  });
});

describe('FileDropZoneComponent', () => {
  const base = {
    label: 'Dateien hierher ziehen oder auswählen',
    hint: 'PDF, Bilder · bis 10 MB je Datei',
    buttonLabel: 'Auswählen',
    accept: '.pdf,image/*',
  };

  async function setup(inputs: Record<string, unknown> = {}) {
    const files = jest.fn();
    const rejected = jest.fn();
    const view = await render(FileDropZoneComponent, {
      inputs: { ...base, ...inputs },
      on: { files, rejected },
    });
    const area = view.container.querySelector('.fdz') as HTMLElement;
    const picker = view.container.querySelector('input[type="file"]') as HTMLInputElement;
    return { view, files, rejected, area, picker };
  }

  function drop(target: HTMLElement, list: File[]) {
    fireEvent.drop(target, { dataTransfer: { files: list } });
  }

  it('describes the button with the label and the hint', async () => {
    const { view, picker } = await setup();
    const button = screen.getByRole('button', { name: 'Auswählen' });
    expect(button).toHaveAccessibleDescription(`${base.label} ${base.hint}`);
    expect(picker).toHaveAttribute('accept', '.pdf,image/*');
    expect(picker.multiple).toBe(true);
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('is described by the label alone without a hint', async () => {
    await setup({ hint: null });
    expect(screen.getByRole('button', { name: 'Auswählen' })).toHaveAccessibleDescription(
      base.label,
    );
  });

  it('opens the picker from the keyboard', async () => {
    const { picker } = await setup();
    const click = jest.spyOn(picker, 'click');
    const user = userEvent.setup();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Auswählen' })).toHaveFocus();
    await user.keyboard('{Enter}');
    await user.keyboard(' ');
    expect(click).toHaveBeenCalledTimes(2);
  });

  it('opens the picker on a click anywhere on the area, once', async () => {
    const { area, picker } = await setup();
    const click = jest.spyOn(picker, 'click').mockImplementation(() => undefined);
    fireEvent.click(area);
    fireEvent.click(screen.getByRole('button', { name: 'Auswählen' }));
    expect(click).toHaveBeenCalledTimes(2);
  });

  it('emits the picked files and clears the input', async () => {
    const { picker, files, rejected } = await setup();
    await userEvent.setup().upload(picker, [pdf, png]);
    expect(files).toHaveBeenCalledWith([pdf, png]);
    expect(rejected).not.toHaveBeenCalled();
    expect(picker.value).toBe('');
  });

  it('emits nothing for a change without a file list', async () => {
    const { picker, files } = await setup();
    Object.defineProperty(picker, 'files', { value: null });
    fireEvent.change(picker);
    expect(files).not.toHaveBeenCalled();
  });

  it('emits the accepted part of a drop and rejects the rest', async () => {
    const { area, files, rejected } = await setup();
    drop(area, [pdf, exe]);
    expect(files).toHaveBeenCalledWith([pdf]);
    expect(rejected).toHaveBeenCalledWith([exe]);
  });

  it('emits nothing when every dropped file is rejected', async () => {
    const { area, files, rejected } = await setup();
    drop(area, [exe]);
    expect(files).not.toHaveBeenCalled();
    expect(rejected).toHaveBeenCalledWith([exe]);
  });

  it('takes only the first dropped file when it holds one file', async () => {
    const { area, files, picker } = await setup({ multiple: false });
    expect(picker.multiple).toBe(false);
    drop(area, [pdf, png]);
    expect(files).toHaveBeenCalledWith([pdf]);
  });

  it('marks the area while a file is dragged over it', async () => {
    const { area, view } = await setup();
    fireEvent.dragEnter(area);
    // Entering a child fires another dragenter before the dragleave of the area.
    fireEvent.dragEnter(area.querySelector('.fdz__text') as HTMLElement);
    fireEvent.dragLeave(area);
    view.fixture.detectChanges();
    expect(area).toHaveClass('fdz--over');
    fireEvent.dragLeave(area);
    fireEvent.dragLeave(area);
    view.fixture.detectChanges();
    expect(area).not.toHaveClass('fdz--over');
  });

  it('allows the drop with a copy effect', async () => {
    const { area } = await setup();
    const dataTransfer = { dropEffect: 'none' };
    const event = fireEvent.dragOver(area, { dataTransfer });
    expect(event).toBe(false); // default prevented
    expect(dataTransfer.dropEffect).toBe('copy');
  });

  it('copes with a drag event without data', async () => {
    const { area, files } = await setup();
    fireEvent.dragOver(area);
    fireEvent.drop(area);
    expect(files).not.toHaveBeenCalled();
  });

  it('takes nothing while disabled', async () => {
    const { area, picker, files, view } = await setup({ disabled: true });
    const click = jest.spyOn(picker, 'click');
    expect(screen.getByRole('button', { name: 'Auswählen' })).toBeDisabled();
    expect(area).toHaveClass('fdz--disabled');
    fireEvent.click(area);
    expect(click).not.toHaveBeenCalled();
    fireEvent.dragEnter(area);
    view.fixture.detectChanges();
    expect(area).not.toHaveClass('fdz--over');
    const dataTransfer = { dropEffect: 'copy' };
    fireEvent.dragOver(area, { dataTransfer });
    expect(dataTransfer.dropEffect).toBe('none');
    drop(area, [pdf]);
    expect(files).not.toHaveBeenCalled();
  });
});
