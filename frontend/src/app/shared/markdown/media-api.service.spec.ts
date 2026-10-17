import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MEDIA_IMAGE_PATH_RE, MediaApiService, markdownImage } from './media-api.service';

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
});

describe('media helpers', () => {
  it('matches only the canonical lowercase path', () => {
    expect(MEDIA_IMAGE_PATH_RE.exec(`/api/media/images/${ID}`)?.[1]).toBe(ID);
    expect(MEDIA_IMAGE_PATH_RE.test(`/api/media/images/${ID.toUpperCase()}`)).toBe(false);
    expect(MEDIA_IMAGE_PATH_RE.test(`/api/media/images/${ID}/x`)).toBe(false);
  });

  it('writes an image reference with a clean alt text', () => {
    expect(markdownImage('Plan', ID)).toBe(`![Plan](/api/media/images/${ID})`);
    expect(markdownImage(' a]b[\\c\n d ', ID)).toBe(`![abc d](/api/media/images/${ID})`);
  });
});
