import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { Attachment, DraftUpload, ProblemDetail } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { AltchaService } from './altcha.service';
import {
  DRAFT_FILES_KEY,
  DraftAttachmentsService,
  uploadErrorKey,
} from './draft-attachments.service';

const LIMITS = { maxFileBytes: 100, maxDraftFiles: 3, maxDraftBytes: 250 };

function attachment(id: string, size = 10, extra: Partial<Attachment> = {}): Attachment {
  return {
    id,
    filename: `${id}.pdf`,
    mime: 'application/pdf',
    size,
    scanned: false,
    isComparisonOffer: false,
    scanState: 'scanning',
    ...extra,
  };
}

function file(name: string, size = 10): File {
  return new File(['x'.repeat(size)], name, { type: 'application/pdf' });
}

function httpError(status: number, error: Partial<ProblemDetail> | null = null) {
  return new HttpErrorResponse({ status, error });
}

interface Setup {
  svc: DraftAttachmentsService;
  upload: jest.Mock;
  remove: jest.Mock;
  solve: jest.Mock;
}

function setup(
  opts: {
    loggedIn?: boolean;
    upload?: jest.Mock;
    remove?: jest.Mock;
    solve?: jest.Mock;
  } = {},
): Setup {
  let n = 0;
  const upload =
    opts.upload ??
    jest.fn((f: File, o: { fieldKey?: string | null; isComparisonOffer?: boolean }) => {
      n++;
      const res: DraftUpload = {
        attachment: attachment(`d${n}`, f.size, {
          filename: f.name,
          isComparisonOffer: !!o.isComparisonOffer,
        }),
        draftToken: 'tok',
        draftExpiresAt: '2999-01-01T00:00:00Z',
      };
      return of(res);
    });
  const remove = opts.remove ?? jest.fn(() => of(undefined));
  const solve = opts.solve ?? jest.fn(async () => 'solution');
  TestBed.configureTestingModule({
    providers: [
      DraftAttachmentsService,
      { provide: ApiClient, useValue: { uploadDraftAttachment: upload, deleteDraftAttachment: remove } },
      { provide: AuthService, useValue: { isAuthenticated: signal(!!opts.loggedIn) } },
      { provide: AltchaService, useValue: { solve } },
      { provide: BrandingService, useValue: { attachmentLimits: signal(LIMITS) } },
    ],
  });
  return { svc: TestBed.inject(DraftAttachmentsService), upload, remove, solve };
}

describe('DraftAttachmentsService', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    sessionStorage.clear();
    jest.restoreAllMocks();
  });

  it('solves ALTCHA only for the first anonymous upload and reuses the token', async () => {
    const { svc, upload, solve } = setup();
    const res = await svc.upload([file('a.pdf'), file('b.pdf')], { fieldKey: 'offer' });
    expect(res.failed).toEqual([]);
    expect(res.uploaded.map((f) => f.fieldKey)).toEqual(['offer', 'offer']);
    expect(solve).toHaveBeenCalledTimes(1);
    expect(upload.mock.calls[0][1]).toMatchObject({ token: null, altcha: 'solution', fieldKey: 'offer' });
    expect(upload.mock.calls[1][1]).toMatchObject({ token: 'tok', altcha: null });
    expect(svc.token()).toBe('tok');
    expect(svc.attachmentIds()).toEqual(['d1', 'd2']);
    expect(svc.count()).toBe(2);
    expect(svc.bytes()).toBe(20);
    expect(svc.filesOf('offer')).toHaveLength(2);
    expect(svc.filesOf(null)).toHaveLength(0);
    expect(svc.busy()).toBe(false);
  });

  it('needs no ALTCHA for a signed-in applicant', async () => {
    const { svc, upload, solve } = setup({ loggedIn: true });
    await svc.upload([file('a.pdf')], { isComparisonOffer: true });
    expect(solve).not.toHaveBeenCalled();
    expect(upload.mock.calls[0][1]).toMatchObject({ altcha: null, isComparisonOffer: true, fieldKey: null });
    expect(svc.files()[0].isComparisonOffer).toBe(true);
  });

  it('keeps the token and the files in sessionStorage only, and restores them', async () => {
    localStorage.clear();
    const { svc } = setup();
    await svc.upload([file('a.pdf')]);
    const raw = sessionStorage.getItem(DRAFT_FILES_KEY);
    expect(JSON.parse(raw as string)).toMatchObject({ token: 'tok', files: [{ id: 'd1' }] });
    // Never into localStorage.
    expect(localStorage.length).toBe(0);

    TestBed.resetTestingModule();
    const again = setup().svc;
    expect(again.token()).toBe('tok');
    expect(again.files().map((f) => f.id)).toEqual(['d1']);
  });

  it('drops an expired, broken or empty stored draft', () => {
    sessionStorage.setItem(
      DRAFT_FILES_KEY,
      JSON.stringify({ token: 'old', expiresAt: '2000-01-01T00:00:00Z', files: [] }),
    );
    expect(setup().svc.token()).toBeNull();
    expect(sessionStorage.getItem(DRAFT_FILES_KEY)).toBeNull();

    TestBed.resetTestingModule();
    sessionStorage.setItem(DRAFT_FILES_KEY, '{broken');
    expect(setup().svc.token()).toBeNull();

    TestBed.resetTestingModule();
    sessionStorage.setItem(DRAFT_FILES_KEY, JSON.stringify({ files: [] }));
    expect(setup().svc.token()).toBeNull();

    TestBed.resetTestingModule();
    sessionStorage.setItem(
      DRAFT_FILES_KEY,
      JSON.stringify({ token: 't', files: 'nope' }),
    );
    expect(setup().svc.files()).toEqual([]);

    TestBed.resetTestingModule();
    sessionStorage.setItem(
      DRAFT_FILES_KEY,
      JSON.stringify({ token: 't', files: [{ id: 'x', filename: 'x', size: 1 }, null, { id: 2 }] }),
    );
    const svc = setup().svc;
    expect(svc.files().map((f) => f.id)).toEqual(['x']);
  });

  it('works without storage when the storage throws', async () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const { svc } = setup();
    await svc.upload([file('a.pdf')]);
    expect(svc.files()).toHaveLength(1);
    svc.clear();
    expect(svc.files()).toEqual([]);
  });

  it('refuses files over the limits before it sends them', async () => {
    const { svc, upload } = setup();
    const res = await svc.upload([file('big.pdf', 101), file('a.pdf', 90), file('b.pdf', 90), file('c.pdf', 90)]);
    expect(res.failed).toEqual([
      { filename: 'big.pdf', reason: 'apply.files.error.tooLarge' },
      { filename: 'c.pdf', reason: 'apply.files.error.quota' },
    ]);
    expect(upload).toHaveBeenCalledTimes(2);
    await svc.upload([file('d.pdf', 1)]);
    const res2 = await svc.upload([file('e.pdf', 1)]);
    expect(res2.failed).toEqual([{ filename: 'e.pdf', reason: 'apply.files.error.tooMany' }]);
  });

  it('reports a refused upload with its reason and keeps the others', async () => {
    const upload = jest.fn(() => throwError(() => httpError(415)));
    const { svc } = setup({ upload });
    const res = await svc.upload([file('x.exe')]);
    expect(res.failed).toEqual([{ filename: 'x.exe', reason: 'apply.files.error.type' }]);
    expect(svc.files()).toEqual([]);
    expect(svc.pending()).toEqual([]);
  });

  it('starts a new draft once when the server no longer knows the token', async () => {
    let calls = 0;
    const upload = jest.fn((f: File, o: { token?: string | null }) => {
      calls++;
      if (calls === 2 && o.token === 'tok') {
        return throwError(() => httpError(422, { code: 'draft_token_invalid' }));
      }
      return of({
        attachment: attachment(`d${calls}`, f.size),
        draftToken: calls < 2 ? 'tok' : 'tok2',
        draftExpiresAt: '2999-01-01T00:00:00Z',
      });
    });
    const { svc, solve } = setup({ upload });
    await svc.upload([file('a.pdf')]);
    const res = await svc.upload([file('b.pdf')]);
    expect(res.failed).toEqual([]);
    expect(svc.token()).toBe('tok2');
    // The first file belonged to the lost token: it is failed now.
    expect(svc.files().map((f) => [f.id, !!f.failed])).toEqual([
      ['d1', true],
      ['d3', false],
    ]);
    expect(svc.hasFailed()).toBe(true);
    expect(solve).toHaveBeenCalledTimes(2);
  });

  it('does not retry other 422 problems', async () => {
    const upload = jest.fn(() => throwError(() => httpError(422, { code: 'other' })));
    const { svc } = setup({ upload });
    const res = await svc.upload([file('a.pdf')]);
    expect(res.failed[0].reason).toBe('apply.files.error.upload');
    expect(upload).toHaveBeenCalledTimes(1);
  });

  it('marks the ids that the submit names as missing', async () => {
    const { svc } = setup();
    await svc.upload([file('a.pdf'), file('b.pdf')]);
    const lost = svc.markFailed({
      code: 'draft_attachments_missing',
      errors: [
        { field: 'attachmentIds.d2', msg: 'missing' },
        { field: 'data.title', msg: 'other' },
        { field: 'attachmentIds.unknown', msg: 'missing' },
      ],
    } as ProblemDetail);
    expect(lost).toEqual(['d2']);
    expect(svc.attachmentIds()).toEqual(['d1']);
    expect(svc.markFailed(null)).toEqual([]);
    expect(svc.markFailed({ code: 'validation_error' } as ProblemDetail)).toEqual([]);
    expect(
      svc.markFailed({ code: 'draft_attachments_missing' } as ProblemDetail),
    ).toEqual([]);
  });

  it('ends the draft when the submit says the token is invalid', async () => {
    const { svc } = setup();
    await svc.upload([file('a.pdf')]);
    expect(svc.markFailed({ code: 'draft_token_invalid' } as ProblemDetail)).toEqual(['d1']);
    expect(svc.token()).toBeNull();
    expect(sessionStorage.getItem(DRAFT_FILES_KEY)).toBeNull();
  });

  it('removes a draft on the server, a lost one only from the list', async () => {
    const { svc, remove } = setup();
    await svc.upload([file('a.pdf'), file('b.pdf')]);
    expect(await svc.remove('d1')).toBe(true);
    expect(remove).toHaveBeenCalledWith('d1', 'tok');
    svc.markFailed({ code: 'draft_attachments_missing', errors: [{ field: 'attachmentIds.d2', msg: '' }] } as ProblemDetail);
    expect(await svc.remove('d2')).toBe(true);
    expect(remove).toHaveBeenCalledTimes(1);
    expect(svc.files()).toEqual([]);
    expect(await svc.remove('nope')).toBe(true);
  });

  it('treats a 404 on delete as gone and keeps the file on other errors', async () => {
    const remove = jest
      .fn()
      .mockReturnValueOnce(throwError(() => httpError(404)))
      .mockReturnValueOnce(throwError(() => httpError(500)))
      .mockReturnValueOnce(throwError(() => new Error('net')));
    const { svc } = setup({ remove });
    await svc.upload([file('a.pdf'), file('b.pdf')]);
    expect(await svc.remove('d1')).toBe(true);
    expect(await svc.remove('d2')).toBe(false);
    expect(await svc.remove('d2')).toBe(false);
    expect(svc.files().map((f) => f.id)).toEqual(['d2']);
  });

  it('discards every draft on the server and forgets the token', async () => {
    const remove = jest
      .fn()
      .mockReturnValueOnce(of(undefined))
      .mockReturnValueOnce(throwError(() => httpError(500)));
    const { svc } = setup({ remove });
    await svc.upload([file('a.pdf'), file('b.pdf')]);
    await svc.discard();
    expect(remove.mock.calls.map((c) => c[0])).toEqual(['d1', 'd2']);
    expect(svc.token()).toBeNull();
    expect(svc.files()).toEqual([]);
    expect(sessionStorage.getItem(DRAFT_FILES_KEY)).toBeNull();
    // Without a token there is nothing to delete.
    await svc.discard();
    expect(remove).toHaveBeenCalledTimes(2);
  });

  it('shows a file as pending while it uploads', async () => {
    const answer = new Subject<DraftUpload>();
    const upload = jest.fn(() => answer);
    const resolve = (v: DraftUpload) => {
      answer.next(v);
      answer.complete();
    };
    const { svc } = setup({ upload, solve: jest.fn(async () => null) });
    const done = svc.upload([file('a.pdf', 5)], { fieldKey: 'k' });
    await Promise.resolve();
    await Promise.resolve();
    expect(svc.busy()).toBe(true);
    expect(svc.pending()[0]).toMatchObject({ filename: 'a.pdf', size: 5, fieldKey: 'k' });
    resolve({ attachment: attachment('d1'), draftToken: 't', draftExpiresAt: '2999-01-01T00:00:00Z' });
    await done;
    expect(svc.busy()).toBe(false);
  });

  it('maps every refusal to its text', () => {
    expect(uploadErrorKey(new Error('x'))).toBe('apply.files.error.upload');
    expect(uploadErrorKey(httpError(413, { code: 'draft_quota_exceeded' }))).toBe('apply.files.error.quota');
    expect(uploadErrorKey(httpError(400))).toBe('apply.files.error.altcha');
    expect(uploadErrorKey(httpError(413))).toBe('apply.files.error.tooLarge');
    expect(uploadErrorKey(httpError(415))).toBe('apply.files.error.type');
    expect(uploadErrorKey(httpError(429))).toBe('apply.files.error.rateLimit');
    expect(uploadErrorKey(httpError(503))).toBe('apply.files.error.unavailable');
    expect(uploadErrorKey(httpError(500))).toBe('apply.files.error.upload');
  });
});
