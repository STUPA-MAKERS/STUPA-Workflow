import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MediaApiService, markdownImage } from './media-api.service';

const ID = '0b8f3c3e-4d6a-4f43-9a1e-2f0c1d2e3f40';

describe('MediaApiService', () => {
  it('posts the file as multipart field "file"', () => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    const api = TestBed.inject(MediaApiService);
    const http = TestBed.inject(HttpTestingController);
    let got: string | undefined;
    const file = new File(['x'], 'a.png', { type: 'image/png' });
    api.uploadImage(file).subscribe((m) => (got = m.url));
    const req = http.expectOne('/api/media/images');
    expect(req.request.method).toBe('POST');
    expect((req.request.body as FormData).get('file')).toBe(file);
    req.flush({ id: ID, url: `/api/media/images/${ID}`, mime: 'image/png', width: 1, height: 1, size: 1 });
    expect(got).toBe(`/api/media/images/${ID}`);
    http.verify();
  });

  it('posts a PDF to the meeting and reads its info (spec 000862)', () => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    const api = TestBed.inject(MediaApiService);
    const http = TestBed.inject(HttpTestingController);
    const doc = { id: ID, url: `/api/media/documents/${ID}`, name: 'a.pdf', size: 1, pages: 2 };
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    let pages: number | undefined;
    api.uploadDocument('m1', file).subscribe((d) => (pages = d.pages));
    const up = http.expectOne('/api/meetings/m1/documents');
    expect(up.request.method).toBe('POST');
    expect((up.request.body as FormData).get('file')).toBe(file);
    up.flush(doc);
    expect(pages).toBe(2);
    let name: string | undefined;
    api.documentInfo(doc.url).subscribe((d) => (name = d.name));
    http.expectOne(`${doc.url}/info`).flush(doc);
    expect(name).toBe('a.pdf');
    http.verify();
  });
});

describe('media helpers', () => {
  it('writes an image reference with a clean alt text', () => {
    expect(markdownImage('Plan', ID)).toBe(`![Plan](/api/media/images/${ID})`);
    expect(markdownImage(' a]b[\\c\n d ', ID)).toBe(`![abc d](/api/media/images/${ID})`);
  });
});
