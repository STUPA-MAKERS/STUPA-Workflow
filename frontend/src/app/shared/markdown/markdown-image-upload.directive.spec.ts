import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { fireEvent, render } from '@testing-library/angular';
import { Subject } from 'rxjs';
import { ToastService } from '@stupa-makers/ui-kit';
import { MarkdownImageUploadDirective, imageUploadErrorKey } from './markdown-image-upload.directive';
import { MediaApiService, type MediaImage } from './media-api.service';

const ID = '0b8f3c3e-4d6a-4f43-9a1e-2f0c1d2e3f40';
const ID2 = '1b8f3c3e-4d6a-4f43-9a1e-2f0c1d2e3f40';

@Component({
  standalone: true,
  imports: [FormsModule, MarkdownImageUploadDirective],
  template: `<textarea
    appMarkdownImageUpload
    #up="mdImageUpload"
    [readOnly]="ro()"
    [ngModel]="text()"
    (ngModelChange)="text.set($event)"
  ></textarea>
  <button type="button" (click)="up.pick()">pick</button>`,
})
class HostComponent {
  readonly text = signal('');
  readonly ro = signal(false);
}

function png(name = 'Plan.png'): File {
  return new File(['x'], name, { type: 'image/png' });
}

function image(id: string): MediaImage {
  return { id, url: `/api/media/images/${id}`, mime: 'image/png', width: 1, height: 1, size: 1 };
}

async function setup(initial = '') {
  const calls: Subject<MediaImage>[] = [];
  const uploadImage = jest.fn(() => {
    const s = new Subject<MediaImage>();
    calls.push(s);
    return s.asObservable();
  });
  const view = await render(HostComponent, {
    providers: [{ provide: MediaApiService, useValue: { uploadImage } }],
  });
  const host = view.fixture.componentInstance;
  host.text.set(initial);
  view.detectChanges();
  await view.fixture.whenStable();
  const area = view.container.querySelector('textarea') as HTMLTextAreaElement;
  const toast = view.fixture.debugElement.injector.get(ToastService);
  const error = jest.spyOn(toast, 'error');
  const dir = view.fixture.debugElement
    .query((d) => d.nativeElement === area)
    .injector.get(MarkdownImageUploadDirective);
  return { view, host, area, calls, uploadImage, error, dir };
}

describe('imageUploadErrorKey', () => {
  it('maps the status to a text', () => {
    expect(imageUploadErrorKey(413)).toBe('markdown.image.error.tooLarge');
    expect(imageUploadErrorKey(415)).toBe('markdown.image.error.type');
    expect(imageUploadErrorKey(429)).toBe('markdown.image.error.rate');
    expect(imageUploadErrorKey(503)).toBe('markdown.image.error.storage');
    expect(imageUploadErrorKey(500)).toBe('markdown.image.error.upload');
    expect(imageUploadErrorKey()).toBe('markdown.image.error.upload');
  });
});

describe('MarkdownImageUploadDirective', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('uploads a pasted image and replaces the placeholder at the caret', async () => {
    const { host, area, calls, dir } = await setup('Text');
    area.focus();
    area.setSelectionRange(4, 4);
    const ev = fireEvent.paste(area, { clipboardData: { files: [png()] } });
    expect(ev).toBe(false);
    expect(host.text()).toMatch(/^Text\n!\[Bild wird hochgeladen … #\d+\]\(\)\n$/);
    expect(dir.uploading()).toBe(1);
    calls[0].next(image(ID));
    calls[0].complete();
    expect(host.text()).toBe(`Text\n![Plan](/api/media/images/${ID})\n`);
    expect(area.selectionStart).toBe(host.text().length - 1);
    expect(dir.uploading()).toBe(0);
  });

  it('ignores a paste without image files', async () => {
    const { area, uploadImage } = await setup();
    const pdf = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    expect(fireEvent.paste(area, { clipboardData: { files: [pdf] } })).toBe(true);
    expect(fireEvent.paste(area, {})).toBe(true);
    expect(uploadImage).not.toHaveBeenCalled();
  });

  it('uploads dropped images one after the other', async () => {
    const { host, area, calls } = await setup('a\n');
    area.setSelectionRange(2, 2);
    expect(fireEvent.drop(area, { dataTransfer: { files: [png('x.png'), png('y.webp')] } })).toBe(false);
    expect(calls).toHaveLength(1);
    calls[0].next(image(ID));
    calls[0].complete();
    expect(calls).toHaveLength(2);
    calls[1].next(image(ID2));
    calls[1].complete();
    expect(host.text()).toContain(`![x](/api/media/images/${ID})`);
    expect(host.text()).toContain(`![y](/api/media/images/${ID2})`);
    expect(host.text()).not.toContain('Bild wird hochgeladen');
  });

  it('lets an image drag in and ignores a drop without images', async () => {
    const { area, uploadImage } = await setup();
    expect(fireEvent.dragOver(area, { dataTransfer: { items: [{ type: 'image/png' }] } })).toBe(false);
    expect(fireEvent.dragOver(area, { dataTransfer: { items: [{ type: 'text/plain' }] } })).toBe(true);
    expect(fireEvent.dragOver(area, {})).toBe(true);
    expect(fireEvent.drop(area, {})).toBe(true);
    expect(uploadImage).not.toHaveBeenCalled();
  });

  it('removes the placeholder and names the error', async () => {
    const { host, area, calls, error } = await setup('vor\nnach');
    area.setSelectionRange(4, 4);
    fireEvent.paste(area, { clipboardData: { files: [png()] } });
    calls[0].error({ status: 413 });
    expect(host.text()).toBe('vor\nnach');
    expect(error).toHaveBeenCalledWith('Bild zu groß (max. 10 MB).');
  });

  it('drops the image when the user deleted the placeholder', async () => {
    const { host, area, calls, dir } = await setup('x');
    fireEvent.paste(area, { clipboardData: { files: [png()] } });
    area.value = 'neu';
    fireEvent.input(area);
    calls[0].next(image(ID));
    calls[0].complete();
    expect(host.text()).toBe('neu');
    expect(dir.uploading()).toBe(0);
  });

  it('drops the results when the textarea shows another text', async () => {
    const { host, area, calls, dir, error } = await setup('Dokument A');
    dir.upload([png(), png('b.png')]);
    host.text.set('Dokument B');
    area.value = 'Dokument B';
    fireEvent.input(area);
    calls[0].next(image(ID));
    calls[0].complete();
    expect(host.text()).toBe('Dokument B');
    calls[1].error(null);
    expect(host.text()).toBe('Dokument B');
    expect(error).toHaveBeenCalledWith('Bild-Upload fehlgeschlagen.');
    expect(dir.uploading()).toBe(0);
  });

  it('does nothing on a read-only textarea', async () => {
    const { host, view, area, uploadImage, dir } = await setup('fix');
    host.ro.set(true);
    view.detectChanges();
    expect(fireEvent.paste(area, { clipboardData: { files: [png()] } })).toBe(true);
    expect(fireEvent.drop(area, { dataTransfer: { files: [png()] } })).toBe(true);
    dir.upload([png()]);
    const click = jest.spyOn(HTMLInputElement.prototype, 'click');
    dir.pick();
    expect(click).not.toHaveBeenCalled();
    click.mockRestore();
    expect(uploadImage).not.toHaveBeenCalled();
    expect(host.text()).toBe('fix');
  });

  it('picks files through a hidden file input', async () => {
    const { view, calls } = await setup();
    const click = jest.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => undefined);
    fireEvent.click(view.getByText('pick'));
    expect(click).toHaveBeenCalledTimes(1);
    const input = click.mock.contexts[0] as HTMLInputElement;
    expect(input.accept).toBe('image/png,image/jpeg,image/gif,image/webp');
    expect(input.multiple).toBe(true);
    Object.defineProperty(input, 'files', { value: [png()], configurable: true });
    fireEvent.change(input);
    expect(calls).toHaveLength(1);
    Object.defineProperty(input, 'files', { value: null, configurable: true });
    fireEvent.change(input);
    expect(calls).toHaveLength(1);
    click.mockRestore();
  });

  it('ignores a picked set without images', async () => {
    const { uploadImage, dir } = await setup();
    dir.upload([new File(['x'], 'a.txt', { type: 'text/plain' })]);
    expect(uploadImage).not.toHaveBeenCalled();
  });
});
